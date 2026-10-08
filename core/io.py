"""Tiny I/O helpers shared by every build/train/eval script in this project.

Direct, trimmed port of Auto Pilot's `core/io.py` -- only the pieces Orchard actually
needs so far (``.env`` loading for the Qwen remote client, JSONL helpers for the
upcoming Track 1/Track 2 dataset builders). Add more functions here as needed rather
than re-implementing them per-script.
"""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path
from typing import Iterator


def load_env(path: Path) -> None:
    """Minimal .env loader: sets os.environ from KEY=VALUE lines, never overwriting existing vars."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_jsonl(path: Path) -> Iterator[dict]:
    """Yield one dict per non-empty line of a JSONL file. Skips malformed lines."""
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  [load_jsonl] skipping malformed line in {path.name}: {e}", file=sys.stderr)
                continue


def load_jsonl_rows_capped(path: Path, max_rows: int | None, seed: int = 0) -> list[dict]:
    """Load a JSONL file into a list of dicts, deterministically subsampled down to at
    most `max_rows` (random.Random(seed).sample, so repeated loads of an unchanged file
    are stable) when the file has more rows than that. `max_rows=None` loads everything.
    Returns [] if `path` doesn't exist."""
    if not path.exists():
        return []
    rows = list(load_jsonl(path))
    if max_rows is not None and len(rows) > max_rows:
        rows = random.Random(seed).sample(rows, max_rows)
    return rows


def safe_write_jsonl(rows: list[dict], path: Path, *, overwrite: bool = False) -> None:
    """Writes `rows` as JSONL to `path`, refusing to silently clobber an existing file
    unless `overwrite=True`."""
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"{path} already exists -- refusing to overwrite without overwrite=True."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
