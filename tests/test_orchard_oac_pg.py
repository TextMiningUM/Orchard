"""OAC extraction from the problem cards and the procedural graph."""
from __future__ import annotations

import numpy as np

from pipeline.ingest.extract_orchard_oac import card_to_trace, extract_cards, parse_card, split_steps
from pipeline.orchard_pg import (build_pg, canonicalize, collect_steps, merge_guard, nearest_node, next_steps,
                                 sample_path)

CARD_TEXT = (
    "- Observatie: Plassen na regen, gele bladeren en slechte groei in natte hoeken.\n"
    "- Actie: Drainage aanleggen of herstellen, op ruggen planten, grondwaterstand meten met peilbuizen.\n"
    "- Gevolg: Wortels krijgen zuurstof en minder Phytophthora.\n"
    "- Waarom: Kersenwortels verdragen geen zuurstofgebrek.\n"
    "- Slechtste reactie: Dode bomen vervangen zonder de waterhuishouding aan te pakken.\n"
    "- Bronnen (deels bevestigd): PNW Handbooks: Phytophthora-wortelrot. Niet gevonden: de diepte van 25-35 cm."
)


def _card(text=CARD_TEXT, title="2. Natte voeten: water blijft staan", cid="c2"):
    return {"chunk_id": cid, "doc_id": "bank", "type": "probleem", "title": title,
            "heading_path": ["Bank", "1. Boomgaard (1-10)", title], "text": text}


def test_parse_card_extracts_every_oac_field_verbatim():
    rec = parse_card(_card())
    assert rec["card_no"] == 2 and rec["title"] == "Natte voeten: water blijft staan"
    assert rec["observation"].startswith("Plassen na regen")
    assert rec["consequence"].startswith("Wortels krijgen") and rec["why"].startswith("Kersenwortels")
    assert rec["worst_case"].startswith("Dode bomen")
    assert rec["sources_status"] == "deels bevestigd" and rec["section"] == "1. Boomgaard (1-10)"
    assert rec["steps"] == ["drainage aanleggen of herstellen", "op ruggen planten",
                            "grondwaterstand meten met peilbuizen"]


def test_incomplete_card_is_skipped_not_guessed():
    assert parse_card(_card(text="- Observatie: Alleen een observatie.")) is None


def test_split_steps_handles_sentences_semicolons_conjunctions_and_short_fragments():
    assert split_steps("Snoei in de zomer; en dan de wonden afwerken. Daarna de takken afvoeren.") == [
        "snoei in de zomer", "de wonden afwerken", "de takken afvoeren"]
    assert split_steps("Ja, nee") == []


def test_card_to_trace_needs_two_steps_and_maps_attributes():
    trace = card_to_trace(parse_card(_card()))
    t = trace["trace"]
    assert [p["step"] for p in t["procedures"]] == [1, 2, 3] and t["procedures"][0]["why"].startswith("Kersenwortels")
    assert t["warnings"][0].startswith("Dode bomen") and t["constraints"][0].startswith("Plassen")
    assert card_to_trace({**parse_card(_card()), "steps": ["enkel een stap"]}) is None


def test_extract_cards_ignores_non_card_chunks():
    records, traces = extract_cards([_card(), {"chunk_id": "p", "doc_id": "x", "type": "prose", "title": "t", "text": "tekst"}])
    assert len(records) == 1 and len(traces) == 1


# ── procedural graph ────────────────────────────────────────────────────────────────────

def test_merge_guard_separates_numbers_and_negation():
    assert merge_guard("diepwoelen op 25 cm") != merge_guard("diepwoelen op 35 cm")
    assert merge_guard("wel snoeien") != merge_guard("niet snoeien")
    assert merge_guard("snoeien") == merge_guard("snoeien in de zomer")


def test_canonicalize_merges_similar_but_not_guard_different_steps():
    emb = np.array([[1.0, 0.0], [0.999, 0.04], [0.999, 0.04]])
    emb = emb / np.linalg.norm(emb, axis=1, keepdims=True)
    node_of, labels = canonicalize(["drainage aanleggen", "drainage aanleggen", "drainage aanleggen op 25 cm"], emb, 0.9)
    assert node_of[0] == node_of[1] != node_of[2] and len(labels) == 2


def _records():
    rows = [
        {"source_file": "a", "family": "bodem", "trace": {"procedures": [{"step": 1, "action": "drainage aanleggen", "why": "zuurstof"},
                                                                      {"step": 2, "action": "op ruggen planten", "why": ""}],
                                                       "constraints": ["natte hoek"], "warnings": ["niets doen"]}},
        {"source_file": "b", "family": "bodem", "trace": {"procedures": [{"step": 1, "action": "drainage aanleggen", "why": ""},
                                                                      {"step": 2, "action": "op ruggen planten", "why": ""},
                                                                      {"step": 3, "action": "peilbuis plaatsen", "why": ""}],
                                                       "constraints": [], "warnings": []}},
        {"source_file": "c", "family": "vorst", "trace": {"procedures": [{"step": 1, "action": "haag openmaken", "why": ""}], "constraints": [], "warnings": []}},
    ]
    return collect_steps(rows)


def _embed(texts):
    vocab = {"drainage aanleggen": [1, 0, 0, 0], "op ruggen planten": [0, 1, 0, 0], "peilbuis plaatsen": [0, 0, 1, 0]}
    return np.array([vocab.get(t, [0, 0, 0, 1]) for t in texts], dtype=float)


def test_collect_steps_drops_traces_with_fewer_than_two_steps():
    assert len(_records()) == 2


def test_build_pg_merges_equal_steps_counts_support_and_keeps_attributes():
    pg = build_pg(_records(), _embed, 0.9)
    assert pg["stats"]["n_nodes"] == 3 and pg["stats"]["merged_nodes"] == 2
    top = pg["edges"][0]
    assert top["support"] == 2 and top["condition"] == ["natte hoek"] and top["pitfalls"] == ["niets doen"]
    assert top["families"] == {"bodem": 2}


def test_sample_path_next_steps_and_nearest_node():
    pg = build_pg(_records(), _embed, 0.9)
    labels = [pg["nodes"][n]["label"] for n in sample_path(pg, "bodem")]
    assert labels == ["drainage aanleggen", "op ruggen planten", "peilbuis plaatsen"]
    start = next(n for n, v in pg["nodes"].items() if v["label"] == "drainage aanleggen")
    assert next_steps(pg, start)[0]["label"] == "op ruggen planten"
    assert nearest_node(pg, "drainage aanleggen", _embed)[0] == start
    assert nearest_node(pg, "iets heel anders", _embed) is None
