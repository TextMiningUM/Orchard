"""Unit tests for pipeline.orchard_disease_weather_links -- synthetic data only for the pure
functions (no live Open-Meteo calls); `compute_disease_weather_early_warnings` (orchestration)
is smoke-tested manually against the real API, same discipline as the rest of this project."""
from __future__ import annotations

from datetime import date

from pipeline.orchard_patterns import LogEntry
from pipeline.orchard_tools import DetailedDailyReading
from pipeline.orchard_disease_weather_links import (
    build_profile,
    compare_current_to_profile,
    first_occurrence_dates,
    slice_window_before,
    summarize_window,
)


def _reading(d, tmax=20.0, precip=0.0):
    return DetailedDailyReading(
        date=d, temp_min_c=tmax - 5, temp_max_c=tmax, precipitation_mm=precip,
        wind_speed_max_kmh=10.0, wind_direction_deg=180.0, wind_direction_compass="Z",
        sunshine_duration_h=6.0, et0_evapotranspiration_mm=3.0,
    )


def _entry(id_, year, month, day, opmerkingen):
    return LogEntry(id=id_, jaar=str(year), datum_iso=f"{year:04d}-{month:02d}-{day:02d}", opmerkingen=opmerkingen)


# ── summarize_window ───────────────────────────────────────────────────────────────────────
def test_summarize_window_basic():
    rows = [_reading(f"2024-05-0{i}", tmax=20.0, precip=2.0) for i in range(1, 4)]
    s = summarize_window(rows)
    assert s["n_days"] == 3
    assert s["avg_tmax"] == 20.0
    assert s["total_precip_mm"] == 6.0
    assert s["n_wet_days"] == 3


def test_summarize_window_wet_day_threshold():
    rows = [_reading("2024-05-01", precip=0.5), _reading("2024-05-02", precip=1.5)]
    s = summarize_window(rows)
    assert s["n_wet_days"] == 1  # only the >=1.0mm day counts


def test_summarize_window_empty_returns_none():
    assert summarize_window([]) is None


# ── first_occurrence_dates ──────────────────────────────────────────────────────────────────
def test_first_occurrence_dates_picks_earliest_per_year():
    entries = [
        _entry(1, 2020, 6, 10, "Tegen vruchtrot."),
        _entry(2, 2020, 5, 1, "Tegen vruchtrot."),  # earlier in the same year
        _entry(3, 2021, 5, 15, "Tegen vruchtrot."),
    ]
    result = first_occurrence_dates(entries, "vruchtrot")
    assert result == [(2020, date(2020, 5, 1), 2), (2021, date(2021, 5, 15), 3)]


def test_first_occurrence_dates_ignores_other_categories():
    entries = [_entry(1, 2020, 5, 1, "Tegen luis.")]
    assert first_occurrence_dates(entries, "vruchtrot") == []


# ── slice_window_before ──────────────────────────────────────────────────────────────────────
def test_slice_window_before_returns_chronological_order():
    daily = {f"2024-04-{d:02d}": _reading(f"2024-04-{d:02d}", tmax=float(d)) for d in range(20, 30)}
    window = slice_window_before(daily, date(2024, 4, 30), n_days=5)
    dates = [r.date for r in window]
    assert dates == ["2024-04-25", "2024-04-26", "2024-04-27", "2024-04-28", "2024-04-29"]


def test_slice_window_before_handles_missing_days():
    daily = {"2024-04-28": _reading("2024-04-28"), "2024-04-29": _reading("2024-04-29")}
    window = slice_window_before(daily, date(2024, 4, 30), n_days=5)
    assert len(window) == 2


# ── build_profile ────────────────────────────────────────────────────────────────────────────
def test_build_profile_requires_minimum_events():
    summaries = [{"avg_tmax": 20.0, "total_precip_mm": 10.0, "n_wet_days": 3}] * 2
    assert build_profile(summaries, onset_doys=[100, 110]) is None


def test_build_profile_computes_mean_min_max():
    summaries = [
        {"avg_tmax": 18.0, "total_precip_mm": 20.0, "n_wet_days": 4},
        {"avg_tmax": 22.0, "total_precip_mm": 30.0, "n_wet_days": 6},
        {"avg_tmax": 20.0, "total_precip_mm": 25.0, "n_wet_days": 5},
    ]
    profile = build_profile(summaries, onset_doys=[120, 130, 125])
    assert profile["n_events"] == 3
    assert profile["avg_tmax"] == {"mean": 20.0, "min": 18.0, "max": 22.0}
    assert profile["total_precip_mm"] == {"mean": 25.0, "min": 20.0, "max": 30.0}
    assert profile["onset_doy"] == {"mean": 125.0, "min": 120, "max": 130}


def test_build_profile_filters_none_entries():
    summaries = [None, {"avg_tmax": 18.0, "total_precip_mm": 20.0, "n_wet_days": 4}] * 2
    assert build_profile(summaries, onset_doys=[100, 110, 120, 130]) is None  # only 2 usable


# ── compare_current_to_profile ────────────────────────────────────────────────────────────────
_PROFILE_WET = {
    "n_events": 4,
    "total_precip_mm": {"mean": 25.0, "min": 18.0, "max": 35.0},
    "n_wet_days": {"mean": 5.0, "min": 3.0, "max": 7.0},
    "avg_tmax": {"mean": 18.0, "min": 15.0, "max": 21.0},
    "onset_doy": {"mean": 135.0, "min": 125, "max": 145},  # mid-May
}
_PROFILE_WARM = {
    "n_events": 4,
    "avg_tmax": {"mean": 24.0, "min": 21.0, "max": 27.0},
    "total_precip_mm": {"mean": 5.0, "min": 0.0, "max": 10.0},
    "n_wet_days": {"mean": 1.0, "min": 0.0, "max": 2.0},
    "onset_doy": {"mean": 145.0, "min": 140, "max": 150},  # late May
}


def test_compare_current_to_profile_flags_when_conditions_match_or_exceed():
    current = {"total_precip_mm": 40.0, "n_wet_days": 8, "avg_tmax": 17.0}
    signal = compare_current_to_profile(
        "vruchtrot", current, _PROFILE_WET, "Vruchtrot (Monilia)", "Rechtstreeks oogstverlies.",
        already_treated_recently=False, source_citation="bron", onset_entry_ids=[1, 2, 3], lookback_days=10,
    )
    assert signal is not None
    assert signal.severity == "hoog"  # both precip + wet-days drivers matched
    assert "Vruchtrot" in signal.title


def test_compare_current_to_profile_no_signal_when_below_historical_minimum():
    current = {"total_precip_mm": 5.0, "n_wet_days": 1, "avg_tmax": 17.0}
    signal = compare_current_to_profile(
        "vruchtrot", current, _PROFILE_WET, "Vruchtrot (Monilia)", "why",
        already_treated_recently=False, source_citation="bron", onset_entry_ids=[], lookback_days=10,
    )
    assert signal is None


def test_compare_current_to_profile_suppressed_when_already_treated():
    current = {"total_precip_mm": 40.0, "n_wet_days": 8, "avg_tmax": 17.0}
    signal = compare_current_to_profile(
        "vruchtrot", current, _PROFILE_WET, "Vruchtrot (Monilia)", "why",
        already_treated_recently=True, source_citation="bron", onset_entry_ids=[], lookback_days=10,
    )
    assert signal is None


def test_compare_current_to_profile_single_driver_category_gives_matig_severity():
    current = {"avg_tmax": 25.0, "total_precip_mm": 0.0, "n_wet_days": 0}
    signal = compare_current_to_profile(
        "fruitvliegen", current, _PROFILE_WARM, "Fruitvliegen", "why",
        already_treated_recently=False, source_citation="bron", onset_entry_ids=[], lookback_days=10,
    )
    assert signal is not None
    assert signal.severity == "matig"


def test_compare_current_to_profile_suppressed_outside_seasonal_window():
    # Regression test: matching weather OUTSIDE the historical onset window (here: day 300,
    # late October, vs. a profile whose onset window is doy 125-145) must NOT fire -- weather
    # similarity alone is not enough, it must also be the right time of year.
    current = {"total_precip_mm": 40.0, "n_wet_days": 8, "avg_tmax": 17.0}
    signal = compare_current_to_profile(
        "vruchtrot", current, _PROFILE_WET, "Vruchtrot (Monilia)", "why",
        already_treated_recently=False, source_citation="bron", onset_entry_ids=[], lookback_days=10,
        current_doy=300,
    )
    assert signal is None


def test_compare_current_to_profile_fires_inside_seasonal_window():
    current = {"total_precip_mm": 40.0, "n_wet_days": 8, "avg_tmax": 17.0}
    signal = compare_current_to_profile(
        "vruchtrot", current, _PROFILE_WET, "Vruchtrot (Monilia)", "why",
        already_treated_recently=False, source_citation="bron", onset_entry_ids=[], lookback_days=10,
        current_doy=135,
    )
    assert signal is not None


def test_compare_current_to_profile_none_when_no_profile_or_current():
    assert compare_current_to_profile("vruchtrot", None, _PROFILE_WET, "x", "y", False, "b", [], 10) is None
    assert compare_current_to_profile("vruchtrot", {"total_precip_mm": 40.0, "n_wet_days": 8, "avg_tmax": 17.0}, None, "x", "y", False, "b", [], 10) is None


def test_compare_current_to_profile_unknown_category_returns_none():
    assert compare_current_to_profile("voeding", {"avg_tmax": 20.0}, _PROFILE_WET, "x", "y", False, "b", [], 10) is None
