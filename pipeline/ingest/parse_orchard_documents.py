"""Parses every acquired Track 1 document (``manifest.json``, status acquired/already_acquired)
into normalized, page/section-level JSON -- the input ``build_orchard_rag.py`` chunks and embeds.

Separate script from ``build_orchard_corpus.py`` (which only downloads) and from
``build_orchard_rag.py`` (which only chunks/embeds) -- same three-stage split Auto Pilot uses
(acquire -> parse -> chunk/embed), so re-running any one stage never silently redoes the others.

Output: one JSON per document under ``Data/Orchard/Orchard_JSON/<doc_id>.json``::

    {
      "doc_id": "...", "title": "...", "category": "...", "language": "nl"|"en",
      "url": "...", "source_file": "<filename>",
      "pages": [{"page_num": 1, "text": "..."}, ...]
    }

Safe to run LOCALLY (pdfplumber + BeautifulSoup, CPU-only, no GPU/API key needed). Idempotent:
re-parses every acquired document each run (parsing is cheap; unlike acquisition there is no
"skip if present" check -- if the PDF text extraction logic improves, re-running should pick
that up immediately rather than silently keeping a stale JSON).

Usage::

    .venv\\Scripts\\python.exe -m pipeline.ingest.parse_orchard_documents
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from core.paths import AgentPaths  # noqa: E402

import pdfplumber  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

# Confirmed 2026-10-08 (Fase 3): this file is English despite its /NL/ URL (EUR-Lex content
# negotiation issue, see design doc Deel F point 8) -- excluded here rather than indexed under a
# false "nl" language label, which would make citations actively misleading. Re-parse once a
# genuine Dutch version is acquired (manifest note has the retry plan).
SKIP_FROM_RAG: set[str] = {"eu_reg_2018_848_organic_nl"}

# EUR-Lex's own site chrome (same for every CELEX page) -- stripped from any EUR-Lex HTML we DO
# parse in future, so a reader's actual legal text isn't buried under navigation boilerplate.
_EURLEX_BOILERPLATE_MARKERS = (
    "Skip to main content", "My EUR-Lex", "Sign in", "Quick search",
)


def _parse_pdf(path: Path) -> list[dict]:
    """Returns [{"page_num": 1, "text": "..."}, ...], one entry per non-empty page."""
    pages = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append({"page_num": i, "text": text})
    return pages


def _parse_html(path: Path) -> list[dict]:
    """Returns a single-entry page list with the visible body text, EUR-Lex nav chrome stripped
    heuristically (drops any line that is just one of the known boilerplate markers)."""
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    body = soup.find("body") or soup
    raw_lines = [ln.strip() for ln in body.get_text("\n", strip=True).split("\n")]
    lines = [ln for ln in raw_lines if ln and ln not in _EURLEX_BOILERPLATE_MARKERS]
    text = re.sub(r"\n{2,}", "\n", "\n".join(lines)).strip()
    return [{"page_num": 1, "text": text}] if text else []


def parse_document(entry: dict) -> dict | None:
    """Parses one manifest entry; returns None (with a printed reason) if it can't/shouldn't be
    parsed -- never raises, so one bad document doesn't abort the whole run."""
    if entry["id"] in SKIP_FROM_RAG:
        print(f"[skip, excluded] {entry['id']}: see SKIP_FROM_RAG / design doc Deel F")
        return None
    if entry["status"] not in ("acquired", "already_acquired"):
        print(f"[skip, not acquired] {entry['id']} (status={entry['status']})")
        return None
    path = Path(entry["file_path"])
    if not path.exists():
        print(f"[skip, file missing] {entry['id']}: {path}")
        return None

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pages = _parse_pdf(path)
    elif suffix in (".html", ".htm"):
        pages = _parse_html(path)
    else:
        print(f"[skip, unsupported type] {entry['id']}: {suffix}")
        return None

    if not pages:
        print(f"[WARNING, no extractable text] {entry['id']}: {path}")
        return None

    n_chars = sum(len(p["text"]) for p in pages)
    print(f"[parsed] {entry['id']}: {len(pages)} pages, {n_chars} chars")
    return {
        "doc_id": entry["id"], "title": entry["title"], "category": entry["category"],
        "language": entry["language"], "url": entry.get("url"), "source_file": path.name,
        "pages": pages,
    }


def main() -> None:
    paths = AgentPaths.orchard()
    manifest_path = paths.source_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    paths.json_dir.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    for entry in manifest:
        doc = parse_document(entry)
        if doc is None:
            continue
        out_path = paths.json_dir / f"{doc['doc_id']}.json"
        out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        n_ok += 1
    print(f"\n{n_ok} document(en) geparsed naar {paths.json_dir}")


if __name__ == "__main__":
    main()
