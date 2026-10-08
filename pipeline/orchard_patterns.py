"""Pattern-mining over the Track 2 logbook database (design doc Sec A.6/B.4, "Patroonherkenning"
menu) -- automatically surfaces the most salient, harvest-relevant patterns in the teler's own
2013-2026 logbooks instead of requiring them to go looking for one, and keeps the exact
contributing entries attached to each pattern so the UI can drill straight down to the real data.

Three trend-based pattern kinds are detected, all scored on the same 0..1 "importance" scale so
they can be ranked together across kinds:
  - seizoenstiming -- is the typical calendar timing of a treatment category (first occurrence
                      per year) shifting earlier/later over the years? (e.g. climate-driven
                      earlier pest pressure -- directly actionable: "moet ik dit jaar vroeger
                      beginnen te controleren/spuiten?")
  - frequentie     -- is the number of treatments per year for a category trending up or down?
  - dosering       -- is the average dose per application for a product trending up? (an early,
                      indirect signal worth a closer look -- rising dose can mean declining
                      efficacy/resistance, but can also just mean a bigger orchard/more trees;
                      this module flags it, it does NOT diagnose the cause)
Plus one always-shown, non-trend reference pattern:
  - kalender       -- a month-by-month overview of which treatment categories typically happen
                      when, aggregated over all years (a practical calendar, not an anomaly).

TARGET_CATEGORIES/HARVEST_WEIGHT below are this project's OWN heuristic judgement of how
directly each category affects the cherry HARVEST (fruit quality/yield) specifically -- NOT a
literature-sourced ranking (unlike pipeline/orchard_phenology_spec.py's cited thresholds).
Documented here precisely so it's easy to challenge/adjust; see design doc Deel F if this needs
revisiting once real yield figures are available (open question 5).
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

import numpy as np

# ── Vocabulaire: vrije-tekst "opmerkingen" -> genormaliseerde probleemcategorie ───────────────
# Elke categorie heeft substring-triggers (lowercased) gevonden door het echte logboek-vocabulaire
# te inspecteren (2026-10-08 sessie) -- geen vooraf aangenomen lijst. Eén entry kan meerdere
# categorieën raken (bv. "Tegen luis + suzukii vlieg").
TARGET_CATEGORIES: dict[str, dict] = {
    "fruitvliegen": {
        "label": "Fruitvliegen (kersenvlieg/suzukii)",
        "keywords": ["kersenvlieg", "suzukii", "suzuki vlieg", "suzuki fruitvlieg", "suzuki-fruitvlieg", "fruitvlieg"],
        "harvest_weight": 1.0,
        "why": "Tast het rijpe fruit zelf aan (maden) -- rechtstreeks oogstverlies/afkeuring.",
    },
    "vruchtrot": {
        "label": "Vruchtrot (Monilia)",
        "keywords": ["vruchtrot", "monilia", "monillia"],
        "harvest_weight": 0.95,
        "why": "Directe vruchtrotting rond de oogst -- rechtstreeks oogstverlies.",
    },
    "bacterie_kanker": {
        "label": "Bacterieziekte / kanker (pseudomonas)",
        "keywords": ["pseudomonas", "bacterie", "bacterien", "bacteriën", "kanker"],
        "harvest_weight": 0.6,
        "why": "Kan takken/bomen verzwakken of doden -- schaadt toekomstige oogstcapaciteit.",
    },
    "bladvlekkenziekte": {
        "label": "Bladvlekkenziekte",
        "keywords": ["bladvlekkenziekte", "bladvlekziekte"],
        "harvest_weight": 0.5,
        "why": "Verzwakt de boom (minder blad) -- indirect effect op vruchtzetting/-groei.",
    },
    "bladvalziekte": {
        "label": "Bladvalziekte",
        "keywords": ["bladvalziekte", "bladval"],
        "harvest_weight": 0.5,
        "why": "Vroegtijdige bladval -- indirect effect op boomvitaliteit en volgend seizoen.",
    },
    "hagelschot": {
        "label": "Hagelschotziekte",
        "keywords": ["hagelschot"],
        "harvest_weight": 0.55,
        "why": "Tast blad en twijgen aan -- indirect effect op boomvitaliteit.",
    },
    "spint": {
        "label": "Spint (spintmijt)",
        "keywords": ["spint"],
        "harvest_weight": 0.4,
        "why": "Bladschade bij hoge druk -- indirect effect op vruchtkwaliteit/-groei.",
    },
    "luis": {
        "label": "Luis",
        "keywords": ["luis", "luizen", "kersenluis"],
        "harvest_weight": 0.4,
        "why": "Verzwakt jonge scheuten/blad -- indirect effect op groei en vruchtzetting.",
    },
    "rupsen": {
        "label": "Rupsen / bladrollers",
        "keywords": ["rupsen", "bladroller"],
        "harvest_weight": 0.4,
        "why": "Vreten aan blad/knoppen -- indirect effect op groei en volgend seizoen.",
    },
    "bestuiving": {
        "label": "Bestuiving / bijen",
        "keywords": ["bestuiving", "bijen", "bijenkast", "bloesem"],
        "harvest_weight": 0.9,
        "why": "Zoete kers heeft kruisbestuiving nodig -- timing van bijenactiviteit is een "
               "directe opbrengstfactor (geen/slechte bestuiving = geen vrucht).",
    },
    "voeding": {
        "label": "Bladvoeding / bemesting",
        "keywords": ["voedingssupplement", "bladvoeding", "boomversterker", "bemesting", "stikstof", "kunstmest"],
        "harvest_weight": 0.3,
        "why": "Algemene boomvoeding -- beïnvloedt groei/opbrengst indirect en geleidelijk.",
    },
}

MIN_YEARS_FOR_TREND = 4  # fewer years of data than this -> trend would be noise, not a pattern


@dataclass
class LogEntry:
    id: int
    jaar: str
    datum_iso: str | None
    opmerkingen: str
    toepassingen: list[tuple[str, str]] = field(default_factory=list)

    @property
    def date(self) -> date | None:
        if not self.datum_iso:
            return None
        try:
            return date.fromisoformat(self.datum_iso)
        except ValueError:
            return None


@dataclass
class Pattern:
    id: str
    title: str
    kind: str  # "seizoenstiming" | "frequentie" | "dosering" | "kalender"
    importance: float
    summary: str
    chart: dict
    entry_ids: list[int] = field(default_factory=list)


def load_entries(conn: sqlite3.Connection) -> list[LogEntry]:
    """Reads every logbook entry + its toepassingen into plain LogEntry records -- the single
    DB-touching function in this module; every detector below is a pure function over these
    records, so detectors can be unit-tested with synthetic data (no DB fixture needed)."""
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT e.id, p.jaar, e.datum_iso, e.opmerkingen
        FROM entries e JOIN pages p ON e.page_id = p.id
    """)
    rows = cur.fetchall()
    entries = {
        r["id"]: LogEntry(id=r["id"], jaar=r["jaar"], datum_iso=r["datum_iso"], opmerkingen=r["opmerkingen"] or "")
        for r in rows
    }
    cur.execute("SELECT entry_id, middel, hoeveelheid FROM toepassingen ORDER BY entry_id, volgorde")
    for r in cur.fetchall():
        if r["entry_id"] in entries:
            entries[r["entry_id"]].toepassingen.append((r["middel"] or "", r["hoeveelheid"] or ""))
    return list(entries.values())


def match_categories(opmerkingen: str) -> set[str]:
    """Returns every TARGET_CATEGORIES key whose keyword appears (as a substring) in
    `opmerkingen`, case-insensitive. An entry commonly matches more than one category."""
    text = (opmerkingen or "").lower()
    return {cat for cat, spec in TARGET_CATEGORIES.items() if any(kw in text for kw in spec["keywords"])}


_UNIT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kilogram|milliliter|liter|ltr|kg|gram|gr|ml|cc|g|l)\b", re.IGNORECASE,
)
_VOLUME_TO_ML = {"liter": 1000.0, "ltr": 1000.0, "l": 1000.0, "milliliter": 1.0, "ml": 1.0, "cc": 1.0}
_WEIGHT_TO_G = {"kilogram": 1000.0, "kg": 1000.0, "gram": 1.0, "gr": 1.0, "g": 1.0}


def parse_hoeveelheid(text: str) -> tuple[float, str] | None:
    """Parses a free-text Dutch quantity like "0,6 liter", "300 ml", "15 kg op 200 liter water"
    into (normalized_value, base_unit) where base_unit is "ml" (volumes) or "g" (weights) -- the
    FIRST number+unit found is taken as the product amount (dilution water, when mentioned,
    always comes second in this logbook's phrasing, e.g. "... op 200 liter water"). Returns None
    if no recognizable number+unit is found (e.g. a bare product name with no quantity noted)."""
    if not text:
        return None
    m = _UNIT_RE.search(text)
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    if unit in _VOLUME_TO_ML:
        return value * _VOLUME_TO_ML[unit], "ml"
    if unit in _WEIGHT_TO_G:
        return value * _WEIGHT_TO_G[unit], "g"
    return None  # pragma: no cover -- every branch of _UNIT_RE's alternation is one of the above


def _linear_trend(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Returns (slope, intercept) of the least-squares line through (xs, ys)."""
    slope, intercept = np.polyfit(xs, ys, 1)
    return float(slope), float(intercept)


def detect_seasonal_timing_patterns(entries: list[LogEntry]) -> list[Pattern]:
    """For each category: the day-of-year of its FIRST mention per year, across every year it
    was mentioned at all. A meaningful slope (days/year) means that treatment's typical timing
    is drifting earlier or later -- directly actionable ("dit jaar waarschijnlijk eerder/later
    controleren dan vorig jaar")."""
    patterns = []
    by_cat_year: dict[str, dict[int, tuple[int, int]]] = defaultdict(dict)  # cat -> year -> (doy, entry_id)
    for e in entries:
        d = e.date
        if d is None:
            continue
        doy = d.timetuple().tm_yday
        for cat in match_categories(e.opmerkingen):
            existing = by_cat_year[cat].get(d.year)
            if existing is None or doy < existing[0]:
                by_cat_year[cat][d.year] = (doy, e.id)

    for cat, year_map in by_cat_year.items():
        if len(year_map) < MIN_YEARS_FOR_TREND:
            continue
        years = sorted(year_map)
        doys = [year_map[y][0] for y in years]
        slope, intercept = _linear_trend([float(y) for y in years], [float(d) for d in doys])
        spec = TARGET_CATEGORIES[cat]
        effect = min(1.0, abs(slope) / 5.0)  # >=5 dagen/jaar verschuiving telt als "maximaal" effect
        confidence = min(1.0, len(years) / 8.0)
        importance = spec["harvest_weight"] * effect * confidence
        direction = "vroeger" if slope < 0 else "later"
        patterns.append(Pattern(
            id=f"seizoenstiming_{cat}",
            title=f"{spec['label']}: eerste moment per jaar verschuift {direction}",
            kind="seizoenstiming",
            importance=importance,
            summary=(
                f"Het eerste moment in het seizoen dat '{spec['label'].lower()}' genoteerd staat, "
                f"verschuift gemiddeld {abs(slope):.1f} dag/jaar {direction} ({years[0]}-{years[-1]}, "
                f"{len(years)} jaar met data). {spec['why']}"
            ),
            chart={
                "type": "scatter_trend", "x": years, "y": doys,
                "trend_y": [slope * y + intercept for y in years],
                "y_axis_title": "Dag van het jaar (1-366) van eerste vermelding",
            },
            entry_ids=[year_map[y][1] for y in years],
        ))
    return patterns


def detect_frequency_trend_patterns(entries: list[LogEntry]) -> list[Pattern]:
    """For each category: number of matching entries per year, across every year the logbook has
    ANY data for (so a true zero year counts, not just an absent one) -- a rising/falling
    treatment frequency over time (e.g. growing pest pressure)."""
    all_years = sorted({e.date.year for e in entries if e.date is not None})
    if len(all_years) < MIN_YEARS_FOR_TREND:
        return []

    cat_year_counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    cat_year_entry_ids: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for e in entries:
        if e.date is None:
            continue
        for cat in match_categories(e.opmerkingen):
            cat_year_counts[cat][e.date.year] += 1
            cat_year_entry_ids[cat][e.date.year].append(e.id)

    patterns = []
    for cat, year_counts in cat_year_counts.items():
        total = sum(year_counts.values())
        if total < MIN_YEARS_FOR_TREND:  # too few occurrences overall to say anything
            continue
        counts = [year_counts.get(y, 0) for y in all_years]
        slope, intercept = _linear_trend([float(y) for y in all_years], [float(c) for c in counts])
        mean_count = total / len(all_years)
        if mean_count <= 0:
            continue
        relative_change = abs(slope) * len(all_years) / mean_count
        spec = TARGET_CATEGORIES[cat]
        effect = min(1.0, relative_change)  # >=100% verandering over de hele periode = max effect
        confidence = min(1.0, total / 15.0)
        importance = spec["harvest_weight"] * effect * confidence
        direction = "toe" if slope > 0 else "af"
        patterns.append(Pattern(
            id=f"frequentie_{cat}",
            title=f"{spec['label']}: aantal behandelingen per jaar neemt {direction}",
            kind="frequentie",
            importance=importance,
            summary=(
                f"Het aantal keren dat '{spec['label'].lower()}' per jaar genoteerd staat neemt "
                f"gemiddeld {abs(slope):.2f} per jaar {direction} ({all_years[0]}-{all_years[-1]}, "
                f"{total} vermeldingen totaal). {spec['why']}"
            ),
            chart={"type": "bar_trend", "x": all_years, "y": counts,
                   "trend_y": [slope * y + intercept for y in all_years],
                   "y_axis_title": "Aantal behandelingen dat jaar"},
            entry_ids=[eid for y in all_years for eid in cat_year_entry_ids[cat].get(y, [])],
        ))
    return patterns


def detect_dosage_trend_patterns(entries: list[LogEntry]) -> list[Pattern]:
    """For each product (``middel``): average parsed dose per application, per year -- a rising
    trend is flagged (NOT diagnosed) as worth a closer look, since it can indicate declining
    product efficacy, but can equally mean a larger treated area/more trees; this module only
    surfaces the pattern, the teler/adviseur draws the conclusion."""
    # middel (lowercased) -> year -> list of (value, base_unit, entry_id)
    by_middel_year: dict[str, dict[int, list[tuple[float, str, int]]]] = defaultdict(lambda: defaultdict(list))
    display_name: dict[str, str] = {}
    for e in entries:
        if e.date is None:
            continue
        for middel, hoeveelheid in e.toepassingen:
            if not middel:
                continue
            key = middel.strip().lower()
            display_name.setdefault(key, middel.strip())
            parsed = parse_hoeveelheid(hoeveelheid)
            if parsed is None:
                continue
            value, unit = parsed
            by_middel_year[key][e.date.year].append((value, unit, e.id))

    patterns = []
    for key, year_map in by_middel_year.items():
        # Only compare years where the dose was recorded in the SAME base unit (ml or g) --
        # never average an ml-dose with a g-dose of the same product.
        unit_counts = Counter(u for vals in year_map.values() for _, u, _ in vals)
        if not unit_counts:
            continue
        base_unit = unit_counts.most_common(1)[0][0]
        year_avg: dict[int, float] = {}
        year_entry_ids: dict[int, list[int]] = defaultdict(list)
        for year, vals in year_map.items():
            same_unit = [(v, eid) for v, u, eid in vals if u == base_unit]
            if not same_unit:
                continue
            year_avg[year] = sum(v for v, _ in same_unit) / len(same_unit)
            year_entry_ids[year] = [eid for _, eid in same_unit]
        if len(year_avg) < MIN_YEARS_FOR_TREND:
            continue
        years = sorted(year_avg)
        doses = [year_avg[y] for y in years]
        slope, intercept = _linear_trend([float(y) for y in years], doses)
        mean_dose = sum(doses) / len(doses)
        if mean_dose <= 0:
            continue
        relative_change = abs(slope) * len(years) / mean_dose
        if relative_change < 0.15:  # <15% verandering over de hele periode -> ruis, geen patroon
            continue
        effect = min(1.0, relative_change)
        confidence = min(1.0, len(years) / 6.0)
        importance = 0.5 * effect * confidence  # geen harvest_weight per product -- neutrale 0.5
        direction = "toenemende" if slope > 0 else "afnemende"
        patterns.append(Pattern(
            id=f"dosering_{key}",
            title=f"{display_name[key]}: {direction} dosering per toepassing",
            kind="dosering",
            importance=importance,
            summary=(
                f"De gemiddelde dosering van '{display_name[key]}' per toepassing is "
                f"{'gestegen' if slope > 0 else 'gedaald'} van ~{doses[0]:.0f} naar ~{doses[-1]:.0f} "
                f"{base_unit} ({years[0]}-{years[-1]}). Een stijgende dosering kan duiden op "
                "afnemende effectiviteit (resistentie) -- maar kan ook een grotere behandelde "
                "oppervlakte betekenen; controleer de onderliggende regels."
            ),
            chart={"type": "line_trend", "x": years, "y": doses,
                   "trend_y": [slope * y + intercept for y in years],
                   "y_axis_title": f"Gem. dosering per toepassing ({base_unit})"},
            entry_ids=[eid for y in years for eid in year_entry_ids[y]],
        ))
    return patterns


def detect_monthly_calendar_pattern(entries: list[LogEntry]) -> Pattern | None:
    """Always-included reference pattern (not ranked as an "anomaly"): a month-by-month count of
    every category's mentions, aggregated over all years -- a practical empirical teeltkalender."""
    counts: dict[str, list[int]] = {cat: [0] * 12 for cat in TARGET_CATEGORIES}
    entry_ids: set[int] = set()
    any_data = False
    for e in entries:
        d = e.date
        if d is None:
            continue
        cats = match_categories(e.opmerkingen)
        if cats:
            entry_ids.add(e.id)
        for cat in cats:
            counts[cat][d.month - 1] += 1
            any_data = True
    if not any_data:
        return None
    # Only keep categories that occur at all, ordered by total mentions (most prominent first).
    active = sorted((cat for cat in counts if sum(counts[cat]) > 0), key=lambda c: -sum(counts[c]))
    return Pattern(
        id="kalender_overzicht",
        title="Teeltkalender: wanneer komt wat voor (alle jaren samen)",
        kind="kalender",
        importance=1.0,  # always pinned, not competing in the ranked list
        summary=(
            "Som van alle vermeldingen per categorie per kalendermaand, over alle beschikbare "
            "jaren -- een empirisch overzicht van wanneer in het seizoen welk onderwerp "
            "typisch aan de orde is."
        ),
        chart={
            "type": "heatmap",
            "x": list(range(1, 13)),
            "y": [TARGET_CATEGORIES[c]["label"] for c in active],
            "z": [counts[c] for c in active],
        },
        entry_ids=sorted(entry_ids),
    )


def detect_patterns(conn: sqlite3.Connection, top_n: int = 6) -> tuple[list[Pattern], Pattern | None]:
    """Runs every detector and returns (top-N ranked trend patterns, the pinned calendar
    pattern). The ranked list is sorted by `importance` descending -- this IS the "system
    itself recognizes the most eye-catching patterns" behaviour the UI surfaces."""
    entries = load_entries(conn)
    ranked = (
        detect_seasonal_timing_patterns(entries)
        + detect_frequency_trend_patterns(entries)
        + detect_dosage_trend_patterns(entries)
    )
    ranked.sort(key=lambda p: -p.importance)
    calendar = detect_monthly_calendar_pattern(entries)
    return ranked[:top_n], calendar
