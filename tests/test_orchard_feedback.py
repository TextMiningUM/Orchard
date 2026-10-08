"""Unit tests for pipeline.orchard_feedback -- DPO-feedback collection (thumbs up/down)."""
from __future__ import annotations

import json

import pytest

from pipeline.orchard_feedback import (
    build_feedback_record,
    feedback_file_path,
    load_feedback,
    save_feedback,
)
from core.paths import AgentPaths


def test_build_feedback_record_chosen():
    record = build_feedback_record(
        "Is er vorstrisico?", "Nee, geen risico.", "redenering...", ["bron A"], ["vorst_risico"],
        "green", "chosen", timestamp="2026-01-01T00:00:00+00:00",
    )
    assert record.preference == "chosen"
    assert record.question == "Is er vorstrisico?"
    assert record.sources == ["bron A"]


def test_build_feedback_record_rejects_invalid_preference():
    with pytest.raises(ValueError):
        build_feedback_record("q", "a", "", [], [], "red", "maybe")


def test_build_feedback_record_defaults_timestamp_when_omitted():
    record = build_feedback_record("q", "a", "", [], [], "red", "rejected")
    assert record.timestamp  # non-empty, some ISO string was generated


def test_save_and_load_feedback_roundtrip(tmp_path):
    paths = AgentPaths.orchard(workspace=tmp_path)
    record = build_feedback_record(
        "Welke dosering?", "Ik weet het niet zeker.", "", [], [], "red", "rejected",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    written_path = save_feedback(record, paths=paths)
    assert written_path == feedback_file_path(paths)
    assert written_path.exists()

    loaded = load_feedback(paths=paths)
    assert len(loaded) == 1
    assert loaded[0].preference == "rejected"
    assert loaded[0].question == "Welke dosering?"


def test_save_feedback_appends_multiple_records(tmp_path):
    paths = AgentPaths.orchard(workspace=tmp_path)
    for pref in ("chosen", "rejected", "chosen"):
        save_feedback(build_feedback_record("q", "a", "", [], [], "green", pref), paths=paths)
    loaded = load_feedback(paths=paths)
    assert len(loaded) == 3
    assert [r.preference for r in loaded] == ["chosen", "rejected", "chosen"]


def test_load_feedback_returns_empty_list_when_file_missing(tmp_path):
    paths = AgentPaths.orchard(workspace=tmp_path)
    assert load_feedback(paths=paths) == []


def test_save_feedback_writes_valid_jsonl(tmp_path):
    paths = AgentPaths.orchard(workspace=tmp_path)
    save_feedback(build_feedback_record("q", "a", "", ["bron"], ["tool"], "green", "chosen"), paths=paths)
    lines = feedback_file_path(paths).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["preference"] == "chosen"
    assert parsed["sources"] == ["bron"]
