"""Unit tests for pipeline.orchard_rag -- only the pure helpers (no embedding/reranker model
load in the automated suite; retrieval quality is smoke-tested manually once the index is
built, see build_orchard_rag.py)."""
from __future__ import annotations

from pipeline.orchard_rag import _cap_per_document, format_context, format_sources


def _hit(doc_id: str, title: str, page_num: int, text: str = "...", url: str | None = None,
         language: str = "nl") -> dict:
    return {"doc_id": doc_id, "title": title, "page_num": page_num, "text": text,
            "url": url, "language": language}


def test_cap_per_document_limits_hits_per_source():
    hits = [_hit("a", "Doc A", 1), _hit("a", "Doc A", 2), _hit("a", "Doc A", 3), _hit("b", "Doc B", 1)]
    capped = _cap_per_document(hits, max_per_document=2)
    assert sum(1 for h in capped if h["doc_id"] == "a") == 2
    assert sum(1 for h in capped if h["doc_id"] == "b") == 1


def test_format_context_empty_hits():
    assert "geen relevante" in format_context([]).lower()


def test_format_context_labels_english_sources():
    hits = [_hit("a", "English Doc", 1, text="Some text.", language="en")]
    ctx = format_context(hits)
    assert "Engelstalige bron" in ctx
    assert "Some text." in ctx


def test_format_sources_dedups_by_document():
    hits = [_hit("a", "Doc A", 1, url="https://example.com/a"), _hit("a", "Doc A", 2)]
    sources = format_sources(hits)
    assert len(sources) == 1
    assert "Doc A" in sources[0]
