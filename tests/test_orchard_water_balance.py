"""Soil-water balance: FAO-56 equations, mass balance, status labels, KNMI-style deficit."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from pipeline.orchard_water_balance import (DayInput, WaterBalanceConfig, STATUS_DRY, STATUS_DRY_WARN, STATUS_OK, STATUS_WET,
                                            crop_coefficient, cumulative_delta, knmi_deficit, period_summary, spinup_start,
                                            water_balance, window)


def days(start: str, rain: list[float], et0: list[float | None], irrigation: list[float] | None = None) -> list[DayInput]:
    d0 = date.fromisoformat(start)
    irr = irrigation or [0.0] * len(rain)
    return [DayInput((d0 + timedelta(days=i)).isoformat(), rain[i], et0[i], irr[i]) for i in range(len(rain))]


LEEM = WaterBalanceConfig(soil="leem", root_depth_m=1.0, ground_cover="kaal")  # TAW 155 mm, RAW 77.5 mm, Kc mid 0.90


# ── configuration / constants straight from FAO-56 ─────────────────────────────────────

def test_taw_and_raw_follow_fao_eq_82():
    assert LEEM.taw_mm == pytest.approx(155.0) and LEEM.raw_mm == pytest.approx(77.5)
    assert WaterBalanceConfig(soil="zand", root_depth_m=1.5).taw_mm == pytest.approx(120.0)


def test_kc_curve_uses_the_fao_stone_fruit_values_and_interpolates():
    assert crop_coefficient(date(2026, 2, 10), "kaal") == 0.45 and crop_coefficient(date(2026, 12, 20), "kaal") == 0.45
    assert crop_coefficient(date(2026, 7, 1), "kaal") == 0.90 and crop_coefficient(date(2026, 7, 1), "gras") == 1.15
    assert crop_coefficient(date(2026, 4, 1), "gras") == 0.50 and crop_coefficient(date(2026, 6, 1), "gras") == 1.15
    mid_may = crop_coefficient(date(2026, 5, 2), "kaal")
    assert 0.45 < mid_may < 0.90
    assert crop_coefficient(date(2026, 11, 1), "kaal") == pytest.approx(0.65)
    values = [crop_coefficient(date(2026, 1, 1) + timedelta(days=i), "gras") for i in range(365)]
    assert max(abs(a - b) for a, b in zip(values, values[1:])) < 0.05     # no jumps


# ── the bucket ─────────────────────────────────────────────────────────────────────────

def test_hand_calculated_day():
    # 10 July, Kc 0.90, ET0 5 -> ETc 4.5; rain 1 -> delta -3.5; start at field capacity -> Dr 3.5
    r = water_balance(days("2026-07-10", [1.0], [5.0]), LEEM)[0]
    assert r.kc == 0.90 and r.etc_mm == pytest.approx(4.5) and r.delta_mm == pytest.approx(-3.5)
    assert r.depletion_mm == pytest.approx(3.5) and r.drainage_mm == 0 and r.ks == 1.0
    assert r.soil_moisture_pct == pytest.approx(100 * (1 - 3.5 / 155))


def test_rain_on_a_full_bucket_drains_below_the_root_zone():
    r = water_balance(days("2026-07-10", [30.0], [4.0]), LEEM)[0]
    assert r.depletion_mm == 0 and r.drainage_mm == pytest.approx(30.0 - 0.9 * 4.0)
    assert r.delta_mm == pytest.approx(30.0 - 3.6)


def test_irrigation_counts_as_inflow_just_like_rain():
    dry = water_balance(days("2026-07-10", [0.0], [5.0], [0.0]), LEEM)[0]
    irrigated = water_balance(days("2026-07-10", [0.0], [5.0], [10.0]), LEEM)[0]
    assert irrigated.delta_mm == pytest.approx(dry.delta_mm + 10.0) and irrigated.drainage_mm == pytest.approx(5.5)


def test_mass_balance_is_exact_over_a_mixed_period():
    rain = [0, 0, 12, 0, 3, 0, 0, 25, 40, 0, 0, 1, 0, 0, 0] * 6
    et0 = [4.5, 5, 3, 4, 4.8, 5.2, 5, 2, 1, 4, 5, 5.5, 6, 5, 4] * 6
    irr = [0] * 90
    irr[20] = 15
    cfg = WaterBalanceConfig(soil="zandleem", root_depth_m=0.8, ground_cover="gras", start_depletion_mm=20.0)
    res = water_balance(days("2026-06-01", rain, et0, irr), cfg)
    inflow = sum(rain) + sum(irr)
    uptake = sum(r.etc_actual_mm for r in res)
    drained = sum(r.drainage_mm for r in res)
    assert inflow - uptake - drained == pytest.approx(20.0 - res[-1].depletion_mm, abs=1e-6)
    assert all(0 <= r.depletion_mm <= cfg.taw_mm + 1e-9 for r in res)


def test_a_drought_reduces_uptake_with_ks_and_flags_stress():
    res = water_balance(days("2026-07-01", [0.0] * 60, [6.0] * 60), LEEM)
    first_stress = next(r for r in res if r.ks < 1.0)
    assert first_stress.status == STATUS_DRY and first_stress.depletion_mm > LEEM.raw_mm
    assert first_stress.etc_actual_mm < first_stress.etc_mm
    assert res[-1].depletion_mm <= LEEM.taw_mm and res[-1].etc_actual_mm < 0.5 * res[-1].etc_mm   # nearly at wilting point
    assert any(r.status == STATUS_DRY_WARN for r in res[:res.index(first_stress)])


def test_wet_status_after_repeated_heavy_rain_and_recovery_to_ok():
    res = water_balance(days("2026-10-01", [30, 30, 0, 0, 0, 0], [1.0] * 6), LEEM)
    assert res[1].status == STATUS_WET and res[-1].status == STATUS_OK


def test_missing_et0_is_flagged_not_invented():
    res = water_balance(days("2026-07-01", [0.0, 2.0], [None, 4.0]), LEEM)
    assert res[0].et0_missing and res[0].etc_mm == 0 and not res[1].et0_missing
    assert period_summary(res)["et0_missing_days"] == 1


def test_start_state_is_clamped_to_the_physically_possible_range():
    res = water_balance(days("2026-07-01", [0.0], [0.0]), WaterBalanceConfig(start_depletion_mm=9999))
    assert res[0].depletion_mm == pytest.approx(WaterBalanceConfig().taw_mm)


def test_results_are_sorted_by_date_whatever_the_input_order():
    shuffled = list(reversed(days("2026-07-01", [0, 1, 2], [3, 3, 3])))
    assert [r.date for r in water_balance(shuffled, LEEM)] == ["2026-07-01", "2026-07-02", "2026-07-03"]


# ── period views ───────────────────────────────────────────────────────────────────────

def test_window_cumulative_delta_and_summary():
    res = water_balance(days("2026-07-01", [0, 10, 0, 2], [4, 4, 4, 4]), LEEM)
    shown = window(res, "2026-07-02", "2026-07-04")
    assert [r.date for r in shown] == ["2026-07-02", "2026-07-03", "2026-07-04"]
    cum = cumulative_delta(shown)
    assert cum[0] == shown[0].delta_mm and cum[-1] == pytest.approx(sum(r.delta_mm for r in shown))
    s = period_summary(shown)
    assert s["days"] == 3 and s["precipitation_mm"] == 12 and s["delta_mm"] == pytest.approx(12 - 3 * 3.6)


def test_knmi_deficit_resets_on_1_april_never_goes_below_zero_and_is_none_in_winter():
    d = days("2026-03-30", [0, 0, 0, 20, 0], [1, 1, 3, 2, 4])
    out = dict(knmi_deficit(d))
    assert out["2026-03-30"] is None and out["2026-03-31"] is None
    assert out["2026-04-01"] == 3 and out["2026-04-02"] == 0     # 3 + (2-20) is negative -> floored at 0
    assert out["2026-04-03"] == 4
    oct_ = dict(knmi_deficit(days("2026-09-29", [0, 0, 0], [3, 3, 3])))
    assert oct_["2026-09-30"] == 6 and oct_["2026-10-01"] is None


def test_spinup_starts_on_1_march_with_at_least_30_days_of_warmup():
    assert spinup_start(date(2026, 10, 9), 30) == date(2026, 3, 1)
    assert spinup_start(date(2026, 3, 20), 7) == date(2025, 3, 1)     # only 19 days since 1 March -> previous year
    assert spinup_start(date(2026, 1, 15), 30) == date(2025, 3, 1)
