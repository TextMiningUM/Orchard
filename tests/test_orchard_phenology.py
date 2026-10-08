"""Unit tests for pipeline.orchard_phenology_spec -- pure stdlib, no network/GPU needed.

Run with: .venv\\Scripts\\python.exe -m pytest tests -v
"""
from __future__ import annotations

from datetime import datetime

from pipeline.orchard_phenology_spec import (
    DailyReading,
    TemperatureReading,
    compute_chill_hours,
    compute_gdd,
    evaluate_chill_hours,
    evaluate_frost_risk,
    evaluate_gdd,
    evaluate_rain_crack_risk,
    evaluate_suzukii_risk,
)


def _hourly(temps: list[float]) -> list[TemperatureReading]:
    return [TemperatureReading(timestamp=datetime(2026, 1, 1, h % 24), temp_c=t) for h, t in enumerate(temps)]


def test_compute_chill_hours_counts_only_the_0_to_7_2_window():
    readings = _hourly([-5.0, 0.0, 3.0, 7.2, 7.3, 10.0, 20.0])
    # qualifying: 0.0, 3.0, 7.2  -> 3 hours
    assert compute_chill_hours(readings) == 3.0


def test_compute_chill_hours_empty_series_is_zero():
    assert compute_chill_hours([]) == 0.0


def test_evaluate_chill_hours_known_variety_has_fraction():
    verdict = evaluate_chill_hours("Kordia", accumulated_hours=700.0)
    assert verdict.required_hours == 1400.0
    assert verdict.fraction_complete == 0.5


def test_evaluate_chill_hours_unknown_variety_has_no_fraction():
    verdict = evaluate_chill_hours("OnbekendRas", accumulated_hours=700.0)
    assert verdict.required_hours is None
    assert verdict.fraction_complete is None


def test_compute_gdd_sums_above_base_temp_only():
    daily = [
        DailyReading(date="2026-04-01", temp_min_c=0.0, temp_max_c=8.8),  # avg 4.4 -> 0 GDD at base 4.4
        DailyReading(date="2026-04-02", temp_min_c=10.0, temp_max_c=14.4),  # avg 12.2 -> 7.8 GDD
    ]
    gdd = compute_gdd(daily, base_temp_c=4.4)
    assert round(gdd, 1) == 7.8


def test_evaluate_gdd_wraps_citation():
    verdict = evaluate_gdd([DailyReading(date="2026-04-01", temp_min_c=10.0, temp_max_c=20.0)])
    assert verdict.accumulated_gdd > 0
    assert "GDD" not in verdict.source_citation  # citation is prose, sanity check it's non-empty
    assert verdict.source_citation


def test_frost_risk_critical_below_90pct_threshold_during_bloei():
    verdict = evaluate_frost_risk("bloei", forecast_min_temp_c=-8.0)
    assert verdict.risk == "kritiek"


def test_frost_risk_low_when_well_above_threshold():
    verdict = evaluate_frost_risk("bloei", forecast_min_temp_c=5.0)
    assert verdict.risk == "laag"


def test_frost_risk_unknown_stage_defaults_to_laag():
    verdict = evaluate_frost_risk("oogst", forecast_min_temp_c=-20.0)
    assert verdict.risk == "laag"


def test_suzukii_risk_high_when_mostly_in_favourable_band():
    readings = _hourly([20.0, 22.0, 25.0, 28.0])
    verdict = evaluate_suzukii_risk(readings)
    assert verdict.risk == "hoog"


def test_suzukii_risk_low_when_outside_favourable_band():
    readings = _hourly([-2.0, 0.0, 2.0, 5.0])
    verdict = evaluate_suzukii_risk(readings)
    assert verdict.risk == "laag"


def test_rain_crack_risk_only_applies_during_rijping_or_oogst():
    assert evaluate_rain_crack_risk("bloei", forecast_precip_mm_48h=50.0).risk == "laag"
    assert evaluate_rain_crack_risk("oogst", forecast_precip_mm_48h=50.0).risk == "kritiek"


def test_rain_crack_risk_thresholds_during_oogst():
    assert evaluate_rain_crack_risk("oogst", 1.0).risk == "laag"
    assert evaluate_rain_crack_risk("oogst", 5.0).risk == "matig"
    assert evaluate_rain_crack_risk("oogst", 10.0).risk == "hoog"
    assert evaluate_rain_crack_risk("oogst", 20.0).risk == "kritiek"
