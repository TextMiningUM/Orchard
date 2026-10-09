"""Unit tests for pipeline.orchard_rag -- only the pure helpers (no embedding/reranker model
load in the automated suite; retrieval quality is smoke-tested manually once the index is
built, see build_orchard_rag.py)."""
from __future__ import annotations

from pipeline.orchard_rag import (DOSE_PLACEHOLDER, _cap_per_document, _format_pages, format_context, format_sources,
                                  redact_doses)


def _hit(doc_id: str, title: str, pages: list[int], text: str = "...", url: str | None = None,
         language: str = "nl") -> dict:
    return {"doc_id": doc_id, "title": title, "pages": pages, "text": text,
            "url": url, "language": language}


def test_cap_per_document_limits_hits_per_source():
    hits = [_hit("a", "Doc A", [1]), _hit("a", "Doc A", [2]), _hit("a", "Doc A", [3]), _hit("b", "Doc B", [1])]
    capped = _cap_per_document(hits, max_per_document=2)
    assert sum(1 for h in capped if h["doc_id"] == "a") == 2
    assert sum(1 for h in capped if h["doc_id"] == "b") == 1


def test_format_context_empty_hits():
    assert "geen relevante" in format_context([]).lower()


def test_redact_doses_removes_per_area_doses_but_keeps_other_numbers():
    text = "Gebruik 5 liter per hectare of 2,5 kg/ha; de boom is 3 meter hoog en 12 jaar oud, bij 25 g/hl."
    out = redact_doses(text)
    assert out.count(DOSE_PLACEHOLDER) == 3
    assert "3 meter hoog en 12 jaar oud" in out and "5 liter" not in out and "kg/ha" not in out


def test_format_context_never_shows_a_product_dose():
    hit = _hit("a", "Webshop", [1], text="Vitalosol Gold: 5 liter per hectare tegen schimmels.")
    out = format_context([hit])
    assert "Vitalosol Gold" in out and "5 liter per hectare" not in out and DOSE_PLACEHOLDER in out


def test_format_context_shows_the_section_so_a_card_is_identifiable():
    hits = [{**_hit("a", "Gids", [4], text="Observatie: iets."), "heading_path": ["Gids", "Groep", "21. Nachtvorst tijdens de bloei"]}]
    assert "sectie: Groep > 21. Nachtvorst tijdens de bloei" in format_context(hits)


def test_format_context_labels_english_sources():
    hits = [_hit("a", "English Doc", [1], text="Some text.", language="en")]
    ctx = format_context(hits)
    assert "Engelstalige bron" in ctx
    assert "Some text." in ctx


def test_format_sources_dedups_by_document():
    hits = [_hit("a", "Doc A", [1], url="https://example.com/a"), _hit("a", "Doc A", [2])]
    sources = format_sources(hits)
    assert len(sources) == 1
    assert "Doc A" in sources[0]


def test_format_pages_single_page():
    assert _format_pages({"pages": [3]}) == "p.3"


def test_format_pages_contiguous_range():
    assert _format_pages({"pages": [2, 3, 4]}) == "p.2-4"


def test_format_pages_non_contiguous():
    assert _format_pages({"pages": [2, 5]}) == "p.2, 5"


def test_format_pages_falls_back_to_legacy_page_num():
    assert _format_pages({"pages": [], "page_num": 7}) == "p.7"
