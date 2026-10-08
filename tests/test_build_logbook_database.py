"""Unit test for pipeline.ingest.build_logbook_database -- uses a tiny synthetic
transcript fixture (not the real agent output) so it runs instantly and without
depending on the background transcription agents having finished.
"""
from __future__ import annotations

import json
import sqlite3

from pipeline.ingest.build_logbook_database import build_database

SAMPLE_PAGE = {
    "jaar": "2013", "bestand": "jaar 2013.pdf", "pagina": 1,
    "image_path": "C:/fake/page_01.png",
    "entries": [
        {
            "datum_ruw": "8 mei", "datum_iso": "2013-05-08", "tijd": "10:30",
            "toepassingen": [
                {"middel": "Ureum", "hoeveelheid": "1 kg"},
                {"middel": "Kalifosfaat", "hoeveelheid": "0,6 liter"},
            ],
            "opmerkingen": "16°C. Wind vanuit het zuiden.", "onzeker": False,
            "raw_transcript": "8 mei: Ureum 1 kg, Kalifosfaat 0,6 liter. 10.30 u. 16°C.",
        },
        {
            "datum_ruw": "11 mei [?]", "datum_iso": None, "tijd": "15:00",
            "toepassingen": [{"middel": "Albatros", "hoeveelheid": "15 kg"}],
            "opmerkingen": "onleesbaar stuk", "onzeker": True,
            "raw_transcript": "11 mei[?]: Albatros 15 kg op ... [onleesbaar]",
        },
    ],
}


def test_build_database_from_fixture(tmp_path):
    transcripts_dir = tmp_path / "_transcripts"
    transcripts_dir.mkdir()
    (transcripts_dir / "test.json").write_text(json.dumps([SAMPLE_PAGE], ensure_ascii=False), encoding="utf-8")

    db_path = tmp_path / "orchard_logbook.db"
    stats = build_database(transcripts_dir, db_path)

    assert stats["pages"] == 1
    assert stats["entries"] == 2
    assert stats["toepassingen"] == 3
    assert stats["onzeker_entries"] == 1

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT e.datum_iso, t.middel, t.hoeveelheid FROM entries e "
        "JOIN toepassingen t ON t.entry_id = e.id ORDER BY e.id, t.volgorde"
    ).fetchall()
    geverifieerd = conn.execute("SELECT geverifieerd, geverifieerd_op FROM entries").fetchall()
    conn.close()
    assert rows == [
        ("2013-05-08", "Ureum", "1 kg"),
        ("2013-05-08", "Kalifosfaat", "0,6 liter"),
        (None, "Albatros", "15 kg"),
    ]
    assert geverifieerd == [(0, None), (0, None)]


def test_build_database_raises_on_missing_dir(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        build_database(tmp_path / "does_not_exist", tmp_path / "out.db")


def test_build_database_refuses_to_overwrite_verified_entries(tmp_path):
    import pytest

    transcripts_dir = tmp_path / "_transcripts"
    transcripts_dir.mkdir()
    (transcripts_dir / "test.json").write_text(json.dumps([SAMPLE_PAGE], ensure_ascii=False), encoding="utf-8")
    db_path = tmp_path / "orchard_logbook.db"
    build_database(transcripts_dir, db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE entries SET onzeker = 0, geverifieerd = 1, geverifieerd_op = '2026-10-08T12:00:00' WHERE id = 1")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="geverifieerde entries"):
        build_database(transcripts_dir, db_path)

    # force=True still allows an intentional full rebuild
    stats = build_database(transcripts_dir, db_path, force=True)
    assert stats["pages"] == 1
