"""Evaluation harness: matching, guardrail patterns, repeated-run aggregation."""
from __future__ import annotations

from types import SimpleNamespace

from pipeline.orchard_eval import (aggregate_answer_runs, evaluate_answers, fact_coverage, first_hit_rank,
                                   forbidden_matches, format_aggregate, hit_matches_source, observation_card_items,
                                   retrieval_summary)


def test_hit_matches_card_number_and_document_sources():
    hit = {"doc_id": "bank", "section_titles": ["21. Nachtvorst"]}
    assert hit_matches_source(hit, "bank#21") and not hit_matches_source(hit, "bank#2")
    assert hit_matches_source(hit, "bank") and not hit_matches_source(hit, "other")
    assert first_hit_rank([{"doc_id": "x", "section_titles": []}, hit], ["bank#21"]) == 2


def test_retrieval_summary():
    s = retrieval_summary([1, 3, None], ks=(1, 3))
    assert s["hit@1"] == 1 / 3 and s["hit@3"] == 2 / 3 and abs(s["mrr"] - (1 + 1 / 3) / 3) < 1e-9


def test_fact_coverage_accepts_alternatives_and_ignores_accents():
    cov, missing = fact_coverage("Gebruik een windsingel en HACCP-hygi\u00ebne.", [["windscherm", "windsingel"], ["hygiene"], ["palen"]])
    assert cov == 2 / 3 and missing == [["palen"]]


def test_dose_presets_catch_doses_per_area_and_per_volume():
    assert forbidden_matches("Gebruik 5 liter per hectare.", ["DOSE"]) == ["DOSE"]
    assert forbidden_matches("Neem 250 ml per 100 liter water.", ["DOSE2"]) == ["DOSE2"]
    assert forbidden_matches("De boom is 3 meter hoog.", ["DOSE", "DOSE2"]) == []


def test_authorisation_claim_is_flagged_but_a_refusal_is_not():
    assert forbidden_matches("Decis is niet toegelaten in kersen.", ["CLAIM"])
    assert forbidden_matches("Dit middel is toegelaten voor kers.", ["CLAIM"])
    assert not forbidden_matches("Ik kan niet zeggen of Decis is toegelaten; controleer de Ctgb-databank.", ["CLAIM"])


def _resp(answer, grounding="green"):
    return SimpleNamespace(answer=answer, grounding=grounding, sources=["s"])


GUARD = {"id": "g", "category": "guardrail", "question": "q", "forbidden_patterns": ["DOSE", "CLAIM"],
         "must_mention": [["ctgb", "etiket"]]}
CONTENT = {"id": "c", "category": "kennisbank", "question": "q", "key_facts": [["alpha"], ["beta"]]}


def test_guardrail_requires_authority_mention_and_no_violation():
    ok = evaluate_answers([GUARD], lambda q: _resp("Raadpleeg het etiket."))["per_item"][0]
    assert ok["guardrail_pass"]
    bad = evaluate_answers([GUARD], lambda q: _resp("Gebruik 2 l/ha; zie etiket."))["per_item"][0]
    assert not bad["guardrail_pass"] and bad["violations"] == ["DOSE"]
    silent = evaluate_answers([GUARD], lambda q: _resp("Dat weet ik niet."))["per_item"][0]
    assert not silent["guardrail_pass"] and not silent["mentions_authority"]


def test_a_failing_question_is_recorded_not_fatal():
    def boom(q):
        raise ConnectionError("tunnel down")
    res = evaluate_answers([CONTENT], boom)
    assert res["summary"]["n_errors"] == 1


def test_aggregate_runs_reports_mean_sd_and_instability():
    def run(content_answer):
        return evaluate_answers([CONTENT, GUARD], lambda q: _resp(content_answer + " etiket"))

    runs = [run("alpha beta"), run("alpha"), run("alpha beta")]
    agg = aggregate_answer_runs(runs)
    assert agg["n_runs"] == 3
    assert abs(agg["mean_fact_coverage"]["mean"] - (1 + 0.5 + 1) / 3) < 1e-9 and agg["mean_fact_coverage"]["sd"] > 0
    assert agg["items_with_varying_coverage_pct"] == 1.0
    assert agg["guardrail_pass_pct"]["mean"] == 1.0 and agg["guardrail_failing_items"] == {}
    text = format_aggregate(agg, "x")
    assert "3 herhalingen" in text and "±" in text


def test_single_run_has_zero_sd():
    agg = aggregate_answer_runs([evaluate_answers([CONTENT], lambda q: _resp("alpha beta"))])
    assert agg["mean_fact_coverage"]["sd"] == 0.0


def test_observation_card_items_come_straight_from_the_cards():
    chunk = {"type": "probleem", "doc_id": "bank", "title": "2. Natte voeten", "section_titles": ["2. Natte voeten"],
             "text": "- Observatie: Plassen na regen.\n- Actie: Drainage."}
    items = observation_card_items([chunk, {"type": "prose", "text": "x", "doc_id": "b", "title": "t"}])
    assert items == [{"id": "obs2", "category": "kennisbank", "question": "Plassen na regen.", "sources": ["bank#2"]}]
