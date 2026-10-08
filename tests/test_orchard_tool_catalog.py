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
            "vruchtbarsten_risico"} <= set(catalog)


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
