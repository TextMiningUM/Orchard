"""Tests for pipeline/ingest/build_orchard_rag.py's chunker, including the embedding-based
topic-boundary detection ported from Auto Pilot's build_rag.py (design doc Deel F #18/G.18).

Uses a FAKE embedding model + tokenizer (no sentence-transformers model load, no GPU/network)
-- per project test conventions, mock any model call. The fake embedder maps a sentence to one
of two orthogonal directions purely by keyword presence, so topic shifts are deterministic and
don't depend on a real model's actual semantics (same technique Auto Pilot's own
test_build_rag_chunking.py uses).
"""
from __future__ import annotations

import numpy as np
import pytest

from pipeline.ingest import build_orchard_rag


class _FakeTokenizer:
    def encode(self, text: str, add_special_tokens: bool = False) -> list[str]:
        return text.split()


class _FakeModel:
    """2D fake embedder: 'monilia' -> [1, 0], 'kevers' -> [0, 1], anything else -> [0.7, 0.7]
    (all L2-normalized), so two keyword-distinguished "topics" are deterministically
    orthogonal-ish and everything else is a neutral middle ground."""

    def get_sentence_embedding_dimension(self) -> int:
        return 2

    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False):
        vecs = []
        for t in texts:
            low = t.lower()
            if "monilia" in low:
                v = np.array([1.0, 0.0])
            elif "kevers" in low:
                v = np.array([0.0, 1.0])
            else:
                v = np.array([0.7, 0.7])
            vecs.append(v / np.linalg.norm(v))
        return np.array(vecs)


@pytest.fixture(autouse=True)
def _fake_embedder(monkeypatch):
    monkeypatch.setattr(build_orchard_rag, "model", _FakeModel())
    monkeypatch.setattr(build_orchard_rag, "tokenizer", _FakeTokenizer())


def _section(section_id: str, text: str, section_type: str = "prose", pages=None) -> dict:
    return {"section_id": section_id, "title": section_id, "type": section_type,
            "text": text, "pages": pages or [1]}


def _doc(sections: list[dict], doc_id: str = "doc1") -> dict:
    return {
        "doc_id": doc_id, "title": "Test Document", "category": "test", "language": "nl",
        "url": "https://example.com/test", "source_file": "test.pdf", "sections": sections,
    }


# ── _split_section_by_topic ────────────────────────────────────────────────────────────
def test_splits_a_section_that_internally_drifts_topic():
    section = _section("s1", (
        "Monilia tast de bloesem aan in het voorjaar. Monilia veroorzaakt bloesemsterfte. "
        "Monilia-sporen verspreiden zich via de wind. Kevers vreten gaatjes in jonge vruchten. "
        "Kevers zijn actief vanaf mei. Kevers overwinteren in de grond."
    ))
    pieces = build_orchard_rag._split_section_by_topic(section)
    assert len(pieces) == 2
    assert "monilia" in pieces[0]["text"].lower()
    assert "kevers" in pieces[1]["text"].lower()
    assert pieces[0]["semantic_split"] is True
    assert pieces[0]["section_id"] == "s1_t1"
    assert pieces[1]["section_id"] == "s1_t2"


def test_does_not_split_a_standalone_type_section_even_with_a_real_topic_shift():
    # "probleem" is in STANDALONE_TYPES -- must stay one complete, unsplit retrieval unit
    # even with the exact same detectable topic shift as the "prose" test above. This is
    # the guarantee that keeps one numbered item's own sources from drifting onto a
    # neighbouring item.
    section = _section("s1", (
        "Monilia tast de bloesem aan in het voorjaar. Monilia veroorzaakt bloesemsterfte. "
        "Monilia-sporen verspreiden zich via de wind. Kevers vreten gaatjes in jonge vruchten. "
        "Kevers zijn actief vanaf mei. Kevers overwinteren in de grond."
    ), section_type="probleem")
    pieces = build_orchard_rag._split_section_by_topic(section)
    assert pieces == [section]


def test_does_not_split_a_section_with_too_few_sentences():
    section = _section("s1", "Monilia komt vaak voor. Kevers soms ook.")
    pieces = build_orchard_rag._split_section_by_topic(section)
    assert pieces == [section]


def test_does_not_split_a_single_topic_section():
    section = _section("s1", (
        "Monilia tast de bloesem aan in het voorjaar. Monilia veroorzaakt bloesemsterfte. "
        "Monilia-sporen verspreiden zich via de wind en regen. Monilia overwintert in "
        "vruchtmummies. Monilia-infecties nemen toe bij vochtig weer. Monilia is de "
        "belangrijkste oorzaak van bloesemsterfte bij kersen."
    ))
    pieces = build_orchard_rag._split_section_by_topic(section)
    assert len(pieces) == 1


# ── chunk_document: embedding-based merge-blocking + STANDALONE isolation ──────────────
def test_chunk_document_blocks_a_merge_across_a_real_topic_shift():
    doc = _doc([
        _section("s1", "Monilia komt dit jaar vroeg voor in de boomgaard."),
        _section("s2", "Monilia-bestrijding is het belangrijkst tijdens de bloei."),
        _section("s3", "Kevers worden dit jaar in grote aantallen waargenomen."),
        _section("s4", "Kevers bestrijden kan het beste vroeg in het seizoen."),
    ])
    chunks = build_orchard_rag.chunk_document(doc)
    section_id_groups = [c["section_ids"] for c in chunks]
    # s1+s2 (monilia/monilia) and s3+s4 (kevers/kevers) should each merge; s2+s3 must NOT.
    assert ["s1", "s2"] in section_id_groups
    assert ["s3", "s4"] in section_id_groups


def test_chunk_document_never_merges_a_standalone_probleem_section_with_a_neighbour():
    doc = _doc([
        _section("s1", "Monilia komt dit jaar vroeg voor in de boomgaard.", section_type="probleem"),
        _section("s2", "Monilia-bestrijding is het belangrijkst tijdens de bloei.", section_type="probleem"),
    ])
    chunks = build_orchard_rag.chunk_document(doc)
    assert len(chunks) == 2
    assert chunks[0]["section_ids"] == ["s1"]
    assert chunks[1]["section_ids"] == ["s2"]


def test_contains_semantic_split_flag_propagates_to_the_chunk():
    long_mixed_text = (
        "Monilia tast de bloesem aan in het voorjaar. Monilia veroorzaakt bloesemsterfte. "
        "Monilia-sporen verspreiden zich via de wind. Kevers vreten gaatjes in jonge vruchten. "
        "Kevers zijn actief vanaf mei. Kevers overwinteren in de grond."
    )
    doc = _doc([_section("s1", long_mixed_text)])
    chunks = build_orchard_rag.chunk_document(doc)
    assert any(c["contains_semantic_split"] for c in chunks)


# ── degenerate-chunk filter ─────────────────────────────────────────────────────────────
def test_is_degenerate_chunk_text_drops_near_empty_fragments():
    assert build_orchard_rag._is_degenerate_chunk_text("BMP") is True
    assert build_orchard_rag._is_degenerate_chunk_text("10") is True
    assert build_orchard_rag._is_degenerate_chunk_text("\u2022") is True
    assert build_orchard_rag._is_degenerate_chunk_text("Planning") is True


def test_is_degenerate_chunk_text_keeps_real_sentences():
    assert build_orchard_rag._is_degenerate_chunk_text("Monilia komt vaak voor bij kersen.") is False
    assert build_orchard_rag._is_degenerate_chunk_text("34. Bladvlekkenziekte (Blumeriella)") is False


def test_chunk_document_drops_degenerate_sections():
    doc = _doc([
        # "probleem" (STANDALONE) so it can never merge into the next section -- isolates
        # the degenerate-filter behavior from the separate merge-decision logic.
        _section("s1", "BMP", section_type="probleem"),
        _section("s2", "Monilia komt dit jaar vroeg voor in de boomgaard."),
    ])
    chunks = build_orchard_rag.chunk_document(doc)
    assert len(chunks) == 1
    assert "Monilia" in chunks[0]["text"]


def test_chunk_document_excludes_hardcoded_junk_chunk_ids(monkeypatch):
    doc = _doc([_section("s1", "Monilia komt dit jaar vroeg voor in de boomgaard.")])
    chunks = build_orchard_rag.chunk_document(doc)
    assert len(chunks) == 1
    monkeypatch.setattr(build_orchard_rag, "EXCLUDED_CHUNK_IDS", {chunks[0]["chunk_id"]})
    assert build_orchard_rag.chunk_document(doc) == []


# ── stable_chunk_id ─────────────────────────────────────────────────────────────────────
def test_stable_chunk_id_deterministic_and_unique():
    a = build_orchard_rag.stable_chunk_id("doc1", 0, "tekst een")
    b = build_orchard_rag.stable_chunk_id("doc1", 0, "tekst een")
    c = build_orchard_rag.stable_chunk_id("doc1", 1, "tekst twee")
    assert a == b
    assert a != c
    assert a.startswith("doc1_")


# ── end-to-end: one probleem per chunk (the user's core requirement) ───────────────────
def test_chunk_document_produces_one_chunk_per_numbered_item():
    doc = _doc([
        _section("s1", "**1. Monilia**\n\n- Observatie: ...\n\n* Bronnen: A.", section_type="probleem"),
        _section("s2", "**2. Kevers**\n\n- Observatie: ...\n\n* Bronnen: B.", section_type="probleem"),
        _section("s3", "**3. Vorst**\n\n- Observatie: ...\n\n* Bronnen: C.", section_type="probleem"),
    ])
    chunks = build_orchard_rag.chunk_document(doc)
    assert len(chunks) == 3
    for i, c in enumerate(chunks, start=1):
        assert c["n_sections"] == 1
        assert f"s{i}" in c["section_ids"]
