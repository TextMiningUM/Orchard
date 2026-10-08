"""Unit tests for pipeline.ingest.build_orchard_corpus -- the acquisition LOGIC only
(blocked-entry handling, idempotent skip-if-already-on-disk, manifest shape). Real network
fetches are NOT re-run here (consistent with this project's test discipline) -- those were
verified manually during the corpus-acquisition session; this test monkeypatches
``_fetch`` so the suite stays fast/offline.
"""
from __future__ import annotations

import pipeline.ingest.build_orchard_corpus as corpus_mod
from pipeline.ingest.build_orchard_corpus import SourceSpec, build_corpus


def test_build_corpus_handles_blocked_entries_without_network(tmp_path, monkeypatch):
    fake_sources = [
        SourceSpec(
            id="blocked_one", title="Een geblokkeerde bron", category="test_cat",
            url=None, filename=None, language="nl", status="blocked", note="niet bereikbaar",
        ),
    ]
    monkeypatch.setattr(corpus_mod, "SOURCES", fake_sources)
    manifest = build_corpus(tmp_path)
    assert len(manifest) == 1
    assert manifest[0]["status"] == "blocked"
    assert manifest[0]["id"] == "blocked_one"


def test_build_corpus_fetches_new_source(tmp_path, monkeypatch):
    fake_sources = [
        SourceSpec(
            id="fetchable_one", title="Een testbron", category="test_cat",
            url="https://example.invalid/test.pdf", filename="test.pdf",
            language="nl", status="to_fetch",
        ),
    ]
    monkeypatch.setattr(corpus_mod, "SOURCES", fake_sources)

    def _fake_fetch(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(corpus_mod, "_fetch", _fake_fetch)
    manifest = build_corpus(tmp_path)
    assert manifest[0]["status"] == "acquired"
    assert (tmp_path / "test_cat" / "test.pdf").exists()
    assert manifest[0]["sha256"]


def test_build_corpus_skips_already_acquired_file(tmp_path, monkeypatch):
    fake_sources = [
        SourceSpec(
            id="existing_one", title="Al aanwezig", category="test_cat",
            url="https://example.invalid/test2.pdf", filename="test2.pdf",
            language="nl", status="to_fetch",
        ),
    ]
    monkeypatch.setattr(corpus_mod, "SOURCES", fake_sources)
    existing = tmp_path / "test_cat" / "test2.pdf"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"already here")

    def _should_not_be_called(url, dest):
        raise AssertionError("_fetch should not be called for an already-acquired file")

    monkeypatch.setattr(corpus_mod, "_fetch", _should_not_be_called)
    manifest = build_corpus(tmp_path)
    assert manifest[0]["status"] == "already_acquired"


def test_build_corpus_records_failure_honestly(tmp_path, monkeypatch):
    fake_sources = [
        SourceSpec(
            id="failing_one", title="Mislukt", category="test_cat",
            url="https://example.invalid/fail.pdf", filename="fail.pdf",
            language="nl", status="to_fetch",
        ),
    ]
    monkeypatch.setattr(corpus_mod, "SOURCES", fake_sources)

    def _fake_fetch_fail(url, dest):
        raise ConnectionError("simulated network failure")

    monkeypatch.setattr(corpus_mod, "_fetch", _fake_fetch_fail)
    manifest = build_corpus(tmp_path)
    assert manifest[0]["status"] == "failed"
    assert "simulated network failure" in manifest[0]["error"]
