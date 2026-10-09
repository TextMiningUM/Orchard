"""Tests for pipeline.ingest.build_orchard_rag: the index is built ONLY from QC-passed chunks of the
structured JSON (fake embedder, no model download)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np

from pipeline.ingest import build_orchard_rag as br


def _doc(doc_id="d1", chunks=None):
    return {"doc_id": doc_id, "title": "Gids", "category": "cat", "language": "nl", "url": "https://x.nl",
            "source_file": "a.pdf", "source_type": "pdf", "chunks": chunks or []}


def _chunk(cid, verdict, text="Een complete zin over monilia.", ctype="prose"):
    chunk = {"chunk_id": cid, "title": "Monilia", "heading_path": ["Gids", "Monilia"], "type": ctype,
             "pages": [2, 3], "text": text, "text_with_context": f"Bron: Gids\nSectie: Gids > Monilia\n\n{text}",
             "word_count": 5, "table_ids": [], "figure_ids": []}
    if verdict:
        chunk["qc"] = {"verdict": verdict}
    return chunk


def _write(tmp_path, *docs):
    for doc in docs:
        (tmp_path / f"{doc['doc_id']}.json").write_text(json.dumps(doc), encoding="utf-8")


def test_only_ok_and_warn_chunks_are_indexed(tmp_path):
    _write(tmp_path, _doc(chunks=[_chunk("a", "ok"), _chunk("b", "warn"), _chunk("c", "fail"),
                                  _chunk("d", "references"), _chunk("e", None)]))
    records, stats = br.load_indexable_chunks(tmp_path)
    assert [r["chunk_id"] for r in records] == ["a", "b", "e"]  # no QC record yet counts as indexable
    assert stats["chunks_total"] == 5 and stats["chunks_indexed"] == 3
    assert stats["excluded"] == {"fail": 1, "references": 1}


def test_index_record_keeps_document_title_for_citations_and_section_title_separately():
    record = br.to_index_record(_doc(), _chunk("a", "ok"))
    assert record["title"] == "Gids" and record["section_title"] == "Monilia"
    assert record["section_titles"] == ["Monilia"] and record["types"] == ["prose"]
    assert record["page_num"] == 2 and record["language"] == "nl" and record["url"] == "https://x.nl"
    assert record["text_with_context"].startswith("Bron: Gids")


def test_embed_texts_applies_the_passage_prefix():
    seen = []

    class FakeModel:
        def encode(self, texts, **kwargs):
            seen.extend(texts)
            return np.ones((len(texts), 3))

    out = br.embed_texts(FakeModel(), ["a", "b"], prefix="passage: ")
    assert seen == ["passage: a", "passage: b"] and out.dtype == np.float32 and out.shape == (2, 3)


def test_main_writes_chunks_embeddings_ids_and_meta(tmp_path, monkeypatch):
    json_dir, cache_dir = tmp_path / "json", tmp_path / "cache"
    json_dir.mkdir()
    _write(json_dir, _doc(chunks=[_chunk("a", "ok"), _chunk("b", "fail")]))
    monkeypatch.setattr(br.AgentPaths, "orchard", classmethod(lambda cls: SimpleNamespace(json_dir=json_dir, cache_dir=cache_dir)))

    class FakeModel:
        max_seq_length = 128

        def __init__(self, *a, **k):
            pass

        def encode(self, texts, **kwargs):
            return np.ones((len(texts), 4))

    import sentence_transformers
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", FakeModel)
    assert br.main(["--embedder", "intfloat/multilingual-e5-large", "--max-seq-length", "256"]) == 0
    assert json.loads((cache_dir / "orchard_rag_chunk_ids.json").read_text()) == ["a"]
    assert np.load(cache_dir / "orchard_rag_embeddings.npy").shape == (1, 4)
    meta = json.loads((cache_dir / "orchard_rag_meta.json").read_text())
    assert meta["embedder"] == "intfloat/multilingual-e5-large" and meta["query_prefix"] == "query: "
    assert meta["excluded_by_qc"] == {"fail": 1}


def test_main_refuses_to_build_without_indexable_chunks(tmp_path, monkeypatch):
    json_dir = tmp_path / "json"
    json_dir.mkdir()
    _write(json_dir, _doc(chunks=[_chunk("a", "fail")]))
    monkeypatch.setattr(br.AgentPaths, "orchard", classmethod(lambda cls: SimpleNamespace(json_dir=json_dir, cache_dir=tmp_path / "c")))
    assert br.main([]) == 1
