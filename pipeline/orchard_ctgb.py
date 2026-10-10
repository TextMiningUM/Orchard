"""Ctgb-toelatingendatabank via de OPEN Ctgb MST public API (``public.mst.ctgb.nl``, JSON:API): toelatingsstatus en gebruiksvoorschriften
per middel voor kers -- maximale dosis, aantal toepassingen, minimaal interval, veiligheidstermijn (PHI), periode, groeistadium, opmerkingen en
de links naar de officiele gebruiksaanwijzing/het besluit (ontwerp G.31).

Geen abonnement of sleutel nodig: de Toelatingendatabank zelf gebruikt dezelfde API, het Ctgb geeft er alleen geen ondersteuning op (zie de
API-beschrijving, https://github.com/trivento/ctgb-mst-public-api). De oude bulk-export (``ctgb.blob.core.windows.net/...xls``) is wel dood.

Compliance-discipline (ontwerp B.1/B.11, "deterministische kern eerst"): getallen uit het voorschrift gaan LETTERLIJK van de API naar een kaart
(``format_card``) die de app zelf toont. Het taalmodel krijgt alleen ``format_model_facts`` -- status en verwijzing, geen doseringen -- zodat het
nooit een dosis kan "verbeteren" of verzinnen. De kaart zegt altijd dat de gebruiksaanwijzing/het etiket leidend is.

Veldnamen zijn gecontroleerd tegen echte antwoorden (Syllit, Movento, Switch, Signum, Pirimor, Calypso, Thiovit, Folicur, Rovral, 2026-10-10).
Let op: "Tuinkers" bevat de letters "kers" maar is geen kers; ``applies_to_cherry`` matcht daarom op hele gewasnamen.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

API_BASE = "https://public.mst.ctgb.nl/public-api/1.0"
SOURCE = "Ctgb Toelatingendatabank (MST public API, public.mst.ctgb.nl)"
CACHE_TTL_DAYS = 7
HTTP_TIMEOUT_S = 30
MAX_VALID_DETAILS = 6
MAX_EXPIRED_DETAILS = 6
CHERRY_NAMES = {"kers", "zoete kers", "zure kers", "kersen", "steenvruchten", "steenvrucht"}
MONTHS_NL = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december"]
DISCLAIMER = ("Dit is het wettelijke maximum volgens het Ctgb-voorschrift, geen aanbeveling en geen spuitadvies. De gebruiksaanwijzing/het etiket op het "
              "product is leidend; voorschriften kunnen wijzigen.")
_UA = "Mozilla/5.0 (compatible; OrchardAdviseur/1.0; +Ctgb MST public API client)"


class CtgbUnavailable(RuntimeError):
    """De Ctgb-API is niet bereikbaar en er is ook geen (verouderde) cache."""


def fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "")
    return re.sub(r"\s+", " ", "".join(c for c in folded if not unicodedata.combining(c)).lower()).strip()


def _nl(x: float | None) -> str:
    if x is None:
        return "-"
    return str(int(x)) if float(x).is_integer() else f"{x:g}".replace(".", ",")


def _date(s: str | None) -> date | None:
    """Ctgb-datums zijn middernacht Nederlandse tijd als UTC (22:00Z of 23:00Z de dag ervoor): rond naar de Nederlandse dag."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    d = dt.astimezone(timezone.utc).date()
    return d + timedelta(days=1) if dt.astimezone(timezone.utc).hour >= 22 else d


def nl_date(d: date | None) -> str:
    return "-" if d is None else f"{d.day} {MONTHS_NL[d.month - 1]} {d.year}"


# ── parsing ──────────────────────────────────────────────────────────────────────────────────────
def crop_names(nodes: list[dict]) -> set[str]:
    """Alle gewassen waarvoor een gebruik geldt: geselecteerde bladeren, plus alle namen onder een ``complete`` groep."""
    out: set[str] = set()

    def walk(items: list[dict], inherited: bool) -> None:
        for n in items:
            name = n.get("crop") or n.get("group")
            if "items" in n:
                complete = inherited or bool(n.get("complete"))
                if n.get("complete") and name:
                    out.add(name)
                walk(n["items"], complete)
            elif (inherited or n.get("selected")) and name:
                out.add(name)

    walk(nodes or [], False)
    return out


def applies_to_cherry(names: set[str]) -> bool:
    return any(fold(n) in CHERRY_NAMES for n in names)


def organism_labels(nodes: list[dict]) -> list[str]:
    """Geselecteerde aantasters/ziekten in gewone taal: 'Appelschurft, Schurft (Venturia inaequalis)'."""
    out: list[str] = []

    def walk(items: list[dict]) -> None:
        for n in items:
            if "organismScientific" in n and n.get("selected"):
                sci = n.get("organism") or n["organismScientific"]
                common = ", ".join(n.get("diseases") or [])
                out.append(f"{common} ({sci})" if common else sci)
            elif n.get("selected") and (n.get("group") or n.get("groupScientific")):
                out.append(n.get("group") or n["groupScientific"])
            if "items" in n:
                walk(n["items"])

    walk(nodes or [])
    return list(dict.fromkeys(out))


def _ratio(d: dict | None) -> tuple[float | None, str | None]:
    if not isinstance(d, dict):
        return None, None
    return d.get("ratio"), (d.get("measure") or {}).get("unit")


def _text(x) -> str:
    if isinstance(x, str):
        return x.strip()
    if isinstance(x, dict):
        for k in ("description", "text", "name", "value"):
            if x.get(k):
                return str(x[k]).strip()
        return json.dumps(x, ensure_ascii=False)
    return str(x)


@dataclass(frozen=True)
class CtgbUse:
    name: str
    summary: str
    cherry: bool
    explicit_cherry: bool                 # de samenvatting noemt kers zelf (en niet alleen via een brede groep)
    crops: tuple[str, ...]
    organisms: tuple[str, ...]
    locations: tuple[str, ...]
    methods: tuple[str, ...]
    dose: float | None
    dose_unit: str | None
    dose_per_season: float | None
    dose_per_season_unit: str | None
    per_season: float | None
    per_use: float | None
    min_interval_days: int | None
    phi_days: int | None
    month_from: int | None
    month_to: int | None
    bbch_from: str | None
    bbch_to: str | None
    water_min: float | None
    water_max: float | None
    minor_use: bool
    remarks: str
    restrictions: tuple[str, ...]


_FRUIT_GROUP = re.compile(r"vruchtbom|steenvrucht|fruitgewas")


def parse_use(u: dict) -> CtgbUse:
    names = crop_names(u.get("targetCrops"))
    summary = (u.get("nameOfUse") or {}).get("usesSummary", "")
    explicit = bool(re.search(r"\bkers\b", fold(summary)))
    # a broad group such as "Boomkwekerijgewassen" lists cherry too, but that is tree-nursery use, not fruit production
    cherry = applies_to_cherry(names) and (explicit or bool(_FRUIT_GROUP.search(fold(summary))))
    dose, unit = _ratio(u.get("maximumProductDose"))
    dose_season, unit_season = _ratio(u.get("maximumProductDosePerCropSeason"))
    amount = u.get("amountOfApplications") or {}
    timing = u.get("applicationTiming") or {}
    stage = u.get("growthStage") or {}
    water = u.get("watervolumeScale") or {}
    return CtgbUse(
        name=(u.get("nameOfUse") or {}).get("name", "").strip().lstrip("#").strip(), summary=summary, cherry=cherry,
        explicit_cherry=explicit, crops=tuple(sorted(names)), organisms=tuple(organism_labels(u.get("targetOrganisms"))),
        locations=tuple(x.get("description", "") for x in u.get("targetLocations") or []),
        methods=tuple(x.get("description", "") for x in u.get("applicationMethods") or []),
        dose=dose, dose_unit=unit, dose_per_season=dose_season, dose_per_season_unit=unit_season,
        per_season=amount.get("perCropSeason"), per_use=amount.get("perUse"),
        min_interval_days=u.get("minimumIntervalBetweenApplications"), phi_days=u.get("phiDays"),
        month_from=timing.get("fromMonth"), month_to=timing.get("toMonth"), bbch_from=stage.get("from"), bbch_to=stage.get("to"),
        water_min=water.get("min"), water_max=water.get("max"), minor_use=bool((u.get("minorUse") or {}).get("type") == "Ja"),
        remarks=(u.get("remarks") or "").strip(), restrictions=tuple(_text(r) for r in u.get("restrictions") or []),
    )


@dataclass(frozen=True)
class CtgbProduct:
    id: str
    name: str
    registration_number: str
    holder: str
    expiration: date | None
    expired: bool
    category: str
    active_substances: tuple[str, ...]
    formulation: str
    signal_word: str
    uses: tuple[CtgbUse, ...]
    manual_url: str | None
    decision_url: str | None

    @property
    def cherry_uses(self) -> tuple[CtgbUse, ...]:
        return tuple(sorted((u for u in self.uses if u.cherry), key=lambda u: (not u.explicit_cherry, u.name)))


def parse_product(payload: dict, listing: dict | None = None, today: date | None = None) -> CtgbProduct:
    d = payload.get("data", payload)
    today = today or date.today()
    listing = listing or {}
    actual = ((d.get("authorisation") or {}).get("actual") or [{}])[0]
    codings = actual.get("wCodings") or []
    expiration = _date(listing.get("expirationDate")) or max((x for x in (_date(c.get("expirationDate")) for c in codings) if x), default=None)
    substances = []
    for s in (d.get("compositions") or {}).get("substances") or []:
        if (s.get("function") or {}).get("isActiveSubstance"):
            unit = (s.get("concentrationUnit") or {}).get("description") or (s.get("concentrationUnit") or {}).get("unit", "")
            substances.append(f"{(s.get('substance') or {}).get('name', '?')} {_nl(_to_float(s.get('concentration')))} {unit}".strip())
    manual = next((c["instructionOfUse"]["document"]["link"] for c in codings
                   if (c.get("instructionOfUse") or {}).get("document", {}).get("link")), None)
    decision = next((x["document"]["link"] for x in d.get("decisions") or [] if (x.get("document") or {}).get("link")), None)
    holder = (d.get("authorisationHolder") or {}).get("companyName", "")
    return CtgbProduct(
        id=str(d.get("id", listing.get("id", ""))), name=d.get("name") or listing.get("name", "?"),
        registration_number=str(((d.get("authorisation") or {}).get("registrationNumber") or {}).get("nl")
                                or listing.get("registrationNumber", "")),
        holder=holder, expiration=expiration, expired=bool(expiration and expiration < today),
        category=(d.get("categoryType") or {}).get("description", ""),
        active_substances=tuple(substances),
        formulation=((d.get("compositions") or {}).get("formulationType") or {}).get("description", ""),
        signal_word=next((((c.get("labelling") or [{}])[0].get("signalWord") or {}).get("description", "")
                          for c in d.get("components") or []), ""),
        uses=tuple(parse_use(u) for u in d.get("uses") or []), manual_url=manual, decision_url=decision)


def _to_float(x) -> float | None:
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


# ── client with disk cache ───────────────────────────────────────────────────────────────────────
def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8"))


def default_cache_dir() -> Path:
    from core.paths import AgentPaths
    return AgentPaths.orchard().ctgb_dir


class CtgbClient:
    """Dunne client met schijf-cache (7 dagen) en terugval op een oudere cache als de API even weg is. ``fetch`` is injecteerbaar (test zonder netwerk)."""

    def __init__(self, fetch: Callable[[str], dict] | None = None, cache_dir: Path | None = None, ttl_days: int = CACHE_TTL_DAYS,
                 now: Callable[[], datetime] | None = None) -> None:
        self.fetch = fetch or _http_get_json
        self.cache_dir = cache_dir if cache_dir is not None else default_cache_dir()
        self.ttl = timedelta(days=ttl_days)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.notes: list[str] = []

    def get(self, path: str, params: dict | None = None) -> dict:
        url = f"{API_BASE}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        cache_file = self.cache_dir / f"{hashlib.sha1(url.encode()).hexdigest()}.json"
        cached = None
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            age = self.now() - datetime.fromisoformat(cached["fetched_at"])
            if age < self.ttl:
                return cached["payload"]
        except (OSError, ValueError, KeyError):
            cached = None
        try:
            payload = self.fetch(url)
        except Exception as exc:  # noqa: BLE001 -- offline: older cache beats nothing, but say so
            if cached is not None:
                days = (self.now() - datetime.fromisoformat(cached["fetched_at"])).days
                self.notes.append(f"De Ctgb-databank was niet bereikbaar; getoond zijn gegevens uit de cache van {days} dagen oud.")
                return cached["payload"]
            raise CtgbUnavailable(f"{type(exc).__name__}: {exc}") from exc
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({"url": url, "fetched_at": self.now().isoformat(), "payload": payload}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # a read-only deployment still works, just uncached
        return payload

    def search(self, name: str) -> list[dict]:
        return self.get("/authorisations", {"filter[productName]": name, "page[limit]": 50, "page[offset]": 0}).get("data", [])

    def detail(self, authorisation_id: str) -> dict:
        return self.get(f"/authorisations/{authorisation_id}", {"filter[locale]": "nl"})


@dataclass
class CtgbLookup:
    query: str
    products: list[CtgbProduct] = field(default_factory=list)
    total_matches: int = 0
    hidden_expired: int = 0               # verlopen toelatingen zonder kers-voorschrift: niet getoond
    notes: list[str] = field(default_factory=list)
    as_of: date = field(default_factory=date.today)

    @property
    def valid_products(self) -> list[CtgbProduct]:
        return [p for p in self.products if not p.expired]

    @property
    def valid_cherry_uses(self) -> list[CtgbUse]:
        return [u for p in self.valid_products for u in p.cherry_uses]


def lookup(query: str, client: CtgbClient | None = None, today: date | None = None) -> CtgbLookup:
    """Zoek een middel op (deel van de naam, hoofdletterongevoelig) en lees het voorschrift van de geldige toelatingen (en de meest recent verlopen)."""
    client = client or CtgbClient()
    today = today or date.today()
    q = fold(query)
    items = [i for i in client.search(query.strip()) if i.get("categoryType", {}).get("type") in ("PPP", "Adjuvant", None)]

    def rank(i: dict) -> int:
        n = fold(i["name"])
        return 0 if n == q else 1 if n.startswith(q) else 2

    items.sort(key=lambda i: (rank(i), fold(i["name"])))
    valid = [i for i in items if (_date(i.get("expirationDate")) or today) >= today]
    expired = sorted((i for i in items if i not in valid), key=lambda i: (rank(i), -(_date(i.get("expirationDate")) or date.min).toordinal()))
    products = []
    for item in valid[:MAX_VALID_DETAILS] + expired[:MAX_EXPIRED_DETAILS]:
        try:
            products.append(parse_product(client.detail(item["id"]), item, today))
        except CtgbUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 -- one malformed record must not hide the others
            client.notes.append(f"Voorschrift van '{item.get('name')}' kon niet worden gelezen ({type(exc).__name__}).")
    kept = [p for p in products if not p.expired or p.cherry_uses]
    hidden = len(products) - len(kept) + max(0, len(expired) - MAX_EXPIRED_DETAILS)
    return CtgbLookup(query=query, products=kept, total_matches=len(items), hidden_expired=hidden, notes=list(dict.fromkeys(client.notes)), as_of=today)


# ── presentation: the card (verbatim numbers) and the model-safe facts (no numbers) ───────────────
def _months(u: CtgbUse) -> str:
    if not u.month_from or not u.month_to:
        return "niet beperkt tot bepaalde maanden"
    return f"{MONTHS_NL[u.month_from - 1]} t/m {MONTHS_NL[u.month_to - 1]}"


def _per_season(u: CtgbUse) -> str:
    parts = []
    if u.per_season is not None:
        parts.append(f"{_nl(u.per_season)} per teeltseizoen")
    if u.per_use is not None:
        parts.append(f"{_nl(u.per_use)} per gebruik")
    return ", ".join(parts) or "niet vermeld"


def use_lines(u: CtgbUse) -> list[str]:
    lines = [f"- Maximale dosis per toepassing: **{_nl(u.dose)} {u.dose_unit or ''}**".rstrip()]
    if u.dose_per_season is not None:
        lines.append(f"- Maximale dosis per teeltseizoen: {_nl(u.dose_per_season)} {u.dose_per_season_unit or ''}".rstrip())
    lines.append(f"- Maximaal aantal toepassingen: **{_per_season(u)}**")
    lines.append(f"- Minimaal interval tussen toepassingen: **{_nl(u.min_interval_days) + ' dagen' if u.min_interval_days else 'niet vermeld'}**")
    lines.append(f"- Veiligheidstermijn (laatste toepassing tot oogst): **{_nl(u.phi_days) + ' dagen' if u.phi_days is not None else 'niet vermeld'}**")
    stage = f"BBCH {u.bbch_from}-{u.bbch_to}" if u.bbch_from and u.bbch_to else "niet vermeld"
    lines.append(f"- Periode: {_months(u)} · Groeistadium: {stage}")
    if u.water_min or u.water_max:
        lines.append(f"- Watervolume: {_nl(u.water_min)}-{_nl(u.water_max)} (eenheid zoals op de gebruiksaanwijzing)")
    if u.locations or u.methods:
        lines.append(f"- Teeltomstandigheden/methode: {', '.join(x for x in (*u.locations, *u.methods) if x)}")
    if u.organisms:
        lines.append(f"- Doel: {'; '.join(u.organisms[:6])}" + (" …" if len(u.organisms) > 6 else ""))
    if u.minor_use:
        lines.append("- Kleine teelt (minor use): ja")
    if u.remarks:
        text = re.sub(r"\s*\n\s*", " ", u.remarks)
        lines.append("- Opmerkingen van het Ctgb: " + (text if len(text) <= 1500 else text[:1500] + " … (zie de gebruiksaanwijzing)"))
    for r in u.restrictions:
        lines.append(f"- Beperking: {r}")
    return lines


def status_text(p: CtgbProduct) -> str:
    if p.expiration is None:
        return "geldigheid onbekend"
    if p.expired:
        return (f"⚠ **verlopen op {nl_date(p.expiration)}** (er kan een opgebruik-/afleveringstermijn gelden: zie het toelatingsbesluit of de "
                "gebruiksaanwijzing)")
    return f"geldig tot {nl_date(p.expiration)}"


def format_card(lk: CtgbLookup) -> str:
    """De officiele voorschriftkaart, deterministisch uit de API: alleen de gebruiken voor kers (en wat er voor andere gewassen staat, in een regel)."""
    if not lk.products:
        if lk.total_matches:
            return (f"**Ctgb-databank: voor '{lk.query}' zijn {lk.total_matches} toelating(en) gevonden, maar geen geldige toelating en geen (verlopen) "
                    f"voorschrift voor kers.** {DISCLAIMER}")
        return (f"**Ctgb-databank: geen product gevonden voor '{lk.query}'.** Controleer de schrijfwijze, of het middel is geen gewasbeschermingsmiddel "
                f"(bijv. een meststof of bladvoeding valt niet onder het Ctgb). {DISCLAIMER}")
    out = [f"### Officieel Ctgb-voorschrift voor kers: '{lk.query}' (peildatum {nl_date(lk.as_of)})", ""]
    for p in sorted(lk.products, key=lambda p: (p.expired, fold(p.name))):
        head = f"#### {p.name} · registratienummer {p.registration_number or '?'}"
        meta = [status_text(p)]
        if p.active_substances:
            meta.append("werkzame stof: " + ", ".join(p.active_substances))
        if p.formulation:
            meta.append(p.formulation.lower())
        if p.signal_word:
            meta.append(f"signaalwoord: {p.signal_word.lower()}")
        out += [head, " · ".join(meta)]
        if p.holder:
            out.append(f"Toelatinghouder: {p.holder}")
        cherry = p.cherry_uses
        if cherry:
            for u in cherry:
                out += ["", f"**Gebruik {u.name or '?'} ({u.summary})**", *use_lines(u)]
        else:
            others = sorted({u.summary for u in p.uses if u.summary})[:4]
            out.append("**Geen gebruiksvoorschrift voor kers bij dit middel.**" + (f" Wel toegelaten voor: {'; '.join(others)}." if others else ""))
        links = [f"[gebruiksaanwijzing (PDF)]({p.manual_url})" if p.manual_url else "", f"[toelatingsbesluit (PDF)]({p.decision_url})" if p.decision_url else ""]
        if any(links):
            out += ["", "Officiële documenten: " + " · ".join(x for x in links if x)]
        out.append("")
    out += [f"*Bron: {SOURCE}. {DISCLAIMER}*"]
    if lk.hidden_expired:
        out.append(f"*{lk.hidden_expired} verlopen toelating(en) zonder kers-voorschrift zijn niet getoond.*")
    out += [f"*{n}*" for n in lk.notes]
    return "\n".join(out)


def format_model_facts(lk: CtgbLookup) -> str:
    """Wat het taalmodel te zien krijgt: status en verwijzing, bewust GEEN doseringen of limieten (die staan alleen op de kaart)."""
    head = f"COMPLIANCE-GUARDRAIL: Ctgb-databank geraadpleegd voor '{lk.query}' (peildatum {lk.as_of.isoformat()})."
    if not lk.products:
        if lk.total_matches:
            return (f"{head} {lk.total_matches} toelating(en) onder die naam, maar geen geldige toelating en geen kers-voorschrift. Doe geen uitspraak over "
                    "toelating of dosering; verwijs naar de Ctgb-databank en het etiket.")
        return (f"{head} Geen product gevonden onder die naam (mogelijk een meststof, een andere schrijfwijze of een niet-toegelaten middel). "
                "Doe geen uitspraak over toelating of dosering; verwijs naar de Ctgb-databank en het etiket.")
    bits = []
    for p in sorted(lk.products, key=lambda p: (p.expired, fold(p.name))):
        uses = ", ".join(u.name or "?" for u in p.cherry_uses)
        state = "verlopen toelating" if p.expired else "geldige toelating"
        bits.append(f"{p.name} (nr {p.registration_number}): {state}; " + (f"voorschrift voor kers aanwezig ({uses})" if uses else "geen kers-voorschrift gevonden"))
    return (f"{head} Gevonden: " + " | ".join(bits) + ". De officiële voorschriftkaart (dosering, aantal toepassingen, interval, veiligheidstermijn) wordt "
            "apart onder je antwoord getoond. Noem zelf GEEN doseringen of limieten en doe geen eigen toelatingsuitspraak; verwijs naar de kaart, de "
            "gebruiksaanwijzing en het etiket.")


def use_rows(lk: CtgbLookup) -> list[dict]:
    rows = []
    for p in sorted(lk.products, key=lambda p: (p.expired, fold(p.name))):
        for u in p.cherry_uses or [None]:
            rows.append({
                "Middel": p.name, "Reg.nr": p.registration_number, "Status": "verlopen" if p.expired else "geldig",
                "Geldig tot": nl_date(p.expiration), "Gebruik": u.name if u else "geen kers-voorschrift",
                "Max. dosis": f"{_nl(u.dose)} {u.dose_unit or ''}".strip() if u else "", "Max. toepassingen": _per_season(u) if u else "",
                "Min. interval (d)": u.min_interval_days if u else None, "Veiligheidstermijn (d)": u.phi_days if u else None,
                "Periode": _months(u) if u else "", "BBCH": f"{u.bbch_from}-{u.bbch_to}" if u and u.bbch_from else "",
            })
    return rows


_STOP_CAPS = {"ctgb", "kers", "kersen", "kersenboomgaard", "nederland", "nederlands", "wat", "welk", "welke", "hoeveel", "mag", "moet", "ik", "de", "het", "een",
              "ctgb-databank", "etiket", "spuiten", "middel", "dosering", "toegelaten"}


def detect_product_names(question: str, known: set[str] | None = None) -> list[str]:
    """Middelnamen in een vraag: bekende logboeknamen (``known``, gevouwen) en hoofdletterwoorden midden in de zin. Hooguit 2, in volgorde van voorkomen."""
    known = known or set()
    words = re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\-]+", question)
    found: list[str] = []
    for i, w in enumerate(words):
        f = fold(w)
        if f in _STOP_CAPS or len(f) < 4:
            continue
        if f in known or (i > 0 and w[0].isupper() and not w.isupper()):
            if f not in (fold(x) for x in found):
                found.append(w)
    return found[:2]
