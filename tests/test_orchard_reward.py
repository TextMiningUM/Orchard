"""Reward function: every component and the compliance gate."""
from __future__ import annotations

from pipeline.orchard_reward import (RewardConfig, card_key_facts, conciseness, focus, is_complete, numeric_faithfulness,
                                     score_answer)

CONTEXT = "Drainage aanleggen op 30 cm diepte en op ruggen planten. Fragment 1."
GOOD = ("Leg drainage aan en plant op ruggen op 30 cm diepte.\n\nBronnen: Fragment 1.")


def test_card_key_facts_use_the_longest_content_word_stem_once():
    facts = card_key_facts(["drainage aanleggen of herstellen", "op ruggen planten", "grondwaterstand meten met peilbuizen",
                            "drainage herstellen"])
    assert facts[0] == ["herstel"] and ["planten"] in facts and ["grondwa"] in facts
    assert len([f for f in facts if f == ["herstel"]]) == 1


def test_perfect_answer_scores_one():
    s = score_answer(GOOD, key_facts=[["drainag"], ["ruggen"]], context=CONTEXT)
    assert s["gate"] == 1.0 and abs(s["reward"] - 1.0) < 1e-9


def test_missing_facts_lower_coverage_and_are_reported():
    s = score_answer(GOOD, key_facts=[["drainag"], ["peilbuis"]], context=CONTEXT)
    assert s["coverage"] == 0.5 and s["missing_facts"] == [["peilbuis"]] and 0 < s["reward"] < 1


def test_a_dose_or_authorisation_claim_zeroes_the_reward_whatever_else_is_good():
    dose = score_answer(GOOD + " Gebruik 5 liter per hectare.", key_facts=[["drainag"]], context=CONTEXT)
    claim = score_answer("Decis is niet toegelaten. Drainage.\n\nBronnen: Fragment 1.", key_facts=[["drainag"]], context=CONTEXT)
    hedge = score_answer("Ik kan niet zeggen of Decis is toegelaten. Drainage.\n\nBronnen: Fragment 1.", key_facts=[["drainag"]], context=CONTEXT)
    assert dose["reward"] == 0 and dose["violations"] == ["DOSE"]
    assert claim["reward"] == 0 and claim["violations"] == ["CLAIM"]
    assert hedge["gate"] == 1.0 and hedge["reward"] > 0


def test_invented_numbers_are_penalised_but_references_and_list_numbers_are_not():
    assert numeric_faithfulness("Plant op 30 cm. Zie Fragment 2 en kaart 7.\n1. stap", CONTEXT) == 1.0
    assert numeric_faithfulness("Plant op 45 cm diepte.", CONTEXT) == 0.0
    assert numeric_faithfulness("Plant op 30 cm en 45 cm.", CONTEXT) == 0.5
    assert numeric_faithfulness("Geen getallen hier.", CONTEXT) == 1.0
    assert numeric_faithfulness("0,5 liter", "0.5 liter") == 1.0


def test_truncated_answers_are_incomplete():
    assert not is_complete("De bladeren worden bruin omdat de")
    assert not is_complete("<think>nog bezig")
    assert not is_complete("Antwoord.\n\nBronnen: Fragment 1,")
    assert is_complete("Antwoord.\n\nBronnen: Fragment 1, Fragment 2")
    assert is_complete("Een volledige zin.")
    s = score_answer("De bladeren worden bruin omdat de", key_facts=[], context="")
    assert s["complete"] == 0.0 and s["grounding"] == 0.0


def test_conciseness_falls_linearly_between_the_limits():
    cfg = RewardConfig(concise_words=10, max_words=20)
    assert conciseness("woord " * 10, cfg) == 1.0 and conciseness("woord " * 15, cfg) == 0.5 and conciseness("woord " * 30, cfg) == 0.0


def test_weights_are_explicit_and_sum_to_one():
    c = RewardConfig()
    assert abs(c.w_coverage + c.w_focus + c.w_grounding + c.w_numeric + c.w_complete + c.w_concise - 1.0) < 1e-9


GOLD = "Drainage aanleggen en op ruggen planten tegen wortelrot door natte voeten."


def test_focus_penalises_content_from_other_fragments():
    on_topic = "Leg drainage aan en plant op ruggen tegen wortelrot.\n\nBronnen: Fragment 1."
    wandering = on_topic + " Houd bovendien greppels en bassinen aan voor erosiebestrijding."
    assert focus(on_topic, GOLD) == 1.0
    assert focus(wandering, GOLD) < 0.7
    assert focus("Plant op natte voeten.", GOLD, question="natte voeten") == 1.0   # the question's own words are allowed
    assert focus("Bronnen: Fragment 1", GOLD) == 1.0                                 # format words never count


def test_focus_enters_the_reward_only_when_gold_text_is_given_and_weights_renormalise():
    a = "Leg drainage aan en plant op ruggen tegen wortelrot.\n\nBronnen: Fragment 1."
    without = score_answer(a, key_facts=[["drainag"]], context=GOLD)
    with_gold = score_answer(a, key_facts=[["drainag"]], context=GOLD, gold_text=GOLD)
    assert "focus" not in without and with_gold["focus"] == 1.0 and abs(without["reward"] - 1.0) < 1e-9
    wander = score_answer(a + " Greppels en bassinen voor erosiebestrijding.", key_facts=[["drainag"]], context=GOLD, gold_text=GOLD)
    assert wander["reward"] < with_gold["reward"]
