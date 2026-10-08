"""Deterministic phenology/risk core for the Cherry Orchard Advisor (Track 1 domain).

Mirrors the role ``chief_engineer_agent_spec.py`` plays in the Auto Pilot project: pure
stdlib, dependency-free dataclasses + deterministic functions that are the single source
of truth for "what is the orchard's current phenological/risk status", importable by BOTH
the Streamlit app (``app/pages/...``) and any future training-data generator, so the two
never drift out of sync -- see ``design_cherry_orchard_advisor.md`` Sec B.1/B.2.

Hard rule carried over from Chief Engineer/Captain (``design_cherry_orchard_advisor.md``
Sec B.1/B.11): the LLM is NEVER allowed to compute or guess these numbers itself -- it only
calls these functions as tools and explains/cites the result. Every threshold below carries
a ``source_citation`` and is explicitly labelled "illustrative, generic" vs "real, cited" --
never silently presented as more precise/variety-specific than it is (same discipline as
Chief Engineer's ``KNOWN_LIMITS`` registry).

Safe to run LOCALLY (pure stdlib, no GPU/API key, no model loading).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

RISK_ORDER: tuple[str, ...] = ("laag", "matig", "hoog", "kritiek")

PHENOLOGY_STAGES: tuple[str, ...] = (
    "rust",
    "knopzwelling",
    "bloei",
    "vruchtzetting",
    "groei",
    "rijping",
    "oogst",
    "nazorg",
)

# ── § 1  Hourly/daily reading types ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class TemperatureReading:
    """One hourly temperature observation/forecast point, e.g. from Open-Meteo."""
    timestamp: datetime
    temp_c: float


@dataclass(frozen=True)
class DailyReading:
    """One daily aggregate (used for GDD, where daily Tmin/Tmax is the usual input)."""
    date: str  # ISO date "YYYY-MM-DD"
    temp_min_c: float
    temp_max_c: float
    precipitation_mm: float = 0.0


# ── § 2  Chill-hours model (rest-break requirement) ─────────────────────────────────────
# Classic "Chilling Hours Model" (Weinberger 1950): count every hour with an air
# temperature between 0 degC and 7.2 degC (45 degF) during the dormant season (~Nov-Feb).
# Known, deliberate simplification (documented, not hidden): this ignores negative-chill
# hours above ~16 degC and the more detailed Utah/Dynamic (chill-portions) models some
# research uses -- picked as the walking-skeleton v0 model because it is what the Actua
# Steenfruit source material itself uses ("koude-uren") and is the simplest to validate
# against logbook seasons first (design_cherry_orchard_advisor.md Sec E, step 2).
_CHILL_HOURS_CITATION = (
    "Weinberger, J.H. (1950) classic 'Chilling Hours' model (0-7.2 degC window); "
    "variety thresholds (e.g. Kordia ~1400 chill hours) per StonefruitConsult 'Actua "
    "Steenfruit' nr. 6, 2026-03-06 (real, extracted). Illustrative for other varieties "
    "until their own thresholds are sourced -- see design doc Sec C.7 gap analysis."
)

# Known rasdrempels (koude-uren) -- alleen Kordia is een echt, geciteerd getal; andere
# rassen MOETEN nog uit WUR/Actua Steenfruit-archief gehaald worden (design doc Sec C.7).
KNOWN_CHILL_HOUR_REQUIREMENTS: dict[str, float] = {
    "Kordia": 1400.0,
}


def compute_chill_hours(readings: list[TemperatureReading]) -> float:
    """Total hours with ``0.0 <= temp_c <= 7.2`` across the given hourly series.

    Callers are responsible for only passing hourly readings from the dormant-season
    window (roughly 1 November - 28/29 February in the Netherlands) -- this function does
    not itself filter by calendar date, it just sums qualifying hours in whatever series
    it is given, so it can also be used incrementally (e.g. "chill hours so far this
    season").
    """
    return float(sum(1 for r in readings if 0.0 <= r.temp_c <= 7.2))


@dataclass(frozen=True)
class ChillHoursVerdict:
    variety: str
    accumulated_hours: float
    required_hours: float | None  # None if the variety's threshold isn't sourced yet
    fraction_complete: float | None
    source_citation: str


def evaluate_chill_hours(variety: str, accumulated_hours: float) -> ChillHoursVerdict:
    required = KNOWN_CHILL_HOUR_REQUIREMENTS.get(variety)
    fraction = (accumulated_hours / required) if required else None
    return ChillHoursVerdict(
        variety=variety,
        accumulated_hours=accumulated_hours,
        required_hours=required,
        fraction_complete=fraction,
        source_citation=_CHILL_HOURS_CITATION,
    )


# ── § 3  Growing Degree Days (GDD) ───────────────────────────────────────────────────────
# Standard GDD formula: GDD_day = max(0, (Tmax + Tmin) / 2 - base_temp), summed over days.
# base_temp = 4.4 degC (40 degF) is a commonly used generic base for sweet cherry in US
# extension literature -- explicitly illustrative/generic, NOT calibrated against this
# orchard's own varieties/logbooks yet (design doc Sec C.7).
_GDD_CITATION = (
    "Standard growing-degree-day formula, base_temp=4.4 degC (40 degF) -- generic sweet-"
    "cherry baseline from US extension/USA-NPN-style phenology literature. Illustrative, "
    "not yet calibrated against this orchard's own logbook seasons."
)

DEFAULT_GDD_BASE_TEMP_C = 4.4


def compute_gdd(daily_readings: list[DailyReading], base_temp_c: float = DEFAULT_GDD_BASE_TEMP_C) -> float:
    """Cumulative growing-degree-days across the given daily Tmin/Tmax series."""
    total = 0.0
    for d in daily_readings:
        avg = (d.temp_max_c + d.temp_min_c) / 2.0
        total += max(0.0, avg - base_temp_c)
    return total


@dataclass(frozen=True)
class GDDVerdict:
    accumulated_gdd: float
    base_temp_c: float
    source_citation: str


def evaluate_gdd(daily_readings: list[DailyReading], base_temp_c: float = DEFAULT_GDD_BASE_TEMP_C) -> GDDVerdict:
    return GDDVerdict(
        accumulated_gdd=compute_gdd(daily_readings, base_temp_c),
        base_temp_c=base_temp_c,
        source_citation=_GDD_CITATION,
    )


# ── § 4  Frost-risk during bloom/bud stages ─────────────────────────────────────────────
# Generic stone-fruit critical-temperature table (10% / 90% bud-kill thresholds), the kind
# commonly published by US agricultural extension services for frost-protection decisions.
# Illustrative/generic -- NOT variety- or site-calibrated for this orchard yet.
_FROST_CITATION = (
    "Generic stone-fruit critical-temperature (10%/90% bud-kill) frost table, the kind "
    "published by agricultural extension services for frost-protection timing. "
    "Illustrative/generic, not variety- or site-calibrated for this orchard."
)

# (stage, T_10pct_kill_degC, T_90pct_kill_degC) -- illustrative values, coarse per stage.
_FROST_TABLE: dict[str, tuple[float, float]] = {
    "knopzwelling": (-9.4, -17.8),
    "bloei": (-2.2, -6.7),
    "vruchtzetting": (-1.1, -4.4),
}


@dataclass(frozen=True)
class FrostRiskVerdict:
    stage: str
    forecast_min_temp_c: float
    risk: str  # one of RISK_ORDER
    note: str
    source_citation: str


def evaluate_frost_risk(stage: str, forecast_min_temp_c: float) -> FrostRiskVerdict:
    thresholds = _FROST_TABLE.get(stage)
    if thresholds is None:
        return FrostRiskVerdict(
            stage=stage, forecast_min_temp_c=forecast_min_temp_c, risk="laag",
            note=f"Geen frost-tabel voor fase '{stage}' (buiten knopzwelling/bloei/vruchtzetting).",
            source_citation=_FROST_CITATION,
        )
    t10, t90 = thresholds
    if forecast_min_temp_c <= t90:
        risk, note = "kritiek", f"Onder 90%-schadedrempel ({t90} degC) voor fase '{stage}'."
    elif forecast_min_temp_c <= t10:
        risk, note = "hoog", f"Onder 10%-schadedrempel ({t10} degC) voor fase '{stage}'."
    elif forecast_min_temp_c <= t10 + 2.0:
        risk, note = "matig", f"Binnen 2 degC van de 10%-schadedrempel ({t10} degC)."
    else:
        risk, note = "laag", "Ruim boven de schadedrempels voor deze fase."
    return FrostRiskVerdict(
        stage=stage, forecast_min_temp_c=forecast_min_temp_c, risk=risk, note=note,
        source_citation=_FROST_CITATION,
    )


# ── § 5  Drosophila suzukii (kersenvlieg) degree-day risk ───────────────────────────────
# Simplified, illustrative degree-day accumulator loosely inspired by the published
# description of the SIMKEF decision-support model (Germany, validated EU-wide; see
# design_cherry_orchard_advisor.md Sec C.3): reproduction favoured 18-30 degC, decline
# above 30 degC, winter mortality below 0 degC. This is explicitly NOT a reimplementation
# of SIMKEF's actual calibrated parameters (those are not published in reusable form) --
# it is a coarse illustrative stand-in until a properly sourced/calibrated model is built.
_SUZUKII_CITATION = (
    "Simplified, illustrative degree-day heuristic loosely based on the published "
    "description of the SIMKEF decision-support model (reproduction favoured 18-30 degC) -- "
    "design_cherry_orchard_advisor.md Sec C.3. NOT a reimplementation of SIMKEF's actual "
    "calibrated parameters; treat as a coarse, generic stand-in only."
)


@dataclass(frozen=True)
class SuzukiiRiskVerdict:
    favourable_hours: float  # hours within the reproduction-favourable band in the window given
    risk: str  # one of RISK_ORDER
    source_citation: str


def evaluate_suzukii_risk(readings: list[TemperatureReading]) -> SuzukiiRiskVerdict:
    favourable = sum(1 for r in readings if 18.0 <= r.temp_c <= 30.0)
    total = len(readings) or 1
    fraction = favourable / total
    if fraction >= 0.5:
        risk = "hoog"
    elif fraction >= 0.25:
        risk = "matig"
    else:
        risk = "laag"
    return SuzukiiRiskVerdict(favourable_hours=float(favourable), risk=risk, source_citation=_SUZUKII_CITATION)


# ── § 6  Rain-crack risk near harvest ────────────────────────────────────────────────────
# Generic heuristic: sweet cherries are well documented to be highly rain-crack-sensitive
# in the final ripening/harvest window; no single universal mm-threshold exists across
# varieties/rootstocks, so this is deliberately coarse (illustrative) pending this
# orchard's own calibration (design doc Sec C.7: harvest/yield records not yet collected).
_RAIN_CRACK_CITATION = (
    "Generic rain-crack-sensitivity heuristic for sweet cherry near harvest (well-"
    "documented phenomenon, no universal mm-threshold across varieties). Illustrative "
    "only -- needs calibration against this orchard's own harvest records (Sec C.7)."
)


@dataclass(frozen=True)
class RainCrackRiskVerdict:
    stage: str
    forecast_precip_mm_48h: float
    risk: str
    source_citation: str


def evaluate_rain_crack_risk(stage: str, forecast_precip_mm_48h: float) -> RainCrackRiskVerdict:
    if stage not in ("rijping", "oogst"):
        return RainCrackRiskVerdict(
            stage=stage, forecast_precip_mm_48h=forecast_precip_mm_48h, risk="laag",
            source_citation=_RAIN_CRACK_CITATION,
        )
    if forecast_precip_mm_48h >= 15.0:
        risk = "kritiek"
    elif forecast_precip_mm_48h >= 8.0:
        risk = "hoog"
    elif forecast_precip_mm_48h >= 3.0:
        risk = "matig"
    else:
        risk = "laag"
    return RainCrackRiskVerdict(
        stage=stage, forecast_precip_mm_48h=forecast_precip_mm_48h, risk=risk,
        source_citation=_RAIN_CRACK_CITATION,
    )
