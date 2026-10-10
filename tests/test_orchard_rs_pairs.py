"""Rejection sampling: pair selection and summary (the model call is injected)."""
from __future__ import annotations

from pipeline.ingest.build_orchard_rs_pairs import choose_pair, process_prompt, split_think, summarise
from pipeline.orchard_reward import score_answer

CTX = "Drainage aanleggen en op ruggen planten."
FACTS = [["drainag"], ["ruggen"]]
GOOD = "Leg drainage aan en plant op ruggen.\n\nBronnen: Fragment 1."
SHORT = "Leg drainage aan."
LEAK = "Leg drainage aan, 5 liter per hectare. Ruggen.\n\nBronnen: Fragment 1."


def cand(answer, origin="sample"):
    return {"origin": origin, "answer": answer, "score": score_answer(answer, key_facts=FACTS, context=CTX)}


def test_split_think_removes_the_reasoning_and_rejects_unfinished_thinking():
    assert split_think("<think>hmm</think>Antwoord.") == "Antwoord."
    assert split_think("<think>nog bezig") == ""
    assert split_think("Gewoon.") == "Gewoon."


def test_chosen_is_best_clean_answer_and_rejected_the_worst_even_if_it_leaks():
    best, worst = choose_pair([cand(GOOD, "card"), cand(SHORT), cand(LEAK)], 0.15)
    assert best["answer"] == GOOD and worst["answer"] == LEAK


def test_a_leaking_answer_is_never_chosen():
    assert choose_pair([cand(LEAK), cand("")], 0.15) is None


def test_pairs_need_a_real_gap_and_different_text():
    assert choose_pair([cand(GOOD), cand(GOOD)], 0.15) is None
    almost = GOOD + " "
    assert choose_pair([cand(GOOD), cand(almost)], 0.15) is None


def test_ties_prefer_the_card_reference_as_chosen():
    best, _ = choose_pair([cand(GOOD, "sample"), cand(GOOD + "\n", "card"), cand(SHORT)], 0.15)
    assert best["origin"] == "card"


def test_process_prompt_scores_card_and_samples_and_survives_a_failing_sample():
    row = {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": CTX}, {"role": "assistant", "content": GOOD}],
           "meta": {"card_no": 1}}
    outputs = iter([SHORT, RuntimeError("boom"), "<think>x</think>" + LEAK])

    def sample_fn(messages):
        out = next(outputs)
        if isinstance(out, Exception):
            raise out
        return out

    res = process_prompt(row, FACTS, sample_fn, 3, 0.15)
    assert [c["origin"] for c in res["candidates"]] == ["card", "sample", "error:RuntimeError", "sample"]
    assert res["pair"][0]["origin"] == "card" and res["pair"][1]["answer"] in ("", LEAK, SHORT)
    s = summarise([res])
    assert s["prompts"] == 1 and s["samples"] == 2 and s["pairs"] == 1 and s["gate_violations"] == {"DOSE": 1}
    assert s["reference_means"]["reward"] > s["sample_means"]["reward"]
