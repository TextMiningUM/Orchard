"""Build the Orchard logbook SQLite database from OCR/vision-transcribed JSON pages.

Input: one or more JSON files in ``Data/Orchard/OrchardLogbooks/_transcripts/*.json``,
each a list of page objects following the schema documented in this project's logbook
transcription task (see the ``transcribe-logbook-*`` background-agent prompts for the
exact schema). These files are produced by visually transcribing the scanned handwritten
logbook pages (`Data/Data Log Books/jaar <year>.pdf`) -- see
``design_cherry_orchard_advisor.md`` Sec C.1/C.7 for why this needs vision-based
transcription rather than a classic OCR engine.

Output: a normalized SQLite database at ``Data/Orchard/OrchardLogbooks/orchard_logbook.db``
with three tables (pages / entries / toepassingen) -- this IS the "database" the Track 2
episodic-memory layer (design doc Sec B.4) will query from, and is also the natural source
for the Streamlit Logboek page and for later SFT/DPO dataset builders.

Safe to run LOCALLY (pure stdlib: json, sqlite3, pathlib -- no GPU/API key needed).
Idempotent: drops and recreates all three tables on every run (this is a dataset build
step, not an incremental database) -- BUT see the ``geverifieerd`` column below: once a
human has verified/corrected an entry via the Streamlit "Logboek Verifiëren" page, that
edit lives ONLY in the live ``orchard_logbook.db`` file, not in the ``_transcripts/*.json``
source files. Rebuilding from scratch would silently erase that human verification work,
so ``build_database()`` refuses to overwrite a database that already contains any
``geverifieerd=1`` rows unless called with ``force=True`` (``--force`` on the CLI).

Usage::

    .venv\\Scripts\\python.exe -m pipeline.ingest.build_logbook_database
    .venv\\Scripts\\python.exe -m pipeline.ingest.build_logbook_database --force  # overwrite verified edits too
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from core.paths import AgentPaths  # noqa: E402

SCHEMA = """
CREATE TABLE pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jaar TEXT NOT NULL,
    bestand TEXT NOT NULL,
    pagina INTEGER NOT NULL,
    image_path TEXT,
    opmerkingen_pagina TEXT,
    UNIQUE(bestand, pagina)
);

CREATE TABLE entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER NOT NULL REFERENCES pages(id),
    datum_ruw TEXT,
    datum_iso TEXT,
    tijd TEXT,
    opmerkingen TEXT,
    onzeker INTEGER NOT NULL DEFAULT 0,
    raw_transcript TEXT,
    geverifieerd INTEGER NOT NULL DEFAULT 0,
    geverifieerd_op TEXT
);

CREATE TABLE toepassingen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL REFERENCES entries(id),
    volgorde INTEGER NOT NULL,
    middel TEXT,
    hoeveelheid TEXT
);

CREATE INDEX idx_entries_datum_iso ON entries(datum_iso);
CREATE INDEX idx_entries_page ON entries(page_id);
CREATE INDEX idx_toepassingen_entry ON toepassingen(entry_id);
CREATE INDEX idx_toepassingen_middel ON toepassingen(middel);
"""


def build_database(transcripts_dir: Path, db_path: Path, force: bool = False) -> dict:
    """Load every ``*.json`` transcript file in ``transcripts_dir`` into a fresh SQLite DB
    at ``db_path``. Returns a small stats dict (pages/entries/toepassingen/onzeker counts).

    Refuses to overwrite an existing database that already contains human-verified entries
    (``geverifieerd=1``) unless ``force=True`` -- see module docstring."""
    json_files = sorted(transcripts_dir.glob("*.json"))
    if not json_files:
        raise FileNotFoundError(
            f"Geen transcript-JSON-bestanden gevonden in {transcripts_dir} -- "
            "zijn de transcribe-logbook-* achtergrondagents al klaar?"
        )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        if not force:
            existing = sqlite3.connect(db_path)
            try:
                n_verified = existing.execute(
                    "SELECT COUNT(*) FROM entries WHERE geverifieerd = 1"
                ).fetchone()[0]
            except sqlite3.OperationalError:
                n_verified = 0  # older schema without the column -- nothing to lose
            finally:
                existing.close()
            if n_verified > 0:
                raise RuntimeError(
                    f"{db_path} bevat {n_verified} door een mens geverifieerde entries. "
                    "Een herbouw zou dat verificatiewerk overschrijven. Roep "
                    "build_database(..., force=True) aan (of --force op de CLI) als je dit "
                    "echt wilt, of exporteer/migreer de geverifieerde rijen eerst."
                )
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    n_pages = n_entries = n_toepassingen = n_onzeker = 0
    errors: list[str] = []

    for jf in json_files:
        try:
            pages = json.loads(jf.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{jf.name}: ONGELDIGE JSON -- {exc}")
            continue
        for page in pages:
            cur = conn.execute(
                "INSERT OR IGNORE INTO pages (jaar, bestand, pagina, image_path, opmerkingen_pagina) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(page.get("jaar", "")), page.get("bestand", ""), int(page.get("pagina", 0)),
                    page.get("image_path"), page.get("opmerkingen_pagina"),
                ),
            )
            if cur.rowcount == 0:
                errors.append(f"{jf.name}: dubbele pagina overgeslagen (bestand={page.get('bestand')!r}, pagina={page.get('pagina')!r})")
                continue
            page_id = cur.lastrowid
            n_pages += 1
            for entry in page.get("entries", []):
                cur2 = conn.execute(
                    "INSERT INTO entries (page_id, datum_ruw, datum_iso, tijd, opmerkingen, onzeker, raw_transcript) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        page_id, entry.get("datum_ruw"), entry.get("datum_iso"), entry.get("tijd"),
                        entry.get("opmerkingen"), 1 if entry.get("onzeker") else 0, entry.get("raw_transcript"),
                    ),
                )
                entry_id = cur2.lastrowid
                n_entries += 1
                if entry.get("onzeker"):
                    n_onzeker += 1
                for i, toep in enumerate(entry.get("toepassingen", [])):
                    conn.execute(
                        "INSERT INTO toepassingen (entry_id, volgorde, middel, hoeveelheid) VALUES (?, ?, ?, ?)",
                        (entry_id, i, toep.get("middel"), toep.get("hoeveelheid")),
                    )
                    n_toepassingen += 1

    conn.commit()
    conn.close()
    return {
        "json_files": len(json_files), "pages": n_pages, "entries": n_entries,
        "toepassingen": n_toepassingen, "onzeker_entries": n_onzeker, "warnings": errors,
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Overwrite even if verified entries exist")
    args = parser.parse_args()

    paths = AgentPaths.orchard()
    transcripts_dir = paths.logbooks_dir / "_transcripts"
    db_path = paths.logbooks_dir / "orchard_logbook.db"
    stats = build_database(transcripts_dir, db_path, force=args.force)
    print(f"Database gebouwd: {db_path}")
    for k, v in stats.items():
        if k == "warnings":
            continue
        print(f"  {k}: {v}")
    if stats["warnings"]:
        print(f"  waarschuwingen ({len(stats['warnings'])}):")
        for w in stats["warnings"]:
            print(f"    - {w}")


if __name__ == "__main__":
    main()
