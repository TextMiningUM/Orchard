"""Seizoenswaarschuwingen (design doc Sec A.6/B.4 vervolg, 2026-10-09): detecteert of HET
LOPENDE (of meest recente) seizoen tot nu toe statistisch afwijkt van voorgaande jaren --
anders dan ``pipeline/orchard_patterns.py`` (meerjaren-trends) en
``app/pages/5_Waarschuwingen.py`` (7-dagen-vooruitblik-drempels), kijkt dit terug: "is dit
seizoen tot nu toe te warm/te droog/te nat, is er een plaagexplosie gaande, en waren de
bestuivingscondities tijdens de bloei goed?" -- elk met een eigen, benoembare historische
vergelijkingsbasis in plaats van een vast getal.

Drie signaaltypes, elk met een PURE kern (testbaar met synthetische data, zie
``tests/test_orchard_season_watch.py``) + een dunne orchestratielaag die de echte
Open-Meteo/logboek-data erbij haalt:
  - weer      -- temperatuur/waterbalans (neerslag - ET0) dit seizoen-tot-nu-toe vs. dezelfde
                 kalenderperiode in de voorgaande ``lookback_years`` jaar.
  - logboek   -- cumulatief aantal vermeldingen per probleemcategorie dit seizoen-tot-nu-toe
                 (tot dezelfde dag-van-het-jaar) vs. voorgaande jaren -- een "explosie" is een
                 categorie die nu veel hoger ligt dan haar eigen historische patroon, ongeacht
                 WELKE categorie dat is (generaliseert "explosie kevers" naar elke in
                 ``pipeline.orchard_patterns.TARGET_CATEGORIES`` gedefinieerde categorie).
  - bestuiving -- vuistregel (zie docstring hieronder, GEEN literatuur-citaat) voor hoeveel
                 van de bloei-periode weersomstandigheden had die slecht zijn voor
                 bijenactiviteit.

Bodem-pH/zuurgraad wordt NIET gesignaleerd -- er is geen echte bodemdata-koppeling
(``pipeline.orchard_tools.get_soil_info`` is een expliciete NotImplementedError-stub, zie
design doc Sec C.4); ``soil_ph_status_note()`` hieronder zegt dat expliciet in de UI in
plaats van iets te verzinnen.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from pipeline.orchard_patterns import TARGET_CATEGORIES, LogEntry, match_categories
from pipeline.orchard_tools import DetailedDailyReading, get_weather_history_detailed, latest_available_archive_date

MIN_BASELINE_YEARS = 3  # fewer than this -> not enough history to call anything an anomaly


@dataclass
class SeasonSignal:
    id: str
    title: str
    severity: str  # "info" | "matig" | "hoog"
    summary: str
    source_citation: str
    chart: dict | None = None
    entry_ids: list[int] = field(default_factory=list)


def _zscore(value: float, baseline: list[float]) -> float:
    """Standard (value-mean)/std -- EXCEPT when the baseline has zero spread (every prior
    year had the exact same count/value), where a plain z-score would divide by zero and
    hide a real deviation. In that case a small heuristic floor stdev (10% of |mean|, or
    0.5 if mean is 0) is used instead, so "always exactly 1x before, now 6x" still produces
    a large, flaggable z-score rather than silently returning 0.0."""
    if len(baseline) < 2:
        return 0.0
    mean = statistics.mean(baseline)
    std = statistics.pstdev(baseline)
    if std == 0:
        if value == mean:
            return 0.0
        std = max(abs(mean) * 0.1, 0.5)
    return (value - mean) / std


def _severity_from_zscore(z: float) -> str:
    """Vuistregel (standaard statistische conventie, niet domein-specifiek gekalibreerd):
    |z|>=2.5 -> "hoog", |z|>=1.5 -> "matig", anders "info" (geen signaal)."""
    az = abs(z)
    if az >= 2.5:
        return "hoog"
    if az >= 1.5:
        return "matig"
    return "info"


# ── Weer: temperatuur + waterbalans dit seizoen-tot-nu-toe vs. voorgaande jaren ──────────────
def summarize_season_weather(rows: list[DetailedDailyReading]) -> dict | None:
    """Pure aggregatie: {"n_days", "avg_tmax", "total_precip_mm", "total_et0_mm",
    "water_balance_mm"} over `rows`. None als er geen bruikbare dagen in zitten."""
    usable = [r for r in rows if r.temp_max_c is not None]
    if not usable:
        return None
    total_precip = sum(r.precipitation_mm for r in usable)
    et0_vals = [r.et0_evapotranspiration_mm for r in usable if r.et0_evapotranspiration_mm is not None]
    total_et0 = sum(et0_vals) if et0_vals else None
    return {
        "n_days": len(usable),
        "avg_tmax": sum(r.temp_max_c for r in usable) / len(usable),
        "total_precip_mm": total_precip,
        "total_et0_mm": total_et0,
        "water_balance_mm": (total_precip - total_et0) if total_et0 is not None else None,
    }


def detect_weather_anomalies(
    current: dict, baseline: list[dict], period_label: str, source_citation: str,
) -> list[SeasonSignal]:
    """Pure comparison: `current` and each item of `baseline` are `summarize_season_weather()`
    outputs for the SAME calendar window length (season-start..as-of-day), just different
    years. Returns 0-2 signals (temperature, water balance)."""
    if current is None or len(baseline) < MIN_BASELINE_YEARS:
        return []
    signals = []

    tmax_baseline = [b["avg_tmax"] for b in baseline if b is not None]
    z_tmax = _zscore(current["avg_tmax"], tmax_baseline)
    sev = _severity_from_zscore(z_tmax)
    if sev != "info":
        richting = "warmer" if z_tmax > 0 else "kouder"
        signals.append(SeasonSignal(
            id="weer_temperatuur", title=f"{period_label}: {richting} dan normaal",
            severity=sev, source_citation=source_citation,
            summary=(
                f"Gemiddelde dagmax is {current['avg_tmax']:.1f}°C, tegenover een historisch "
                f"gemiddelde van {statistics.mean(tmax_baseline):.1f}°C over dezelfde periode in "
                f"de {len(tmax_baseline)} voorgaande jaren (afwijking z={z_tmax:+.1f})."
            ),
        ))

    wb_baseline = [b["water_balance_mm"] for b in baseline if b is not None and b["water_balance_mm"] is not None]
    if current.get("water_balance_mm") is not None and len(wb_baseline) >= MIN_BASELINE_YEARS:
        z_wb = _zscore(current["water_balance_mm"], wb_baseline)
        sev = _severity_from_zscore(z_wb)
        if sev != "info":
            if z_wb < 0:
                titel, advies = "mogelijke droogtestress (watertekort)", "Overweeg extra beregening."
            else:
                titel, advies = "natter dan normaal (verhoogd schimmelrisico)", "Let extra op vruchtrot/bladziekten."
            signals.append(SeasonSignal(
                id="weer_waterbalans", title=f"{period_label}: {titel}",
                severity=sev, source_citation=source_citation,
                summary=(
                    f"Neerslag minus ET0-verdamping is {current['water_balance_mm']:.0f} mm, "
                    f"tegenover een historisch gemiddelde van {statistics.mean(wb_baseline):.0f} mm "
                    f"over dezelfde periode in de {len(wb_baseline)} voorgaande jaren "
                    f"(afwijking z={z_wb:+.1f}). {advies}"
                ),
            ))
    return signals


def compute_weather_season_watch(
    lat: float, lon: float, target_year: int, as_of: date | None = None,
    season_start_month: int = 3, season_start_day: int = 1, lookback_years: int = 6,
) -> list[SeasonSignal]:
    """Orchestration: fetches real weather for `target_year`'s season-to-date and the same
    calendar window in each of the `lookback_years` preceding years, then calls the pure
    detector above. Returns [] if the season hasn't started yet or there isn't enough
    history (never raises on a quiet/empty result -- same "always return something usable"
    posture as the rest of this project's live-data call sites)."""
    season_start = date(target_year, season_start_month, season_start_day)
    as_of = as_of or latest_available_archive_date()
    if as_of.year != target_year:
        as_of = date(target_year, 11, 1)  # a past, fully-logged year -- compare its whole season
    else:
        as_of = min(as_of, latest_available_archive_date())
    if as_of <= season_start:
        return []
    n_days = (as_of - season_start).days

    current_rows, citation = get_weather_history_detailed(lat, lon, season_start.isoformat(), as_of.isoformat())
    current_summary = summarize_season_weather(current_rows)

    baseline_summaries = []
    for y in range(target_year - lookback_years, target_year):
        b_start = date(y, season_start_month, season_start_day)
        b_end = b_start + timedelta(days=n_days)
        rows, _ = get_weather_history_detailed(lat, lon, b_start.isoformat(), b_end.isoformat())
        baseline_summaries.append(summarize_season_weather(rows))

    period_label = f"Seizoen {target_year} ({season_start.isoformat()}..{as_of.isoformat()})"
    return detect_weather_anomalies(current_summary, baseline_summaries, period_label, citation)


# ── Logboek: cumulatieve plaag-/ziektedruk dit seizoen vs. voorgaande jaren ──────────────────
def cumulative_counts_by_year(entries: list[LogEntry], category: str, cutoff_doy: int) -> dict[int, int]:
    """Pure: {jaar: cumulatief_aantal_vermeldingen_tot_en_met_dag-van-het-jaar `cutoff_doy`}
    voor `category`, over alle jaren waar `entries` data voor heeft."""
    counts: dict[int, int] = {}
    for e in entries:
        d = e.date
        if d is None or d.timetuple().tm_yday > cutoff_doy:
            continue
        if category in match_categories(e.opmerkingen):
            counts[d.year] = counts.get(d.year, 0) + 1
    return counts


def detect_logbook_season_spikes(
    entries: list[LogEntry], target_year: int, as_of_doy: int | None = None,
) -> list[SeasonSignal]:
    """Pure (no network): compares, for every TARGET_CATEGORIES key, the cumulative
    mentions-to-date in `target_year` against the same cumulative count (same cutoff
    day-of-year) in every OTHER year present in `entries` -- flags a category whose
    current-season count is a statistical outlier vs. its own history. Works for any
    category already defined (generalises e.g. "explosie kevers" to whichever pest/disease
    is actually spiking)."""
    if as_of_doy is None:
        target_dates = [e.date for e in entries if e.date is not None and e.date.year == target_year]
        if not target_dates:
            return []
        as_of_doy = max(d.timetuple().tm_yday for d in target_dates)

    signals = []
    for cat, spec in TARGET_CATEGORIES.items():
        counts = cumulative_counts_by_year(entries, cat, as_of_doy)
        current = counts.get(target_year, 0)
        baseline = [c for y, c in counts.items() if y != target_year]
        if len(baseline) < MIN_BASELINE_YEARS:
            continue
        z = _zscore(float(current), [float(b) for b in baseline])
        sev = _severity_from_zscore(z)
        if sev == "info" or z <= 0:  # alleen een PIEK (niet "minder dan normaal") is hier interessant
            continue
        matching_ids = [
            e.id for e in entries
            if e.date is not None and e.date.year == target_year and e.date.timetuple().tm_yday <= as_of_doy
            and cat in match_categories(e.opmerkingen)
        ]
        signals.append(SeasonSignal(
            id=f"logboek_piek_{cat}", title=f"{spec['label']}: ongewoon hoog aantal meldingen dit seizoen",
            severity=sev, source_citation="Eigen logboek (Data/Orchard/OrchardLogbooks/orchard_logbook.db)",
            summary=(
                f"{current}x '{spec['label'].lower()}' genoteerd in {target_year} tot dag "
                f"{as_of_doy} van het jaar, tegenover gemiddeld {statistics.mean(baseline):.1f}x "
                f"in de {len(baseline)} andere jaren met data tot hetzelfde punt in het seizoen "
                f"(afwijking z={z:+.1f}). {spec['why']}"
            ),
            entry_ids=matching_ids,
        ))
    signals.sort(key=lambda s: ({"hoog": 2, "matig": 1}.get(s.severity, 0)), reverse=True)
    return signals


# ── Bestuiving: weer tijdens de bloei vs. een vuistregel voor bijenactiviteit ────────────────
# VUISTREGEL (geen letterlijk literatuurcitaat -- algemeen bekend uit bijenteelt-praktijk):
# honingbijen vliegen nauwelijks uit onder ~12-13 graden, bij neerslag, of bij harde wind
# (>~25 km/u). Dit is bewust ruim/illustratief; vervang door een echte bron zodra die
# gevonden is (zelfde "illustrative vs real, cited" discipline als
# pipeline/orchard_phenology_spec.py).
_BEE_MIN_TEMP_C = 13.0
_BEE_MAX_WIND_KMH = 25.0
_BEE_MAX_RAIN_MM = 0.5


def classify_bee_flight_day(tmax_c: float | None, precip_mm: float, wind_kmh: float | None) -> bool:
    """True = goede bestuivingsdag (vuistregel hierboven), False = slechte dag."""
    if tmax_c is None or tmax_c < _BEE_MIN_TEMP_C:
        return False
    if precip_mm > _BEE_MAX_RAIN_MM:
        return False
    if wind_kmh is not None and wind_kmh > _BEE_MAX_WIND_KMH:
        return False
    return True


def summarize_bloom_conditions(rows: list[DetailedDailyReading]) -> dict | None:
    if not rows:
        return None
    goede_dagen = sum(1 for r in rows if classify_bee_flight_day(r.temp_max_c, r.precipitation_mm, r.wind_speed_max_kmh))
    return {"n_days": len(rows), "n_goede_dagen": goede_dagen, "slechte_fractie": 1 - goede_dagen / len(rows)}


def detect_pollination_weather_risk(summary: dict | None, period_label: str, source_citation: str) -> SeasonSignal | None:
    """Pure: flags when a large share of the bloom window had poor bee-flight weather."""
    if summary is None or summary["n_days"] < 5:
        return None
    frac = summary["slechte_fractie"]
    if frac >= 0.6:
        sev = "hoog"
    elif frac >= 0.4:
        sev = "matig"
    else:
        return None
    return SeasonSignal(
        id="bestuiving_weer", title=f"{period_label}: mogelijk verminderde bestuiving door het weer",
        severity=sev, source_citation=source_citation,
        summary=(
            f"{summary['n_goede_dagen']}/{summary['n_days']} dagen in het bloeivenster had "
            f"redelijke bijenvlieg-omstandigheden (vuistregel: >={_BEE_MIN_TEMP_C:.0f}°C, "
            f"droog, wind <{_BEE_MAX_WIND_KMH:.0f} km/u) -- {frac*100:.0f}% van de dagen was "
            "ongunstig. Minder bijenactiviteit tijdens de bloei kan direct de vruchtzetting "
            "en dus de opbrengst raken."
        ),
    )


def compute_pollination_season_watch(
    lat: float, lon: float, entries: list[LogEntry], target_year: int,
    fallback_month_range: tuple[int, int] = (4, 1, 4, 30),
) -> SeasonSignal | None:
    """Orchestration: determines the bloom window from this year's own 'bestuiving'-category
    logbook entries if any exist, else falls back to `fallback_month_range` (default: all of
    April -- the empirical peak month from the teeltkalender, see Patroonherkenning)."""
    bloom_dates = [
        e.date for e in entries
        if e.date is not None and e.date.year == target_year and "bestuiving" in match_categories(e.opmerkingen)
    ]
    if bloom_dates:
        start, end = min(bloom_dates), max(bloom_dates)
        if start == end:
            start, end = start - timedelta(days=7), end + timedelta(days=7)
    else:
        sm, sd, em, ed = fallback_month_range
        start, end = date(target_year, sm, sd), date(target_year, em, ed)
    if end > date.today() and target_year == date.today().year:
        end = latest_available_archive_date()
    if end <= start:
        return None

    rows, citation = get_weather_history_detailed(lat, lon, start.isoformat(), end.isoformat())
    summary = summarize_bloom_conditions(rows)
    return detect_pollination_weather_risk(summary, f"Bloeivenster {start.isoformat()}..{end.isoformat()}", citation)


def soil_ph_status_note() -> SeasonSignal:
    """Altijd-getoonde, eerlijke placeholder -- geen bodem-pH-signaal wordt verzonnen."""
    return SeasonSignal(
        id="bodem_ph_stub", title="Bodem-pH / zuurgraad", severity="info", source_citation="",
        summary=(
            "Nog niet gekoppeld aan echte bodemdata (Bodemdata.nl/BOFEK, zie "
            "`pipeline.orchard_tools.get_soil_info()` en design doc Sec C.4) -- dit kan dus "
            "nog NIET automatisch gesignaleerd worden. Raadpleeg een eigen grondmonster "
            "totdat deze koppeling bestaat."
        ),
    )
