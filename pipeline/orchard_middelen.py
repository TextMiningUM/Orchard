"""Canonicaliseert en categoriseert de ~120 schrijfwijzen/OCR-varianten van `middel`-namen
in het logboek (Data/Orchard/OrchardLogbooks/orchard_logbook.db) voor het "Gebruik van
Middelen"-overzicht (menu, 2026-10-09) -- telt alle toepassingen bij elkaar op,
gecategoriseerd, per week/maand/kwartaal/jaar.

De ruwe `middel`-kolom bevat zoveel schrijfvarianten van hetzelfde product (bv. "Zink" /
"Zinc", "Borium" / "borium" / "Boriam", "Epso microtop" / "Epso Microtop" / "Epso Microstop
bitterzout") dat optellen zonder normalisatie misleidend zou zijn (hetzelfde product lijkt
dan meerdere kleinere, losse producten). ``_PRODUCT_REGISTRY`` hieronder is een EIGEN,
HANDMATIG OPGEBOUWDE mapping (2026-10-09, op basis van de volledige distincte lijst uit de
database en algemene kennis van Nederlandse fruitteelt-gewasbeschermingsmiddelen/
meststoffen) -- GEEN uit een officiële Ctgb-databank afgeleide lijst. Waar de identiteit of
categorie van een naam niet met voldoende zekerheid vaststond (bv. "Tracor", "Policur",
"Medesyn[?]", "Telder Kalifosfaat"), is die BEWUST in categorie "overig" gehouden in plaats
van geraden -- zelfde "nooit verzinnen"-discipline als de rest van dit project. Elke
aanname hieronder is in principe herzienbaar; de ruwe tekst blijft altijd beschikbaar via
drill-down naar de onderliggende logboekregel.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from pipeline.orchard_patterns import LogEntry, parse_hoeveelheid

CATEGORY_LABELS: dict[str, str] = {
    "fungicide_bactericide": "Gewasbescherming -- schimmel/bacterie",
    "insecticide_acaricide": "Gewasbescherming -- insect/mijt",
    "herbicide": "Gewasbescherming -- onkruid",
    "meststof": "Meststof / bladvoeding",
    "hulpstof": "Hulpstof (uitvloeier e.d.)",
    "bestuiving": "Bestuiving (bijen/hommels -- geen middel)",
    "overig": "Overig / niet met zekerheid te classificeren",
}

# canonical_name -> (category_key, [raw-tekst-aliassen, lowercase, "[?]"-markers al verwijderd])
_PRODUCT_REGISTRY: dict[str, tuple[str, list[str]]] = {
    # ── Meststoffen / bladvoeding ──────────────────────────────────────────────────────
    "Ureum": ("meststof", ["ureum (+ 325 gram, onduidelijk product)"]),
    "Borium": ("meststof", ["borium", "boriam"]),
    "Mangaan": ("meststof", ["magaan"]),
    "Epso": ("meststof", []),
    "Epso Microtop": ("meststof", ["epso microtop", "epso micro", "epso microstop bitterzout",
                                    "epso microtop bitterzout"]),
    "Epso Magnesium": ("meststof", ["epso magn", "epso magnesium", "epso mecron"]),
    "Kalifosfaat": ("meststof", []),
    "Kalifosfaat compleet": ("meststof", []),
    "Zink": ("meststof", ["zinc"]),
    "Kalifosfiet": ("meststof", []),
    "Kalifosfiet compleet": ("meststof", []),
    "Mantrac": ("meststof", ["mantrac (vlek/doorhaling, onduidelijk)"]),
    "Bitterzout": ("meststof", ["bitterzout (microtop)", "bitterzout (mg.)"]),
    "Magnesium": ("meststof", []),
    "Aminosol": ("meststof", []),
    "Ammosol": ("meststof", []),  # bewust NIET samengevoegd met Aminosol -- te onzeker of dit hetzelfde is
    "Yzer": ("meststof", ["ijzer"]),
    "Fosfiet": ("meststof", []),
    "Total leaf mix": ("meststof", ["total leaf"]),
    "Kalk": ("meststof", []),
    "Patentkali": ("meststof", ["patent kali"]),
    "12-10-18": ("meststof", ["12-10-18 stikstof"]),
    "BM Start": ("meststof", ["bm start"]),
    "Kali + fosfaat": ("meststof", ["kali en fosfaat", "kali + fosforfaat", "kali fosfaat + fosforfeet"]),
    "Kas": ("meststof", ["kas 27%", "kas (stikstof)"]),
    "Albatros 14-4-34+3MgO+micro": ("meststof", []),
    "Chloorhoudende Kalksalpeter": ("meststof", []),
    "DCM (kunstmest)": ("meststof", []),
    "Kali (chloorarm)": ("meststof", []),
    "Kali + fosf + zink (complet)": ("meststof", []),
    "Kopermeststof": ("meststof", []),  # naam zegt zelf expliciet "meststof", dus niet bij Koper (fungicide)
    "Kristallon blauw": ("meststof", []),
    "Kristalon rood": ("meststof", []),
    "Kunstmest (12-10-10)": ("meststof", []),
    "Mengmest": ("meststof", []),
    "Prills (korrels)": ("meststof", []),
    "Pruse Kali + Stikstof": ("meststof", []),
    "Stikstof": ("meststof", []),
    "Zinkfosfaat": ("meststof", []),
    "Goëmar": ("meststof", ["goemar", "goeman [?]", "goemer"]),  # zeewier-biostimulant
    # ── Gewasbescherming: schimmel/bacterie ────────────────────────────────────────────
    "Koper": ("fungicide_bactericide", []),  # hier steeds tegen pseudomonas/vruchtrot gebruikt
    "Koper foliplus": ("fungicide_bactericide", []),
    "Koper en Zink": ("fungicide_bactericide", []),
    "Syllit": ("fungicide_bactericide", ["syllit flow"]),
    "Zwavel": ("fungicide_bactericide", []),
    "Folicur": ("fungicide_bactericide", ["folicur [?]"]),
    "Rovral": ("fungicide_bactericide", ["roval (basf)"]),  # "Roval" = evidente OCR-misread van Rovral (BASF bevestigt)
    "Switch": ("fungicide_bactericide", []),
    "Delan": ("fungicide_bactericide", []),
    "Signum": ("fungicide_bactericide", ["signum[?]"]),
    "Serenade": ("fungicide_bactericide", []),
    "Captan": ("fungicide_bactericide", []),
    "Teldor": ("fungicide_bactericide", ["teldor [?]"]),
    # ── Gewasbescherming: insect/mijt ───────────────────────────────────────────────────
    "Calypso": ("insecticide_acaricide", []),
    "Movento": ("insecticide_acaricide", []),
    "Gazelle": ("insecticide_acaricide", ["gazella"]),
    "Gazelle + uitvloeier": ("insecticide_acaricide", [
        "gaselle + uitvloeier", "gazelle + uitvloeier (a-job[?])", "gazelle + uitvloeier (scherm[?])",
    ]),
    "Tracer": ("insecticide_acaricide", []),
    "Pirimor": ("insecticide_acaricide", ["perimor", "pirimor [?]"]),
    "Cantack": ("insecticide_acaricide", []),
    "Teppeki": ("insecticide_acaricide", []),
    "Xentari": ("insecticide_acaricide", []),
    "Apollo": ("insecticide_acaricide", ["appolo [?]"]),
    "Vertimec": ("insecticide_acaricide", ["vertimec gold"]),
    "Steward": ("insecticide_acaricide", ["stuward[?]"]),
    # ── Gewasbescherming: onkruid ───────────────────────────────────────────────────────
    "Basta": ("herbicide", []),
    "Onbekend onkruidmiddel": ("herbicide", ["tegen onkruid[?]", "wdazol[?] (onkruidbestrijder)"]),
    # ── Hulpstoffen ──────────────────────────────────────────────────────────────────────
    "Uitvloeier": ("hulpstof", ["uitvloeier [?]"]),
    "H. olie": ("hulpstof", []),  # horticultuur-/spuitolie
    "Kleurstof": ("hulpstof", []),
    # ── Bestuiving (geen middel) ─────────────────────────────────────────────────────────
    "Bijen": ("bestuiving", ["2 kasten bijen", "bijen nico"]),
    "Hommels": ("bestuiving", []),
    "2 kasten van Nico": ("bestuiving", []),
}

# Namen waarvan de identiteit/categorie NIET met voldoende zekerheid vaststond -- bewust in
# "overig" gehouden in plaats van geraden. Expliciet opgesomd (i.p.v. stilzwijgend) zodat
# duidelijk is WELKE namen bewust niet geclassificeerd zijn.
_ONZEKER_OVERIG = {
    "tracor", "policur", "medesyn[?]", "telder kalifosfaat", "kelder", "batavia", "complete",
    "cor teeuw[?]", "koolstoffilter", "vbc", "water",
}


def _normalize_raw(raw: str) -> str:
    """Strip OCR-onzekerheidsmarkers en overtollige spatie, lowercase -- voor lookup only;
    de CANONIEKE weergavenaam blijft altijd de nette vorm uit ``_PRODUCT_REGISTRY``."""
    cleaned = re.sub(r"\s*\[\?\]\s*$", "", (raw or "").strip())
    return cleaned.lower()


def _build_alias_index() -> dict[str, tuple[str, str]]:
    """lowercase-naam -> (canonical_name, category_key), inclusief de canonieke naam zelf.
    Elke alias wordt door dezelfde ``_normalize_raw()`` gehaald als een lookup-sleutel --
    anders zou een alias die zelf nog een "[?]"-marker bevat (bv. "goeman [?]") nooit
    matchen, want de lookup-kant normaliseert wel altijd (regressie gevonden 2026-10-09:
    "Goeman [?]" en "Appolo [?]" bleven stilzwijgend in "overig" hangen)."""
    index: dict[str, tuple[str, str]] = {}
    for canonical, (category, aliases) in _PRODUCT_REGISTRY.items():
        index[_normalize_raw(canonical)] = (canonical, category)
        for alias in aliases:
            index[_normalize_raw(alias)] = (canonical, category)
    return index


_ALIAS_INDEX = _build_alias_index()


def canonicalize_middel(raw: str) -> tuple[str, str]:
    """Retourneert (canonieke_naam, category_key). Onbekende/onzekere namen komen in
    category "overig" terecht met hun eigen (opgeschoonde) tekst als naam -- niets wordt
    stilzwijgend weggelaten."""
    key = _normalize_raw(raw)
    if key in _ALIAS_INDEX:
        return _ALIAS_INDEX[key]
    cleaned = re.sub(r"\s*\[\?\]\s*$", "", (raw or "").strip())
    return cleaned or "(leeg)", "overig"


@dataclass
class ToepassingRecord:
    entry_id: int
    date_iso: str
    canonical_middel: str
    category: str
    raw_middel: str
    raw_hoeveelheid: str
    value: float | None  # genormaliseerde hoeveelheid, of None als onleesbaar
    unit: str | None  # "ml" | "g" | None


def build_toepassing_records(entries: list[LogEntry]) -> list[ToepassingRecord]:
    """Pure: zet elke (middel, hoeveelheid)-toepassing uit `entries` om naar een
    ToepassingRecord met canonieke naam, categorie, en genormaliseerde hoeveelheid
    (hergebruikt ``pipeline.orchard_patterns.parse_hoeveelheid`` -- geen tweede
    hoeveelheid-parser)."""
    records = []
    for e in entries:
        if e.date is None:
            continue
        for middel, hoeveelheid in e.toepassingen:
            if not middel:
                continue
            canonical, category = canonicalize_middel(middel)
            parsed = parse_hoeveelheid(hoeveelheid)
            records.append(ToepassingRecord(
                entry_id=e.id, date_iso=e.date.isoformat(), canonical_middel=canonical,
                category=category, raw_middel=middel, raw_hoeveelheid=hoeveelheid or "",
                value=parsed[0] if parsed else None, unit=parsed[1] if parsed else None,
            ))
    return records


GRANULARITIES = ("week", "maand", "kwartaal", "jaar")


def period_key(d: date, granularity: str) -> str:
    """Pure: zet een datum om naar een sorteerbare periode-sleutel ("2024-W23" / "2024-05" /
    "2024-Q2" / "2024"). ISO-weeknummer (maandag-gebaseerd) voor "week"."""
    if granularity == "week":
        iso_year, iso_week, _ = d.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if granularity == "maand":
        return f"{d.year}-{d.month:02d}"
    if granularity == "kwartaal":
        kwartaal = (d.month - 1) // 3 + 1
        return f"{d.year}-Q{kwartaal}"
    if granularity == "jaar":
        return str(d.year)
    raise ValueError(f"Onbekende granulariteit: {granularity!r} (kies uit {GRANULARITIES})")


def aggregate_middelen(records: list[ToepassingRecord], granularity: str) -> list[dict]:
    """Pure: groepeert `records` per (periode, canonieke naam, categorie) en telt het aantal
    toepassingen + totale hoeveelheid op -- ml en g ALTIJD gescheiden gehouden (nooit bij
    elkaar opgeteld, dat zou net zo zinloos zijn als liters en kilo's samenvoegen). Elke rij:
    {"periode", "middel", "categorie", "aantal", "totaal_ml", "totaal_g"}."""
    buckets: dict[tuple[str, str, str], dict] = defaultdict(lambda: {"aantal": 0, "totaal_ml": 0.0, "totaal_g": 0.0})
    for r in records:
        key = (period_key(date.fromisoformat(r.date_iso), granularity), r.canonical_middel, r.category)
        b = buckets[key]
        b["aantal"] += 1
        if r.unit == "ml" and r.value is not None:
            b["totaal_ml"] += r.value
        elif r.unit == "g" and r.value is not None:
            b["totaal_g"] += r.value
    rows = [{"periode": p, "middel": m, "categorie": c, **b} for (p, m, c), b in buckets.items()]
    rows.sort(key=lambda row: (row["periode"], row["categorie"], row["middel"]))
    return rows
