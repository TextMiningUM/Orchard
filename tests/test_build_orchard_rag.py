"""Unit tests for pipeline.ingest.build_orchard_rag -- only the pure chunking logic (no
embedding model load in the automated suite; embedding quality is smoke-tested manually,
see pipeline/orchard_rag.py's own docstring)."""
from __future__ import annotations

from pipeline.ingest.build_orchard_rag import (
    CHUNK_MAX_WORDS,
    _pack_paragraphs,
    _split_paragraphs,
    chunk_document,
    stable_chunk_id,
)


def test_split_paragraphs_on_blank_lines():
    text = "Eerste alinea.\n\nTweede alinea.\n\nDerde alinea."
    assert _split_paragraphs(text) == ["Eerste alinea.", "Tweede alinea.", "Derde alinea."]


def test_pack_paragraphs_merges_short_paragraphs_into_one_chunk():
    paragraphs = ["Korte alinea een.", "Korte alinea twee.", "Korte alinea drie."]
    chunks = _pack_paragraphs(paragraphs)
    assert len(chunks) == 1
    assert "een" in chunks[0] and "twee" in chunks[0] and "drie" in chunks[0]


def test_pack_paragraphs_splits_when_over_budget():
    long_paragraph = ". ".join(f"Dit is zin nummer {i}" for i in range(CHUNK_MAX_WORDS // 4 + 20)) + "."
    chunks = _pack_paragraphs([long_paragraph])
    assert len(chunks) >= 2
    for c in chunks:
        # Allow slack for the overlap prefix, but never wildly over budget.
        assert len(c.split()) <= CHUNK_MAX_WORDS + 60


def test_pack_paragraphs_adds_overlap_between_chunks():
    from pipeline.ingest.build_orchard_rag import CHUNK_OVERLAP_WORDS
    long_paragraph = ". ".join(f"Dit is zin nummer {i}" for i in range(CHUNK_MAX_WORDS // 4 + 20)) + "."
    chunks = _pack_paragraphs([long_paragraph])
    assert len(chunks) >= 2
    first_tail = chunks[0].split()[-CHUNK_OVERLAP_WORDS:]
    second_start = chunks[1].split()[:CHUNK_OVERLAP_WORDS]
    assert first_tail == second_start


def test_pack_paragraphs_no_crash_on_two_short_paragraphs():
    # Regression test: an earlier bug (chunks[-2] assigned AFTER chunks.pop() already
    # shrank the list) raised IndexError whenever exactly 2 short chunks were produced.
    chunks = _pack_paragraphs(["Alinea een is kort.", "Alinea twee is ook kort."])
    assert len(chunks) >= 1


def test_stable_chunk_id_deterministic_and_unique():
    a = stable_chunk_id("doc1", 1, 0)
    b = stable_chunk_id("doc1", 1, 0)
    c = stable_chunk_id("doc1", 1, 1)
    assert a == b
    assert a != c
    assert a.startswith("doc1_")


def test_chunk_document_produces_citable_records():
    doc = {
        "doc_id": "test_doc", "title": "Test Document", "category": "test",
        "language": "nl", "url": "https://example.com/test", "source_file": "test.pdf",
        "pages": [{"page_num": 1, "text": "Dit is een testparagraaf over kersenteelt.\n\nEn nog een."}],
    }
    records = chunk_document(doc)
    assert len(records) >= 1
    for r in records:
        assert r["doc_id"] == "test_doc"
        assert r["page_num"] == 1
        assert r["title"] == "Test Document"
        assert r["text"]
