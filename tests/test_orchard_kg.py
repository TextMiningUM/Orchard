"""Concept lexicon, knowledge graph and hybrid retrieval."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from pipeline.orchard_concepts import CONCEPTS, aliases_for_kg, concept_category, fold, tag_text
from pipeline.orchard_kg import build_kg, idf_weight, query_concepts, retrieve_hybrid
from pipeline.orchard_rag import _cap_per_document, retrieve


def _chunk(cid, text, doc="d1", title="", typ="prose", path=None):
    return {"chunk_id": cid, "doc_id": doc, "title": title or cid, "heading_path": path or [title or cid],
            "type": typ, "pages": [1], "text": text, "text_with_context": text, "language": "nl"}


# ── lexicon ─────────────────────────────────────────────────────────────────────────────

def test_fold_removes_accents_and_case():
    assert fold("  \u00c9\u00e9n  Ge\u00efntegreerde ") == "een geintegreerde"


def test_aliases_map_latin_english_and_dutch_to_one_concept():
    for text in ("Stigmina carpophila op het blad", "typische shot hole symptomen", "last van hagelschot"):
        assert "hagelschot" in tag_text(text)


def test_colloquial_symptom_words_reach_the_pest_concept():
    assert "spint" in tag_text("blad is dof en bronskleurig met fijne webjes")


def test_prefix_match_finds_compounds_but_short_aliases_need_whole_words():
    assert "vorst" in tag_text("ernstige nachtvorst en vorstschade")
    assert "bemesting" in tag_text("de stikstofgift")          # "stikstof" prefix
    assert "colt" in tag_text("onderstam Colt") and "colt" not in tag_text("het is een Colton-type")
    assert "kersenvlieg" in tag_text("Rhagoletis cerasi")


def test_no_match_for_unrelated_text():
    assert tag_text("Dit is een zin over het weer van gisteren in Amsterdam.") == {}


def test_every_concept_has_category_and_aliases_and_no_alias_is_ambiguous_noise():
    for concept, (category, aliases) in CONCEPTS.items():
        assert category and aliases, concept
        assert concept_category(concept) == category
    assert all(len(a) >= 3 or a in ("ras",) for a in aliases_for_kg()), "very short aliases cause false matches"
    assert "van" not in aliases_for_kg()


# ── graph ───────────────────────────────────────────────────────────────────────────────

CHUNKS = [
    _chunk("a", "Hagelschot geeft gaatjes in het blad. Stigmina carpophila overwintert in knoppen.", title="Hagelschot"),
    _chunk("b", "Kersenvlieg legt eieren in rijpende kersen. De made eet het vruchtvlees.", title="Kersenvlieg"),
    _chunk("c", "Bij vorst in de bloei kan bloesem bevriezen. Vorstberegening helpt bij nachtvorst.", title="Vorst"),
    _chunk("d", "Een algemene zin zonder vakterm over de tuin en de boom en de wolken.", title="Algemeen"),
]


def test_build_kg_structure():
    kg = build_kg(CHUNKS)
    assert kg["concept_chunks"]["hagelschot"] == ["a"]
    assert kg["title_concepts"]["a"] == ["hagelschot"]
    assert kg["chunk_concepts"]["d"] == {}
    assert kg["stats"]["n_chunks"] == 4 and kg["stats"]["chunks_without_concepts"] == 1
    assert kg["adjacency"]["b"] == ["a", "c"]
    assert query_concepts("wat is hagelschot?", kg) == ["hagelschot"]
    assert query_concepts("iets over kersen-onbekend", kg) == []


def test_idf_weight_is_high_for_rare_and_low_for_common_concepts():
    kg = build_kg([_chunk(str(i), "gewasbescherming en bespuiting") for i in range(9)] + [_chunk("r", "hagelschot")])
    assert idf_weight(kg, "hagelschot") > idf_weight(kg, "gewasbescherming")
    assert idf_weight(kg, "gewasbescherming") < 0.1


class FakeEmbedder:
    def encode(self, texts, **kw):
        return np.array([[1.0, 0.0]])


def _index(chunks, embeddings, kg):
    return SimpleNamespace(embedder=FakeEmbedder(), query_prefix="", embeddings=np.array(embeddings),
                           chunk_ids=[c["chunk_id"] for c in chunks], chunk_by_id={c["chunk_id"]: c for c in chunks},
                           kg=kg, reranker=None)


def test_concept_boost_lifts_a_chunk_that_dense_search_ranks_lower():
    kg = build_kg(CHUNKS)
    # chunk d is dense-closest, chunk a (hagelschot) slightly less so
    index = _index(CHUNKS, [[0.60, 0.8], [0.0, 1.0], [0.0, 1.0], [0.62, 0.78]], kg)
    dense_order = [h["chunk_id"] for h in retrieve("hagelschot?", index, k=4, hybrid=False)]
    hybrid = retrieve_hybrid("hagelschot?", index, kg, k=4)
    assert dense_order[0] == "d"
    assert hybrid[0]["chunk_id"] == "a" and hybrid[0]["concept_hits"] == ["hagelschot"]


def test_retrieve_is_hybrid_by_default_only_when_the_index_has_a_kg():
    kg = build_kg(CHUNKS)
    emb = [[0.60, 0.8], [0.0, 1.0], [0.0, 1.0], [0.62, 0.78]]
    assert retrieve("hagelschot?", _index(CHUNKS, emb, kg), k=1, rerank=False)[0]["chunk_id"] == "a"
    assert retrieve("hagelschot?", _index(CHUNKS, emb, None), k=1, rerank=False)[0]["chunk_id"] == "d"


def test_problem_cards_are_exempt_from_the_per_document_cap_but_prose_is_not():
    cards = [{"doc_id": "bank", "type": "probleem", "title": f"{i}. x"} for i in range(5)]
    prose = [{"doc_id": "book", "type": "prose", "title": f"s{i}"} for i in range(5)]
    assert len(_cap_per_document(cards, 3)) == 5
    assert len(_cap_per_document(prose, 3)) == 3
