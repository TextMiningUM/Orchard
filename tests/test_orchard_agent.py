"""Unit tests for pipeline.orchard_agent -- only the pure response-parsing helpers (no live
Qwen3-8B call in the automated suite; end-to-end ReACT behaviour is smoke-tested manually
against the real cloud inference server, see pipeline/orchard_agent.py's own docstring)."""
from __future__ import annotations

from pipeline.orchard_agent import _dedup, _extract_tool_call, _strip_think


def test_strip_think_extracts_reasoning_block():
    raw = "<think>Ik overweeg eerst het weer te checken.</think>Het antwoord is: ja."
    reasoning, remainder = _strip_think(raw)
    assert reasoning == "Ik overweeg eerst het weer te checken."
    assert remainder == "Het antwoord is: ja."


def test_strip_think_no_think_block():
    raw = "Gewoon een antwoord zonder redenering."
    reasoning, remainder = _strip_think(raw)
    assert reasoning == ""
    assert remainder == raw


def test_strip_think_unclosed_think_tag_returns_empty_remainder():
    # Regression test: generation cut off by max_new_tokens before </think> must never leak
    # raw, half-finished reasoning as if it were the final answer.
    raw = "<think>Ik ben nog aan het nadenken over"
    reasoning, remainder = _strip_think(raw)
    assert "nog aan het nadenken" in reasoning
    assert remainder == ""


def test_extract_tool_call_valid_json():
    remainder = '{"call_tool": "weer_vooruitzicht", "args": null}'
    call = _extract_tool_call(remainder)
    assert call == {"call_tool": "weer_vooruitzicht", "args": None}


def test_extract_tool_call_with_code_fence():
    remainder = '```json\n{"call_tool": "koude_uren", "args": null}\n```'
    call = _extract_tool_call(remainder)
    assert call is not None
    assert call["call_tool"] == "koude_uren"


def test_extract_tool_call_returns_none_for_plain_answer():
    remainder = "Er is geen verhoogd risico deze week."
    assert _extract_tool_call(remainder) is None


def test_extract_tool_call_returns_none_for_json_without_call_tool_key():
    remainder = '{"answer": "dit is geen tool-aanroep"}'
    assert _extract_tool_call(remainder) is None


def test_dedup_preserves_first_occurrence_order():
    assert _dedup(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]
