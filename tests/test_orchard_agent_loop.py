"""Repetition-loop guard of the advisor."""
from __future__ import annotations

from pipeline.orchard_agent import collapse_repetition, has_repetition_loop

LOOP = "Die kennisbank geeft geen getal, dosering of middelnaam. " * 6


def test_loop_is_detected_only_at_three_or_more_repeats_of_a_long_sentence():
    assert has_repetition_loop(LOOP)
    assert not has_repetition_loop("Die kennisbank geeft geen getal. Die kennisbank geeft geen getal.")
    assert not has_repetition_loop("Ja. Ja. Ja. Ja. Ja.")            # short sentences never count
    assert not has_repetition_loop("")


def test_collapse_keeps_the_first_occurrence_and_drops_the_rest():
    text = "Eerst iets anders hier. " + LOOP + "Bronnen: Ctgb-databank."
    out = collapse_repetition(text)
    assert out.count("Die kennisbank geeft geen getal, dosering of middelnaam.") == 1
    assert out.startswith("Eerst iets anders hier.") and out.endswith("Bronnen: Ctgb-databank.")


def test_collapse_is_a_no_op_without_a_loop():
    text = "Normaal antwoord met twee zinnen. De tweede zin is anders.\n\nBronnen: Fragment 1."
    assert collapse_repetition(text) == text


def test_collapse_drops_a_trailing_unfinished_sentence_left_by_a_cut_off_loop():
    assert collapse_repetition(LOOP + "Die kennisbank geeft geen get") == "Die kennisbank geeft geen getal, dosering of middelnaam."


def test_collapse_never_adds_words():
    text = "Zin een is hier. " + LOOP
    assert set(collapse_repetition(text).split()) <= set(text.split())
