"""Unit tests for pipeline.orchard_season_watch -- synthetic data only for the pure detector
functions (no live Open-Meteo calls in the automated suite); the orchestration functions
(`compute_weather_season_watch`, `compute_pollination_season_watch`) are smoke-tested
manually against the real API, same discipline as test_orchard_tools.py."""
from __future__ import annotations

from datetime import date

from pipeline.orchard_patterns import LogEntry
from pipeline.orchard_tools import DetailedDailyReading
from pipeline.orchard_season_watch import (
    _severity_from_zscore,
    _zscore,
    classify_bee_flight_day,
    cumulative_counts_by_year,
    detect_logbook_season_spikes,
    detect_pollination_weather_risk,
    detect_weather_anomalies,
    soil_ph_status_note,
    summarize_bloom_conditions,
    summarize_season_weather,
)


def _reading(d, tmax=20.0, tmin=10.0, precip=0.0, wind=10.0, et0=3.0):
    return DetailedDailyReading(
        date=d, temp_min_c=tmin, temp_max_c=tmax, precipitation_mm=precip,
        wind_speed_max_kmh=wind, wind_direction_deg=180.0, wind_direction_compass="Z",
        sunshine_duration_h=6.0, et0_evapotranspiration_mm=et0,
    )


def _entry(id_, year, month, day, opmerkingen):
    return LogEntry(id=id_, jaar=str(year), datum_iso=f"{year:04d}-{month:02d}-{day:02d}", opmerkingen=opmerkingen)


# ── _zscore / _severity_from_zscore ───────────────────────────────────────────────────────
def test_zscore_zero_with_insufficient_baseline():
    assert _zscore(100.0, [50.0]) == 0.0
    assert _zscore(100.0, []) == 0.0


def test_zscore_zero_when_no_spread_and_value_matches():
    assert _zscore(50.0, [50.0, 50.0, 50.0]) == 0.0


def test_zscore_large_when_no_spread_but_value_differs():
    # Regression test: a baseline with zero variance (e.g. "always exactly 1x before") must
    # not silently hide a real deviation (e.g. "6x now") behind a std=0 divide-by-zero guard.
    z = _zscore(6.0, [1.0, 1.0, 1.0, 1.0])
    assert z > 2.5


def test_zscore_positive_above_mean():
    z = _zscore(100.0, [50.0, 60.0, 40.0, 50.0])
    assert z > 0


def test_severity_thresholds():
    assert _severity_from_zscore(0.5) == "info"
    assert _severity_from_zscore(1.6) == "matig"
    assert _severity_from_zscore(-2.6) == "hoog"


# ── summarize_season_weather ───────────────────────────────────────────────────────────────
def test_summarize_season_weather_basic():
    rows = [_reading(f"2024-05-0{i}", tmax=20.0 + i, precip=2.0, et0=3.0) for i in range(1, 4)]
    summary = summarize_season_weather(rows)
    assert summary["n_days"] == 3
    assert summary["avg_tmax"] == 22.0
    assert summary["total_precip_mm"] == 6.0
    assert summary["total_et0_mm"] == 9.0
    assert summary["water_balance_mm"] == -3.0


def test_summarize_season_weather_empty_returns_none():
    assert summarize_season_weather([]) is None


def test_summarize_season_weather_handles_missing_et0():
    rows = [_reading("2024-05-01", et0=None)]
    summary = summarize_season_weather(rows)
    assert summary["total_et0_mm"] is None
    assert summary["water_balance_mm"] is None


# ── detect_weather_anomalies ───────────────────────────────────────────────────────────────
def test_detect_weather_anomalies_flags_warmer_than_normal():
    current = {"avg_tmax": 28.0, "water_balance_mm": -10.0}
    baseline = [{"avg_tmax": 20.0, "water_balance_mm": -8.0} for _ in range(5)]
    # baseline needs some spread, else zscore is 0 -- vary slightly
    baseline = [{"avg_tmax": v, "water_balance_mm": -8.0} for v in (18.0, 19.0, 20.0, 21.0, 22.0)]
    signals = detect_weather_anomalies(current, baseline, "Test-periode", "bron")
    assert any(s.id == "weer_temperatuur" and s.severity in ("matig", "hoog") for s in signals)


def test_detect_weather_anomalies_flags_drought_on_deficit():
    current = {"avg_tmax": 20.0, "water_balance_mm": -80.0}
    baseline = [{"avg_tmax": 20.0, "water_balance_mm": v} for v in (-10.0, -12.0, -8.0, -11.0, -9.0)]
    signals = detect_weather_anomalies(current, baseline, "Test-periode", "bron")
    wb_signal = next(s for s in signals if s.id == "weer_waterbalans")
    assert "droogtestress" in wb_signal.title


def test_detect_weather_anomalies_flags_wet_on_surplus():
    current = {"avg_tmax": 20.0, "water_balance_mm": 150.0}
    baseline = [{"avg_tmax": 20.0, "water_balance_mm": v} for v in (-10.0, -12.0, -8.0, -11.0, -9.0)]
    signals = detect_weather_anomalies(current, baseline, "Test-periode", "bron")
    wb_signal = next(s for s in signals if s.id == "weer_waterbalans")
    assert "natter" in wb_signal.title


def test_detect_weather_anomalies_no_signal_when_normal():
    current = {"avg_tmax": 20.0, "water_balance_mm": -10.0}
    baseline = [{"avg_tmax": v, "water_balance_mm": -10.0} for v in (19.0, 20.0, 21.0, 20.5, 19.5)]
    assert detect_weather_anomalies(current, baseline, "Test-periode", "bron") == []


def test_detect_weather_anomalies_requires_minimum_baseline_years():
    current = {"avg_tmax": 30.0, "water_balance_mm": -50.0}
    baseline = [{"avg_tmax": 20.0, "water_balance_mm": -10.0}]
    assert detect_weather_anomalies(current, baseline, "Test-periode", "bron") == []


def test_detect_weather_anomalies_handles_none_current():
    assert detect_weather_anomalies(None, [{"avg_tmax": 20.0, "water_balance_mm": -10.0}] * 4, "x", "bron") == []


# ── cumulative_counts_by_year / detect_logbook_season_spikes ─────────────────────────────
def test_cumulative_counts_by_year_respects_cutoff_doy():
    entries = [
        _entry(1, 2022, 5, 1, "Tegen luis."),   # doy ~121
        _entry(2, 2022, 7, 1, "Tegen luis."),   # doy ~182, after cutoff
        _entry(3, 2023, 5, 2, "Tegen luis."),
    ]
    counts = cumulative_counts_by_year(entries, "luis", cutoff_doy=150)
    assert counts == {2022: 1, 2023: 1}


def test_detect_logbook_season_spikes_flags_unusual_spike():
    entries = []
    eid = 1
    # Baseline years: 1 mention of luis each, early in the season.
    for year in (2019, 2020, 2021, 2022):
        entries.append(_entry(eid, year, 5, 1, "Tegen luis."))
        eid += 1
    # Target year 2023: 6 mentions -> a clear spike vs. baseline of 1 each.
    target_ids = []
    for day in range(1, 7):
        entries.append(_entry(eid, 2023, 5, day, "Tegen luis."))
        target_ids.append(eid)
        eid += 1
    signals = detect_logbook_season_spikes(entries, target_year=2023, as_of_doy=200)
    spike = next(s for s in signals if s.id == "logboek_piek_luis")
    assert set(spike.entry_ids) == set(target_ids)


def test_detect_logbook_season_spikes_no_signal_when_consistent():
    entries = []
    eid = 1
    for year in (2019, 2020, 2021, 2022, 2023):
        entries.append(_entry(eid, year, 5, 1, "Tegen luis."))
        eid += 1
    signals = detect_logbook_season_spikes(entries, target_year=2023, as_of_doy=200)
    assert not any(s.id == "logboek_piek_luis" for s in signals)


def test_detect_logbook_season_spikes_empty_when_no_target_year_data():
    entries = [_entry(1, 2020, 5, 1, "Tegen luis.")]
    assert detect_logbook_season_spikes(entries, target_year=2030) == []


# ── bestuiving/bijen ───────────────────────────────────────────────────────────────────────
def test_classify_bee_flight_day_good_conditions():
    assert classify_bee_flight_day(18.0, 0.0, 10.0) is True


def test_classify_bee_flight_day_too_cold():
    assert classify_bee_flight_day(8.0, 0.0, 10.0) is False


def test_classify_bee_flight_day_rain():
    assert classify_bee_flight_day(18.0, 2.0, 10.0) is False


def test_classify_bee_flight_day_too_windy():
    assert classify_bee_flight_day(18.0, 0.0, 40.0) is False


def test_summarize_bloom_conditions_and_risk_detection():
    rows = [_reading(f"2024-04-{d:02d}", tmax=9.0, precip=3.0) for d in range(1, 11)]  # all bad days
    summary = summarize_bloom_conditions(rows)
    assert summary["n_goede_dagen"] == 0
    risk = detect_pollination_weather_risk(summary, "Bloei", "bron")
    assert risk is not None
    assert risk.severity == "hoog"


def test_detect_pollination_weather_risk_none_when_good_weather():
    rows = [_reading(f"2024-04-{d:02d}", tmax=18.0, precip=0.0, wind=10.0) for d in range(1, 11)]
    summary = summarize_bloom_conditions(rows)
    assert detect_pollination_weather_risk(summary, "Bloei", "bron") is None


def test_detect_pollination_weather_risk_none_for_short_window():
    rows = [_reading("2024-04-01", tmax=9.0, precip=3.0)]
    summary = summarize_bloom_conditions(rows)
    assert detect_pollination_weather_risk(summary, "Bloei", "bron") is None


# ── soil stub ──────────────────────────────────────────────────────────────────────────────
def test_soil_ph_status_note_is_honest_placeholder():
    note = soil_ph_status_note()
    assert note.severity == "info"
    assert "niet" in note.summary.lower()
