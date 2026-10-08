"""Unit tests for pipeline.orchard_agent -- only the pure response-parsing helpers (no live
Qwen3-8B call in the automated suite; end-to-end ReACT behaviour is smoke-tested manually
against the real cloud inference server, see pipeline/orchard_agent.py's own docstring)."""
from __future__ import annotations

from pipeline.orchard_agent import (
    _dedup,
    _extract_tool_call,
    _strip_think,
    assess_grounding,
    build_history_messages,
)


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


# ── assess_grounding ───────────────────────────────────────────────────────────────────────
def test_assess_grounding_red_when_no_sources_or_tools():
    assert assess_grounding("Dat weet ik niet zeker.", [], []) == "red"


def test_assess_grounding_green_when_answer_cites_bronnen():
    answer = "Koude-uren zijn op schema.\n\nBronnen: WUR-publicatie X"
    assert assess_grounding(answer, ["WUR-publicatie X"], []) == "green"


def test_assess_grounding_green_when_answer_names_a_used_tool():
    answer = "Op basis van koude_uren is er geen risico."
    assert assess_grounding(answer, [], ["koude_uren"]) == "green"


def test_assess_grounding_red_when_sources_available_but_not_cited_in_text():
    # Regression guard: having sources available is NOT enough -- the answer text itself must
    # reference them, otherwise the model may have ignored its own context.
    answer = "Ik denk dat het wel goed komt."
    assert assess_grounding(answer, ["WUR-publicatie X"], []) == "red"


def test_assess_grounding_case_insensitive_bron_match():
    answer = "Zie BRON: iets"
    assert assess_grounding(answer, ["iets"], []) == "green"


# ── build_history_messages ───────────────────────────────────────────────────────────────────
def test_build_history_messages_preserves_order_and_roles():
    turns = [("user", "Is er vorstrisico?"), ("assistant", "Nee, geen risico.")]
    messages = build_history_messages(turns)
    assert messages == [
        {"role": "user", "content": "Is er vorstrisico?"},
        {"role": "assistant", "content": "Nee, geen risico."},
    ]


def test_build_history_messages_strips_disclaimer_from_assistant_turns():
    answer = (
        "Het antwoord is X.\n\n**Bronnen:**\n- WUR-publicatie\n\n"
        "*Let op: dit antwoord komt van het ongetrainde Qwen3-8B-basismodel ...*"
    )
    messages = build_history_messages([("assistant", answer)])
    assert messages[0]["content"] == "Het antwoord is X.\n\n**Bronnen:**\n- WUR-publicatie"
    assert "Let op" not in messages[0]["content"]


def test_build_history_messages_leaves_user_turns_untouched():
    messages = build_history_messages([("user", "Een vraag met *Let op: iets* erin.")])
    assert messages[0]["content"] == "Een vraag met *Let op: iets* erin."


def test_build_history_messages_empty_list():
    assert build_history_messages([]) == []
