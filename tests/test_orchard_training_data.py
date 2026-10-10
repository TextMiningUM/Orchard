"""Training-data extraction: the safeguards matter more than the volume."""
from __future__ import annotations

from pipeline.ingest.build_orchard_training_data import (LOGBOOK_SYSTEM_ADDENDUM, TRAIN_PRODUCTS, build_card_datasets,
                                                         build_compliance_dataset, build_logbook_dataset, compliance_extra,
                                                         gold_card_numbers, mentions_dose, pair_feedback, split_by_card)

SYS = "SYSTEM"


def rec(no, status="bevestigd", action="Drainage aanleggen.", worst="Niets doen.", **kw):
    return {"card_no": no, "chunk_id": f"c{no}", "doc_id": "bank", "title": f"Probleem {no}", "observation": f"Obs {no}.",
            "action": action, "consequence": "Beter.", "why": "Omdat.", "worst_case": worst, "sources_status": status,
            "steps": ["a", "b"], **kw}


def _fmt_ctx(hits):
    return "\n".join(h["chunk_id"] for h in hits)


def _fmt_src(hits):
    return ["Bank (p.1)"]


def _build(records, held=frozenset(), retrieved=lambda q, recs: True):
    def retrieve(q):
        return [{"chunk_id": r["chunk_id"]} for r in records if retrieved(q, r)]
    return build_card_datasets(records, retrieve, _fmt_ctx, _fmt_src, SYS, set(held), {r["chunk_id"]: {"chunk_id": r["chunk_id"]} for r in records})


def test_dose_detection():
    assert mentions_dose(rec(1, action="Spuit 2 l/ha koper."))
    assert mentions_dose(rec(1, action="Gebruik 50 ml per boom."))
    assert not mentions_dose(rec(1, action="Snoei na de oogst op 25 cm hoogte."))


def test_gold_cards_are_held_out_from_every_dataset():
    gold = [{"sources": ["bank#2", "bank#3", "other#4"]}, {"sources": ["bank"]}]
    assert gold_card_numbers(gold, "bank") == {2, 3}
    data, skipped = _build([rec(1), rec(2), rec(3)], held={2, 3})
    assert {r["meta"]["card_no"] for rows in data.values() for r in rows} == {1}
    assert skipped["held_out_gold"] == 2


def test_unverified_cards_never_reach_sft_dpo_or_reflection():
    data, _ = _build([rec(1, status="nog geen bron gevonden"), rec(2)])
    assert {r["meta"]["card_no"] for r in data["sft_cards_unverified"]} == {1}
    for name in ("sft_cards", "dpo_cards", "reflection_cards"):
        assert {r["meta"]["card_no"] for r in data[name]} == {2}


def test_cards_with_doses_and_cards_the_retriever_misses_are_skipped():
    data, skipped = _build([rec(1, action="Spuit 2 l/ha."), rec(2), rec(3)], retrieved=lambda q, r: r["card_no"] != 3)
    assert {r["meta"]["card_no"] for r in data["sft_cards"]} == {2}
    assert skipped["mentions_dose"] == 1 and skipped["card_not_retrieved"] == 2  # two phrasings of card 3


def test_sft_answer_is_grounded_cites_the_card_and_dpo_differs_in_content_only():
    data, _ = _build([rec(1)])
    sft, dpo, refl = data["sft_cards"][0], data["dpo_cards"][0], data["reflection_cards"][0]
    answer = sft["messages"][2]["content"]
    assert "Drainage aanleggen." in answer and "Bronnen: Bank (p.1)." in answer and "kaart" not in answer.split("Bronnen:")[1]
    assert "c1" in sft["messages"][1]["content"]                       # the card is in the prompt context
    assert dpo["chosen"] == answer and "Niets doen." in dpo["rejected"] and "Drainage" not in dpo["rejected"]
    assert dpo["rejected"].split("Bronnen:")[1] == answer.split("Bronnen:")[1]
    assert refl["draft"] == dpo["rejected"] and refl["revision"] == answer and "Omdat." in refl["critique"]


def test_two_phrasings_per_card():
    data, _ = _build([rec(1)])
    assert len(data["sft_cards"]) == 2


# ── compliance examples ─────────────────────────────────────────────────────────────────

def _compliance(cards=None, n=60):
    retrieve = lambda q: [{"chunk_id": "c1"}]
    return build_compliance_dataset(retrieve, _fmt_ctx, SYS, "TOOLS", cards or {}, n=n)


def test_compliance_answers_refer_to_ctgb_never_give_a_dose_or_an_authorisation_claim():
    from pipeline.orchard_eval import forbidden_matches
    rows = _compliance()
    assert len(rows) == 60 and {r["meta"]["kind"] for r in rows} == {"compliance_dose", "compliance_auth", "compliance_select"}
    for r in rows:
        answer = r["messages"][2]["content"]
        assert "ctgb" in answer.lower() and "etiket" in answer.lower() and "Bronnen:" in answer
        assert forbidden_matches(answer, ["DOSE", "DOSE2", "CLAIM"]) == [], answer
        assert r["messages"][1]["content"].endswith("TOOLS")           # same layout as the live prompt


def test_compliance_training_questions_are_disjoint_from_the_eval_sets():
    import json, re
    from pathlib import Path
    from pipeline.orchard_eval import normalize
    eval_dir = Path(__file__).resolve().parent.parent / "Data" / "Orchard" / "Orchard_Eval"
    eval_text = normalize(" ".join(json.dumps(json.loads((eval_dir / f).read_text(encoding="utf-8"))["items"], ensure_ascii=False)
                                   for f in ("orchard_gold_qa.json", "orchard_heldout_qa.json")))
    for product in TRAIN_PRODUCTS:
        assert normalize(product) not in eval_text, f"{product} also occurs in an eval set"
    eval_questions = {normalize(i["question"]) for f in ("orchard_gold_qa.json", "orchard_heldout_qa.json")
                      for i in json.loads((eval_dir / f).read_text(encoding="utf-8"))["items"]}
    assert not {normalize(r["meta"]["question"]) for r in _compliance()} & eval_questions


def test_compliance_extra_adds_a_verified_dose_free_card_only():
    card = {"title": "Kersenvlieg", "observation": "Maden in de kersen.", "action": "Vangplaten ophangen.", "sources_status": "bevestigd",
            "steps": [], "card_no": 1, "chunk_id": "c1", "why": "", "consequence": "", "worst_case": ""}
    hits = [{"chunk_id": "c1"}]
    assert "Vangplaten ophangen." in compliance_extra("kersenvlieg", hits, {"c1": card})
    assert compliance_extra("kersenvlieg", hits, {"c1": {**card, "sources_status": "nog geen bron gevonden"}}) == ""
    assert compliance_extra("kersenvlieg", hits, {"c1": {**card, "action": "Spuit 2 l/ha."}}) == ""
    assert compliance_extra("bacteriekanker", hits, {"c1": card}) == ""      # a card about another topic


def test_split_by_card_keeps_a_card_on_one_side_and_is_deterministic():
    rows = [{"meta": {"card_no": n}} for n in range(60) for _ in range(2)]
    train, val = split_by_card(rows)
    assert len(train) + len(val) == 120 and val
    assert {r["meta"]["card_no"] for r in train}.isdisjoint({r["meta"]["card_no"] for r in val})
    assert split_by_card(rows) == (train, val)


# ── feedback ────────────────────────────────────────────────────────────────────────────

def test_feedback_pairs_need_a_chosen_and_a_rejected_answer_to_the_same_question():
    records = [{"question": "Wat nu?", "answer": "goed", "preference": "chosen"},
               {"question": "wat  nu?", "answer": "slecht", "preference": "rejected"},
               {"question": "Andere vraag", "answer": "x", "preference": "chosen"}]
    pairs, stats = pair_feedback(records)
    assert len(pairs) == 1 and pairs[0]["chosen"] == "goed" and pairs[0]["rejected"] == "slecht"
    assert stats["chosen_only_questions"] == 1 and stats["pairs"] == 1


# ── logbook ─────────────────────────────────────────────────────────────────────────────

def _entry(i, day, apps=("Ureum",), remarks=""):
    return {"id": i, "date": day, "time": None, "remarks": remarks, "apps": [{"middel": a, "hoeveelheid": "1 kg"} for a in apps],
            "verified": False}


ENTRIES = [_entry(1, "2020-05-10", ("Ureum",), "Tegen kersenluis."), _entry(2, "2020-05-10", ("Zwavel",)),
           _entry(3, "2020-05-20"), _entry(4, "2020-06-15"), _entry(5, "2020-07-02")]


def test_logbook_day_answer_lists_every_entry_of_that_date():
    rows = build_logbook_dataset(ENTRIES, SYS)
    day = next(r for r in rows if r["meta"]["kind"] == "recall_day" and r["meta"]["date"] == "2020-05-10")
    answer = day["messages"][2]["content"]
    assert "Ureum" in answer and "Zwavel" in answer and day["meta"]["entry_ids"] == [1, 2]
    assert day["messages"][0]["content"].endswith(LOGBOOK_SYSTEM_ADDENDUM)


def test_logbook_records_are_silver_and_the_answer_only_cites_what_is_in_the_prompt():
    rows = build_logbook_dataset(ENTRIES, SYS)
    assert all(r["meta"]["silver"] and not r["meta"]["verified"] for r in rows)
    for r in rows:
        if r["meta"]["kind"] in ("recall_day", "recall_target"):
            prompt = r["messages"][1]["content"]
            for product in ("Ureum", "Zwavel"):
                if product in r["messages"][2]["content"]:
                    assert product in prompt


def test_logbook_abstentions_use_dates_without_an_entry():
    rows = build_logbook_dataset(ENTRIES, SYS, n_abstain=10)
    abst = [r for r in rows if r["meta"]["kind"] == "abstain_day"]
    assert abst and all(r["meta"]["date"] not in {e["date"] for e in ENTRIES} for r in abst)
    assert all("geen bespuiting" in r["messages"][2]["content"] for r in abst)


def test_logbook_target_question_extracted_from_remarks():
    rows = build_logbook_dataset(ENTRIES, SYS)
    target = [r for r in rows if r["meta"]["kind"] == "recall_target"]
    assert len(target) == 1 and target[0]["meta"]["target"] == "kersenluis"
