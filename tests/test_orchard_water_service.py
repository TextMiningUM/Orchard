"""Tests of the water-balance service: history + forecast continuation and the advisor summary (no network)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from pipeline.orchard_water_service import advisor_summary, compute_water_state, outlook

TODAY = date(2026, 7, 10)


def _hist(rain=0.0, et0=5.0):
    def fetch(lat, lon, start, end):
        d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
        return [((d0 + timedelta(days=i)).isoformat(), rain, et0) for i in range((d1 - d0).days + 1)]
    return fetch


def _fc(rain=0.0, et0=5.0, offset=0):
    def fetch(lat, lon, days):
        return [((TODAY + timedelta(days=offset + i)).isoformat(), rain, et0) for i in range(days)]
    return fetch


def test_forecast_continues_from_the_end_state_of_the_past():
    s = compute_water_state(52.0, 5.0, history_fetch=_hist(), forecast_fetch=_fc(), today=TODAY, latest_archive=TODAY - timedelta(days=1))
    assert s.end == "2026-07-09" and s.forecast_from == "2026-07-10"
    assert len(s.forecast) == 7 and s.observed[-1].date == "2026-07-09"
    # a dry forecast must keep depleting the bucket from where the past ended
    assert s.forecast[0].soil_moisture_pct <= s.observed[-1].soil_moisture_pct
    assert s.forecast[-1].soil_moisture_pct < s.forecast[0].soil_moisture_pct


def test_forecast_days_already_in_the_archive_are_not_counted_twice():
    s = compute_water_state(52.0, 5.0, history_fetch=_hist(), forecast_fetch=_fc(offset=-2), today=TODAY, forecast_days=9)
    dates = [r.date for r in s.results]
    assert len(dates) == len(set(dates)) and s.forecast_from == "2026-07-10"


def test_a_failing_forecast_keeps_the_past_valid_and_reports_the_error():
    def boom(*a):
        raise ConnectionError("offline")
    s = compute_water_state(52.0, 5.0, history_fetch=_hist(), forecast_fetch=boom, today=TODAY)
    assert s.forecast == [] and s.forecast_from is None and "offline" in s.forecast_error and s.observed
    assert "niet beschikbaar" in advisor_summary(s)


def test_no_history_is_an_error_not_invented_data():
    with pytest.raises(ValueError):
        compute_water_state(52.0, 5.0, history_fetch=lambda *a: [], today=TODAY)


def test_outlook_flags_first_stress_day_and_first_wet_day():
    dry = compute_water_state(52.0, 5.0, history_fetch=_hist(rain=3.0, et0=3.0), forecast_fetch=_fc(rain=0.0, et0=7.0), today=TODAY)
    assert outlook(dry.forecast)["first_warn_date"] is not None or outlook(dry.forecast)["first_stress_date"] is not None
    wet = compute_water_state(52.0, 5.0, history_fetch=_hist(rain=3.0, et0=3.0), forecast_fetch=_fc(rain=40.0, et0=1.0), today=TODAY)
    o = outlook(wet.forecast)
    assert o["first_wet_date"] == "2026-07-10" and o["drainage_mm"] > 0
    assert outlook([]) == {}


def test_advisor_summary_contains_facts_caveat_and_forecast_lines():
    s = compute_water_state(52.0, 5.0, history_fetch=_hist(rain=1.0, et0=4.0), forecast_fetch=_fc(rain=0.0, et0=6.0), today=TODAY)
    text = advisor_summary(s)
    for needle in ("laatste 7 dagen", "laatste 30 dagen", "Bodemvocht nu", "Neerslagtekort sinds 1 april", "Verwachting komende 7 dagen",
                   "indicatief", "pessimistische"):
        assert needle in text
