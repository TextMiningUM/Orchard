"""Weer-naar-ziekte vroegtijdige-waarschuwing (design doc Sec A.6/B.4 vervolg, 2026-10-09):
koppelt het echte weer in de dagen VOORAFGAAND aan elke historische behandeling tegen een
ziekte/plaag (zelfde categorieën als ``pipeline/orchard_patterns.py``) aan de behandeldatum
zelf -- en vergelijkt het WEER VAN DE LAATSTE DAGEN daarmee. Doel: niet pas signaleren zodra
de teler het al in het logboek heeft genoteerd (reactief, dat doet
``orchard_season_watch.detect_logbook_season_spikes``), maar ervoor -- "de omstandigheden nu
lijken op wat vroeger een uitbraak voorafging, overweeg nu al preventief in te grijpen".

Methode (een eenvoudige, expliciet-benoemde heuristiek, GEEN gekalibreerd voorspelmodel --
bij 487 logboekregels over 14 jaar is er simpelweg te weinig data per categorie voor meer dan
dit):
  1. Voor elke categorie: het EERSTE moment per jaar dat ertegen behandeld werd (zelfde
     "eerste-moment-per-jaar"-aanpak als ``orchard_patterns.detect_seasonal_timing_patterns``).
  2. Voor elk van die momenten: het weer in de ``lookback_days`` (standaard 10) dagen ERVOOR --
     gemiddelde dagmax, totale neerslag, aantal natte dagen.
  3. Een categorie heeft 1-2 "primaire aanjagers" (schimmel-/bacterieziekten: vocht; insecten:
     warmte -- algemeen bekende, niet per-se WUR-geciteerde plantenziektekunde/entomologie,
     zie ``PRIMARY_DRIVER_METRICS``). Alleen die aanjager-metrieken worden vergeleken.
  4. Signaal: als de afgelopen ``lookback_days`` dagen op ELKE aanjager-metriek minstens zo
     "erg" zijn als het historisch MINIMUM van alle eerdere keren dat die categorie kort
     daarna werd behandeld -- dus minstens zo nat/warm als de MINST extreme eerdere
     aanleiding -- wordt het gevlagd. Onderdrukt als de categorie dit jaar al behandeld is
     binnen `lookback_days` dagen (dan is er al op gereageerd).

Weer wordt per jaar ÉÉN keer opgehaald (heel seizoen) en daarna in Python gesneden naar elk
benodigde sub-venster -- niet één API-call per historische gebeurtenis (zou met ~10
categorieën x ~5-8 gebeurtenissen al snel 50-80 calls zijn).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from pipeline.orchard_patterns import TARGET_CATEGORIES, LogEntry, match_categories
from pipeline.orchard_tools import DetailedDailyReading, get_weather_history_detailed, latest_available_archive_date

# Schimmel-/bacterieziekten: vocht is de belangrijkste aanjager. Insecten (warmbloedige
# seizoenspieken): temperatuur. "bestuiving"/"voeding" bewust uitgesloten -- geen
# ziekte-/plaagdruksignaal.
PRIMARY_DRIVER_METRICS: dict[str, list[str]] = {
    "vruchtrot": ["total_precip_mm", "n_wet_days"],
    "bladvlekkenziekte": ["total_precip_mm", "n_wet_days"],
    "bladvalziekte": ["total_precip_mm", "n_wet_days"],
    "hagelschot": ["total_precip_mm", "n_wet_days"],
    "bacterie_kanker": ["total_precip_mm", "n_wet_days"],
    "fruitvliegen": ["avg_tmax"],
    "luis": ["avg_tmax"],
    "spint": ["avg_tmax"],
    "rupsen": ["avg_tmax"],
}
_QUALITATIEF_LABEL = {"total_precip_mm": "vochtig", "n_wet_days": "vochtig", "avg_tmax": "warm"}

LOOKBACK_DAYS_DEFAULT = 10
MIN_ONSET_EVENTS = 3  # minder dan dit -> te weinig historische gevallen voor een profiel


@dataclass
class DiseaseRiskSignal:
    id: str
    title: str
    severity: str  # "matig" | "hoog"
    summary: str
    source_citation: str
    entry_ids: list[int] = field(default_factory=list)


def summarize_window(rows: list[DetailedDailyReading]) -> dict | None:
    """Pure: {"n_days", "avg_tmax", "total_precip_mm", "n_wet_days"} over `rows`. None als
    er geen bruikbare dagen in zitten."""
    usable = [r for r in rows if r.temp_max_c is not None]
    if not usable:
        return None
    return {
        "n_days": len(usable),
        "avg_tmax": sum(r.temp_max_c for r in usable) / len(usable),
        "total_precip_mm": sum(r.precipitation_mm for r in usable),
        "n_wet_days": sum(1 for r in usable if r.precipitation_mm >= 1.0),
    }


def first_occurrence_dates(entries: list[LogEntry], category: str) -> list[tuple[int, date, int]]:
    """Pure: [(jaar, datum, entry_id), ...] -- het EERSTE moment per jaar dat `category`
    genoemd wordt, over alle jaren waar `entries` data voor heeft."""
    best: dict[int, tuple[date, int]] = {}
    for e in entries:
        d = e.date
        if d is None:
            continue
        if category in match_categories(e.opmerkingen):
            if d.year not in best or d < best[d.year][0]:
                best[d.year] = (d, e.id)
    return [(y, d, eid) for y, (d, eid) in sorted(best.items())]


def slice_window_before(
    daily_by_date: dict[str, DetailedDailyReading], end_date_exclusive: date, n_days: int,
) -> list[DetailedDailyReading]:
    """Pure: `n_days` dagen eindigend op de dag VOOR `end_date_exclusive`, uit een al
    opgehaalde {ISO-datum: reading}-lookup -- geen netwerk-call per gebeurtenis, de caller
    haalt één keer een heel seizoen op en hergebruikt dat voor elke gebeurtenis in dat jaar."""
    out = []
    for i in range(1, n_days + 1):
        key = (end_date_exclusive - timedelta(days=i)).isoformat()
        if key in daily_by_date:
            out.append(daily_by_date[key])
    return list(reversed(out))  # chronological order


def build_profile(window_summaries: list[dict], onset_doys: list[int]) -> dict | None:
    """Pure: {"n_events", "<metric>": {"mean","min","max"}, "onset_doy": {...}} -- None als
    er minder dan MIN_ONSET_EVENTS bruikbare samenvattingen zijn. `onset_doy` (dag-van-het-
    jaar van de behandeldatum zelf, NIET het weervenster ervoor) voedt de seizoensgrens in
    ``compare_current_to_profile()`` -- zonder die grens zou dit elke maand van het jaar
    kunnen afgaan, ook als de categorie historisch ALLEEN in het voorjaar voorkomt."""
    usable_idx = [i for i, s in enumerate(window_summaries) if s is not None]
    if len(usable_idx) < MIN_ONSET_EVENTS:
        return None
    profile: dict = {"n_events": len(usable_idx)}
    for metric in ("avg_tmax", "total_precip_mm", "n_wet_days"):
        vals = [window_summaries[i][metric] for i in usable_idx]
        profile[metric] = {"mean": statistics.mean(vals), "min": min(vals), "max": max(vals)}
    doys = [onset_doys[i] for i in usable_idx]
    profile["onset_doy"] = {"mean": statistics.mean(doys), "min": min(doys), "max": max(doys)}
    return profile


SEASONAL_MARGIN_DAYS = 21  # hoeveel ruimte rond het historische [min,max]-venster nog "relevant" telt


def compare_current_to_profile(
    category: str, current: dict | None, profile: dict | None, spec_label: str, spec_why: str,
    already_treated_recently: bool, source_citation: str, onset_entry_ids: list[int],
    lookback_days: int, current_doy: int | None = None,
) -> DiseaseRiskSignal | None:
    """Pure: vlagt wanneer (a) de huidige dag-van-het-jaar binnen het historisch relevante
    seizoensvenster voor `category` valt (± SEASONAL_MARGIN_DAYS) EN (b) ELKE aanjager-
    metriek minstens zo hoog is als het historische MINIMUM in het opgebouwde profiel --
    zonder (a) zou dit net zo makkelijk "vruchtrot-risico" in oktober melden, wat agronomisch
    onzin is (vruchtrot speelt hier historisch alleen rond mei-juni)."""
    if current is None or profile is None or already_treated_recently:
        return None
    if current_doy is not None:
        window = profile["onset_doy"]
        if not (window["min"] - SEASONAL_MARGIN_DAYS <= current_doy <= window["max"] + SEASONAL_MARGIN_DAYS):
            return None
    drivers = PRIMARY_DRIVER_METRICS.get(category)
    if not drivers:
        return None
    matches = []
    for metric in drivers:
        if current.get(metric) is None or current[metric] < profile[metric]["min"]:
            return None
        matches.append(f"{metric}={current[metric]:.1f} (hist. min {profile[metric]['min']:.1f}, gem. {profile[metric]['mean']:.1f})")
    kwalificaties = sorted({_QUALITATIEF_LABEL[m] for m in drivers})
    return DiseaseRiskSignal(
        id=f"weer_risico_{category}",
        title=f"{spec_label}: weer van de laatste {lookback_days} dagen lijkt op wat vroeger een uitbraak voorafging",
        severity="hoog" if len(matches) >= 2 else "matig",
        source_citation=source_citation,
        summary=(
            f"De laatste {lookback_days} dagen waren minstens zo {'/'.join(kwalificaties)} "
            f"({', '.join(matches)}) als ELK van de {profile['n_events']} eerdere keren dat "
            f"'{spec_label.lower()}' kort na vergelijkbaar weer werd behandeld, EN we zitten "
            "in het deel van het seizoen waarin dat historisch ook echt voorkomt. "
            f"{spec_why} Overweeg nu al te controleren of preventief in te grijpen, in "
            "plaats van te wachten tot de eerste symptomen zichtbaar zijn."
        ),
        entry_ids=onset_entry_ids,
    )


def compute_disease_weather_early_warnings(
    lat: float, lon: float, entries: list[LogEntry], as_of: date | None = None,
    lookback_days: int = LOOKBACK_DAYS_DEFAULT, season_start_month: int = 3, season_start_day: int = 1,
) -> list[DiseaseRiskSignal]:
    """Orchestration: haalt per benodigd jaar ÉÉN keer het hele-seizoen-weer op (hergebruikt
    voor elke historische gebeurtenis dat jaar + voor het huidige venster als `as_of` in dat
    jaar valt), bouwt per categorie een profiel, en vergelijkt dat met de laatste
    `lookback_days` dagen. Retourneert [] (nooit een crash) als er te weinig
    weer-/logboekdata is."""
    as_of = as_of or latest_available_archive_date()
    years_needed = {y for cat in PRIMARY_DRIVER_METRICS for y, _d, _eid in first_occurrence_dates(entries, cat)}
    years_needed.add(as_of.year)

    weather_by_year: dict[int, dict[str, DetailedDailyReading]] = {}
    for y in sorted(years_needed):
        start = date(y, season_start_month, season_start_day)
        end = date(y, 11, 1) if y != as_of.year else min(as_of, latest_available_archive_date())
        if end <= start:
            continue
        rows, _citation = get_weather_history_detailed(lat, lon, start.isoformat(), end.isoformat())
        weather_by_year[y] = {r.date: r for r in rows}

    current_window = slice_window_before(weather_by_year.get(as_of.year, {}), as_of + timedelta(days=1), lookback_days)
    current_summary = summarize_window(current_window)
    citation = (
        f"Open-Meteo Historical Weather API, laatste {lookback_days} dagen t/m {as_of.isoformat()}, "
        f"vergeleken met het weer voor {MIN_ONSET_EVENTS}+ eerdere behandelmomenten"
    )

    signals = []
    for cat in PRIMARY_DRIVER_METRICS:
        events = first_occurrence_dates(entries, cat)
        window_summaries, onset_entry_ids, onset_doys = [], [], []
        for y, d, eid in events:
            if y not in weather_by_year:
                continue
            s = summarize_window(slice_window_before(weather_by_year[y], d, lookback_days))
            if s is not None:
                window_summaries.append(s)
                onset_entry_ids.append(eid)
                onset_doys.append(d.timetuple().tm_yday)
        profile = build_profile(window_summaries, onset_doys)
        if profile is None:
            continue
        already_treated = any(
            e.date is not None and e.date.year == as_of.year and 0 <= (as_of - e.date).days <= lookback_days
            and cat in match_categories(e.opmerkingen)
            for e in entries
        )
        spec = TARGET_CATEGORIES[cat]
        signal = compare_current_to_profile(
            cat, current_summary, profile, spec["label"], spec["why"], already_treated,
            citation, onset_entry_ids, lookback_days, current_doy=as_of.timetuple().tm_yday,
        )
        if signal is not None:
            signals.append(signal)
    signals.sort(key=lambda s: ({"hoog": 2, "matig": 1}.get(s.severity, 0)), reverse=True)
    return signals
