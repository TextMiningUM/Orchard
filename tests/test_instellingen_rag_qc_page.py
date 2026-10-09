"""Smoke test for the "Controleer RAG Chunks" button on the Instellingen page."""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

PAGE_PATH = str(Path(__file__).resolve().parent.parent / "app" / "pages" / "11_Instellingen.py")

_FAKE_DOCS = [{
    "doc_id": "doc_a", "title": "Doc A", "language": "nl",
    "chunks": [
        {"chunk_id": "c1", "chunk_index": 0, "title": "Goed", "pages": [1],
         "text": "Dit is een complete zin. Dit is er nog een.",
         "qc": {"verdict": "ok", "reasons": [], "issues": []}},
        {"chunk_id": "c2", "chunk_index": 1, "title": "Kapot", "pages": [2],
         "text": "begint midden in een zin en houdt op",
         "qc": {"verdict": "fail", "reasons": ["begint midden in een zin"], "issues": ["page_break"]}},
    ],
}]
_FAKE_RESULT = {
    "docs": _FAKE_DOCS,
    "summary": {"counts": {"ok": 1, "fail": 1}, "issues": {"page_break": 1}, "lm": False,
                "n_chunks": 2, "n_docs": 1},
    "report": "# Orchard QC-rapport RAG-chunks\n",
}


def test_page_loads_with_qc_button():
    at = AppTest.from_file(PAGE_PATH)
    at.run(timeout=30)
    assert not at.exception
    assert any(b.label == "Controleer RAG Chunks" for b in at.button)


def test_button_runs_qc_and_shows_results(monkeypatch):
    monkeypatch.setattr("pipeline.ingest.orchard_qc.qc_rag_index", lambda *a, **k: _FAKE_RESULT)
    at = AppTest.from_file(PAGE_PATH)
    at.run(timeout=30)
    next(b for b in at.button if b.label == "Controleer RAG Chunks").click()
    at.run(timeout=30)
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Chunks"] == "2"
    assert metrics["Afgekeurd (fail)"] == "1"


def test_missing_index_shows_warning(monkeypatch):
    monkeypatch.setattr("pipeline.ingest.orchard_qc.qc_rag_index", lambda *a, **k: None)
    at = AppTest.from_file(PAGE_PATH)
    at.run(timeout=30)
    next(b for b in at.button if b.label == "Controleer RAG Chunks").click()
    at.run(timeout=30)
    assert not at.exception
    assert any("nog geen RAG-index" in w.value for w in at.warning)
