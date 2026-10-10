"""Logboek-kalender: "wat deed ik rond deze tijd?" uit de eigen 2013-heden-historie van de teler (ontwerp G.30).

Pure functies over ``LogEntry``-records (zelfde discipline als ``orchard_patterns``/``orchard_middelen``; de enige database-aanraking staat in
``load_calendar_data``). Dit is **eigen historie, geen advies**: het laat zien wat de teler zelf in deze weken deed en hoe vaak, niet of het goed was
(het logboek bevat geen uitkomsten) en niet of het nu is toegelaten of hoe het gedoseerd moet worden -- hoeveelheden komen daarom bewust nergens in de
uitvoer (compliance-guardrail, ontwerp B.11). Namen komen uit ``orchard_middelen.canonicalize_middel``.

Twee datakwaliteitscorrecties die de tellingen anders vertekenen:
  * ``dedupe_entries``: identieke regels (zelfde datum + zelfde middelen en hoeveelheden) die op VERSCHILLENDE pagina's staan, worden één keer geteld.
    Aanleiding: 2020 is twee keer ingescand (``jaar 2020.pdf`` en ``jaar 2020-2.pdf``), wat 45 regels verdubbelde. Dezelfde regel twee keer op
    dezelfde pagina blijft staan (dat kan echt twee bespuitingen op één dag zijn).
  * ``MIN_ENTRIES_PER_YEAR``: een jaar met (bijna) geen regels (2024: één) telt niet als "jaar met logboek", anders lijkt elk middel in dat jaar "niet gedaan".
"""
from __future__ import annotations

import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pipeline.orchard_middelen import CATEGORY_LABELS, canonicalize_middel
from pipeline.orchard_patterns import LogEntry, load_entries

MIN_ENTRIES_PER_YEAR = 8
USUAL_FRACTION = 0.5          # "gebruikelijk": in minstens de helft van de jaren met logboek
DEFAULT_WINDOW_DAYS = 14
CAVEAT = ("Dit is je eigen historie, geen advies: het logboek bevat geen uitkomsten en zegt niet of een middel nu is toegelaten of hoe het gedoseerd moet "
          "worden (controleer dat bij Ctgb en de kennisbank).")


def default_db_path() -> Path:
    from core.paths import AgentPaths
    return AgentPaths.orchard().logbooks_dir / "orchard_logbook.db"


@dataclass(frozen=True)
class CalendarData:
    entries: list[LogEntry]
    removed_duplicates: int
    verified: int
    total: int


def dedupe_entries(entries: list[LogEntry], page_ids: dict[int, int] | None = None) -> tuple[list[LogEntry], int]:
    """Telt identieke regels van verschillende pagina's één keer. Zonder ``page_ids`` geldt elke regel als een eigen pagina."""
    seen: dict[tuple, set[int]] = {}
    kept: list[LogEntry] = []
    removed = 0
    for e in sorted(entries, key=lambda e: (e.datum_iso or "", e.id)):
        if not e.datum_iso or not e.toepassingen:
            kept.append(e)
            continue
        key = (e.datum_iso, tuple(sorted((canonicalize_middel(m)[0], (h or "").strip().lower()) for m, h in e.toepassingen)))
        page = page_ids.get(e.id, e.id) if page_ids else e.id
        pages = seen.setdefault(key, set())
        if pages and page not in pages:
            removed += 1
            continue
        pages.add(page)
        kept.append(e)
    return kept, removed


def load_calendar_data(db_path: Path | None = None) -> CalendarData:
    con = sqlite3.connect(str(db_path or default_db_path()))
    try:
        entries = load_entries(con)
        page_ids = {r[0]: r[1] for r in con.execute("select id, page_id from entries")}
        verified, total = con.execute("select coalesce(sum(geverifieerd), 0), count(*) from entries").fetchone()
    finally:
        con.close()
    kept, removed = dedupe_entries(entries, page_ids)
    return CalendarData(kept, removed, int(verified), int(total))


@dataclass(frozen=True)
class ProductWindow:
    middel: str
    category: str
    years: tuple[int, ...]            # jaren (met logboek, vóór het referentiejaar) waarin het in het venster voorkwam
    years_back: tuple[int, ...]       # idem, alleen de dagen vóór/op de referentiedatum
    applications: int
    median_interval_days: int | None
    purposes: tuple[tuple[str, int], ...]   # (doel uit de opmerking, aantal jaren)
    this_year: int                    # toepassingen dit jaar in het stuk vóór/op de referentiedatum

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)


@dataclass(frozen=True)
class CalendarReport:
    ref: date
    window_days: int
    history_years: tuple[int, ...]    # jaren met genoeg regels (vóór het referentiejaar)
    products: list[ProductWindow]
    this_year_entries: int
    this_year_comparable: bool        # genoeg regels dit jaar om "nog niet gedaan" te mogen zeggen
    missing_this_year: list[ProductWindow]
    removed_duplicates: int = 0
    verified: int = 0
    total: int = 0


_PURPOSE = re.compile(r"\btegen\s+([^.;\n]+)")
_NOT_A_TARGET = re.compile(r"wind|graden|°|temp|geen|beetje|celsius|regen|droog|zon|bewolkt|onleesbaar|onduidelijk")


def purposes_of(remarks: str) -> list[str]:
    """Doelen uit een opmerking als "Tegen pseudomonas en bladval." -> ["pseudomonas", "bladval"]. Weerzinnen ("beetje wind") tellen niet mee."""
    out = []
    for m in _PURPOSE.finditer(re.sub(r"\[\?\]", "", (remarks or "").lower())):
        for part in re.split(r",|&|\ben\b", m.group(1)):
            part = re.sub(r"^(tegen|de|het|een)\s+", "", part.strip())
            if 2 < len(part) <= 30 and not _NOT_A_TARGET.search(part):
                out.append(part)
    return out


def _anchor(year: int, ref: date) -> date:
    try:
        return date(year, ref.month, ref.day)
    except ValueError:  # 29 februari in een gewoon jaar
        return date(year, ref.month, 28)


def build_calendar(entries: list[LogEntry], ref: date, window_days: int = DEFAULT_WINDOW_DAYS, *, removed_duplicates: int = 0,
                   verified: int = 0, total: int = 0) -> CalendarReport:
    dated = [e for e in entries if e.date is not None]
    per_year = Counter(e.date.year for e in dated)
    history = tuple(sorted(y for y, n in per_year.items() if y < ref.year and n >= MIN_ENTRIES_PER_YEAR))
    this_year_entries = per_year.get(ref.year, 0)

    dates: dict[tuple[str, int], list[date]] = defaultdict(list)        # (middel, jaar) -> datums in het venster
    category: dict[str, str] = {}
    purposes: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    this_year: Counter = Counter()
    for e in dated:
        y = e.date.year
        if y not in history and y != ref.year:
            continue
        delta = (e.date - _anchor(y, ref)).days
        if abs(delta) > window_days or (y == ref.year and delta > 0):
            continue
        for raw, _hoeveelheid in e.toepassingen:
            if not raw:
                continue
            name, cat = canonicalize_middel(raw)
            category[name] = cat
            if y == ref.year:
                this_year[name] += 1
                continue
            dates[(name, y)].append(e.date)
            for p in purposes_of(e.opmerkingen):
                purposes[name][p].add(y)

    names = {n for n, _ in dates}
    products = []
    for name in names:
        by_year = {y: sorted(ds) for (n, y), ds in dates.items() if n == name}
        gaps = [(b - a).days for ds in by_year.values() for a, b in zip(ds, ds[1:]) if (b - a).days > 0]
        back = tuple(sorted(y for y, ds in by_year.items() if any(d <= _anchor(y, ref) for d in ds)))
        top = sorted(((p, len(ys)) for p, ys in purposes[name].items()), key=lambda t: (-t[1], t[0]))[:2]
        products.append(ProductWindow(name, category[name], tuple(sorted(by_year)), back, sum(len(v) for v in by_year.values()),
                                      round(statistics.median(gaps)) if gaps else None, tuple(top), this_year.get(name, 0)))
    products.sort(key=lambda p: (-len(p.years), -p.applications, p.middel))
    comparable = this_year_entries >= MIN_ENTRIES_PER_YEAR
    need = max(1, USUAL_FRACTION * len(history))
    missing = [p for p in products if comparable and len(p.years_back) >= need and p.this_year == 0]
    return CalendarReport(ref, window_days, history, products, this_year_entries, comparable, missing, removed_duplicates, verified, total)


def format_calendar(r: CalendarReport, *, limit: int = 12) -> str:
    """Nederlandse feitentekst (adviseur-tool en pagina delen dit); alles is geteld, niets is door het model bedacht."""
    nh = len(r.history_years)
    if nh == 0:
        return "Het logboek heeft te weinig jaren met voldoende regels om een kalender te maken. " + CAVEAT
    lines = [f"Logboek-kalender rond {r.ref.day}-{r.ref.month}-{r.ref.year} (±{r.window_days} dagen), gebaseerd op {nh} jaar met logboek "
             f"({r.history_years[0]}-{r.history_years[-1]}):"]
    if not r.products:
        lines.append("- In deze periode staat er in geen enkel jaar iets in het logboek.")
    for p in r.products[:limit]:
        bits = [f"{p.middel} ({p.category_label}): in {len(p.years)} van {nh} jaar, {p.applications} toepassingen"]
        if p.median_interval_days:
            bits.append(f"meestal om de ~{p.median_interval_days} dagen")
        if p.purposes:
            bits.append("doel: " + ", ".join(f"{t} ({n}×)" for t, n in p.purposes))
        lines.append("- " + "; ".join(bits))
    if len(r.products) > limit:
        lines.append(f"- ... en nog {len(r.products) - limit} andere middelen met minder voorkomen.")
    if r.this_year_comparable:
        if r.missing_this_year:
            lines.append("Gebruikelijk rond deze tijd, maar dit jaar nog niet in het logboek: "
                         + ", ".join(f"{p.middel} ({len(p.years_back)} van {nh} jaar)" for p in r.missing_this_year[:8]) + ".")
        else:
            lines.append("Alles wat gebruikelijk is rond deze tijd staat dit jaar al in het logboek.")
    else:
        lines.append(f"Dit jaar ({r.ref.year}) staan er {r.this_year_entries} regels in het logboek; te weinig om te zeggen wat er nog ontbreekt.")
    if r.total:
        lines.append(f"Datakwaliteit: {r.verified} van {r.total} regels handmatig geverifieerd; {r.removed_duplicates} dubbel ingescande regels zijn "
                     "één keer geteld.")
    lines.append(CAVEAT)
    return "\n".join(lines)


def parse_calendar_arg(arg: str | None, today: date | None = None) -> tuple[date, int]:
    """Tool-argument: leeg = vandaag (±14 d); maandnaam = midden van die maand (±15 d); ISO-datum = die dag (±14 d)."""
    today = today or date.today()
    text = (arg or "").strip().lower()
    if not text:
        return today, DEFAULT_WINDOW_DAYS
    m = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if m:
        try:
            return date.fromisoformat(m.group()), DEFAULT_WINDOW_DAYS
        except ValueError:
            pass
    from pipeline.orchard_logbook_rag import MONTHS
    for i, name in enumerate(MONTHS, start=1):
        if name in text or (len(name) > 3 and name[:3] in text.split()):
            return date(today.year, i, 15), 15
    return today, DEFAULT_WINDOW_DAYS


def calendar_facts(arg: str | None, db_path: Path | None = None, today: date | None = None) -> str:
    ref, window = parse_calendar_arg(arg, today)
    data = load_calendar_data(db_path)
    return format_calendar(build_calendar(data.entries, ref, window, removed_duplicates=data.removed_duplicates,
                                          verified=data.verified, total=data.total))


__all__ = ["CalendarData", "CalendarReport", "ProductWindow", "build_calendar", "calendar_facts", "dedupe_entries", "format_calendar",
           "load_calendar_data", "parse_calendar_arg", "purposes_of"]
