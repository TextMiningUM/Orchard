"""Unit tests for pipeline.orchard_tool_catalog -- uses fake ctx/snapshot objects so no live
network call happens in the automated suite (same discipline as test_orchard_tools.py)."""
from __future__ import annotations

from dataclasses import dataclass

from pipeline.orchard_tool_catalog import build_tool_catalog


@dataclass
class _FakeVerdict:
    risk: str
    source_citation: str
    note: str = ""
    required_hours: float = 1000.0
    accumulated_hours: float = 500.0
    fraction_complete: float = 0.5
    forecast_precip_mm_48h: float = 2.0


@dataclass
class _FakeCtx:
    lat: float = 52.0
    lon: float = 5.0
    variety: str = "Kordia"
    stage: str = "bloei"


def _fake_snapshot() -> dict:
    @dataclass
    class _FakeForecast:
        daily: list
        source_citation: str = "fake-forecast-bron"

    return {
        "forecast": _FakeForecast(daily=[]),
        "chill": _FakeVerdict(risk="laag", source_citation="fake-chill-bron"),
        "frost_by_day": [],
        "suzukii": _FakeVerdict(risk="laag", source_citation="fake-suzukii-bron"),
        "rain_crack": _FakeVerdict(risk="laag", source_citation="fake-rain-bron"),
    }


def test_build_tool_catalog_without_snapshot_only_has_kb_and_ctgb():
    catalog = build_tool_catalog(_FakeCtx(), snapshot=None, rag_index=None)
    assert set(catalog) == {"kennisbank_zoeken", "ctgb_toelating"}


def test_build_tool_catalog_with_snapshot_adds_weather_tools():
    catalog = build_tool_catalog(_FakeCtx(), snapshot=_fake_snapshot(), rag_index=None)
    assert {"weer_vooruitzicht", "koude_uren", "vorst_risico", "suzuki_risico",
            "vruchtbarsten_risico", "waterbalans"} <= set(catalog)


def test_waterbalans_tool_reports_deterministic_numbers_and_forecast(monkeypatch):
    from datetime import date, timedelta
    from types import SimpleNamespace
    from pipeline import orchard_tools

    def hist(lat, lon, start, end):
        d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
        return [SimpleNamespace(date=(d0 + timedelta(days=i)).isoformat(), precipitation_mm=0.0, et0_evapotranspiration_mm=5.0)
                for i in range((d1 - d0).days + 1)], "stub"

    def fc(lat, lon, days):
        d0 = date.today()
        return [((d0 + timedelta(days=i)).isoformat(), 0.0, 5.0) for i in range(days)]

    monkeypatch.setattr(orchard_tools, "get_weather_history_detailed", hist)
    monkeypatch.setattr(orchard_tools, "get_forecast_water_inputs", fc)
    result = build_tool_catalog(_FakeCtx(), snapshot=_fake_snapshot(), rag_index=None)["waterbalans"].fn(None)
    assert "laatste 7 dagen" in result.facts and "Verwachting komende 7 dagen" in result.facts
    assert "indicatief" in result.facts and result.sources


def test_waterbalans_tool_says_so_when_weather_is_unreachable(monkeypatch):
    from pipeline import orchard_tools

    def boom(*a, **k):
        raise ConnectionError("offline")
    monkeypatch.setattr(orchard_tools, "get_weather_history_detailed", boom)
    result = build_tool_catalog(_FakeCtx(), snapshot=_fake_snapshot(), rag_index=None)["waterbalans"].fn(None)
    assert "niet te berekenen" in result.facts and "Geef geen getallen" in result.facts


def test_ctgb_toelating_tool_always_returns_guardrail_text():
    catalog = build_tool_catalog(_FakeCtx(), snapshot=None, rag_index=None)
    result = catalog["ctgb_toelating"].fn("Decis")
    assert "GUARDRAIL" in result.facts
    assert "Decis" in result.facts


def test_kennisbank_zoeken_without_index_gives_clear_message():
    catalog = build_tool_catalog(_FakeCtx(), snapshot=None, rag_index=None)
    result = catalog["kennisbank_zoeken"].fn("suzuki-fruitvlieg")
    assert "nog niet gebouwd" in result.facts


def test_koude_uren_tool_uses_snapshot_fields():
    catalog = build_tool_catalog(_FakeCtx(), snapshot=_fake_snapshot(), rag_index=None)
    result = catalog["koude_uren"].fn(None)
    assert "500" in result.facts
    assert "1000" in result.facts
    assert result.sources == ["fake-chill-bron"]
