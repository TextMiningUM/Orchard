"""Smoke / behaviour tests of the water-balance section (rendered with a stubbed weather source, no network)."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from streamlit.testing.v1 import AppTest  # noqa: E402

from pipeline import orchard_tools  # noqa: E402


def _stub(rain=lambda i: 0.0, et0=lambda i: 3.0):
    def get(lat, lon, start, end):
        d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
        rows = [SimpleNamespace(date=(d0 + timedelta(days=i)).isoformat(), precipitation_mm=rain(i), et0_evapotranspiration_mm=et0(i))
                for i in range((d1 - d0).days + 1)]
        return rows, "stub"
    return get


def _page():
    from waterbalance_view import render_waterbalance_section
    from datetime import date as _date
    render_waterbalance_section(52.0123, 5.4567, today=_date(2026, 10, 9))


@pytest.fixture(autouse=True)
def _fresh_cache():
    import streamlit as st
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def test_section_renders_metrics_two_charts_and_the_table(monkeypatch):
    monkeypatch.setattr(orchard_tools, "get_weather_history_detailed", _stub(rain=lambda i: 8.0 if i % 9 == 0 else 0.0))
    at = AppTest.from_function(_page, default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Waterbalans" in " ".join(s.value for s in at.subheader)
    labels = [m.label for m in at.metric]
    assert any(l.startswith("Neerslag (30 d)") for l in labels) and "Delta periode" in labels and "Bodemvocht nu" in labels
    assert "Neerslagtekort sinds 1 apr" in labels
    assert len(at.get("plotly_chart")) == 2 and len(at.dataframe) >= 1


def test_a_dry_spell_is_reported_as_a_deficit_and_stress(monkeypatch):
    monkeypatch.setattr(orchard_tools, "get_weather_history_detailed", _stub(rain=lambda i: 0.0, et0=lambda i: 6.0))
    at = AppTest.from_function(_page, default_timeout=60).run()
    metrics = {m.label: m for m in at.metric}
    assert metrics["Delta periode"].value.startswith("-") and metrics["Delta periode"].delta == "tekort"
    assert "te droog" in metrics["Bodemvocht nu"].delta


def test_a_wet_spell_drains_and_shows_a_surplus(monkeypatch):
    monkeypatch.setattr(orchard_tools, "get_weather_history_detailed", _stub(rain=lambda i: 15.0, et0=lambda i: 1.0))
    at = AppTest.from_function(_page, default_timeout=60).run()
    metrics = {m.label: m for m in at.metric}
    assert metrics["Delta periode"].delta == "overschot" and "nat" in metrics["Bodemvocht nu"].delta
    assert float(metrics["Afvoer naar diepere lagen"].value.split()[0]) > 100


def test_missing_et0_shows_a_warning(monkeypatch):
    monkeypatch.setattr(orchard_tools, "get_weather_history_detailed", _stub(et0=lambda i: None))
    at = AppTest.from_function(_page, default_timeout=60).run()
    assert any("ontbreekt de verdamping" in w.value for w in at.warning)


def test_a_weather_outage_is_shown_as_an_error_not_as_invented_data(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("geen verbinding")
    monkeypatch.setattr(orchard_tools, "get_weather_history_detailed", boom)
    at = AppTest.from_function(_page, default_timeout=60).run()
    assert any("Kon de weerdata voor de waterbalans niet ophalen" in e.value for e in at.error)
    assert not at.metric


def test_after_the_season_the_knmi_deficit_shows_the_end_of_season_value(monkeypatch):
    monkeypatch.setattr(orchard_tools, "get_weather_history_detailed", _stub(rain=lambda i: 0.0, et0=lambda i: 2.0))
    at = AppTest.from_function(_page, default_timeout=60).run()      # "today" is 9 Oct: outside 1 Apr - 30 Sep
    deficit = {m.label: m for m in at.metric}["Neerslagtekort sinds 1 apr"]
    assert deficit.value.endswith("mm") and deficit.delta == "eindstand 2026-09-30"


def test_changing_the_soil_changes_the_available_water(monkeypatch):
    monkeypatch.setattr(orchard_tools, "get_weather_history_detailed", _stub(rain=lambda i: 0.0, et0=lambda i: 4.0))
    at = AppTest.from_function(_page, default_timeout=60).run()
    sand_soil = at.selectbox(key="wb_soil").select("zand").run()
    caption = " ".join(c.value for c in sand_soil.caption)
    assert "TAW 80 mm" in caption
