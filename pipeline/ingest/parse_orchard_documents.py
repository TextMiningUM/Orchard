"""Parses every acquired Track 1 document (``manifest.json``, status acquired/already_acquired)
into normalized, SECTION-level JSON -- the input ``build_orchard_rag.py`` chunks and embeds.

Mirrors Auto Pilot's own three-stage split (acquire -> parse -> chunk/embed) AND its JSON
*shape*: each document becomes a flat list of ``sections`` (not raw per-page text) -- a
"section" is the natural structural unit of that document (one PDF page's worth of running
prose, or -- for a hand-curated markdown knowledge doc with a repeating "**N. Titel**" pattern
-- ONE discrete, numbered item). Each section carries a ``type``: plain ``"prose"`` sections may
still be split/merged further downstream by ``build_orchard_rag.py``'s topic-boundary logic,
while a structurally-complete unit (``"probleem"``) is marked STANDALONE and is NEVER split or
merged with a neighbour -- exactly Auto Pilot's STANDALONE_TYPES mechanism (its own "rule"/
"chirp_report"/... section types), ported rather than re-derived.

Separate script from ``build_orchard_corpus.py`` (which only downloads) and from
``build_orchard_rag.py`` (which only chunks/embeds), so re-running any one stage never silently
redoes the others.

Output: one JSON per document under ``Data/Orchard/Orchard_JSON/<doc_id>.json``::

    {
      "doc_id": "...", "title": "...", "category": "...", "language": "nl"|"en",
      "url": "...", "source_file": "<filename>",
      "sections": [
        {"section_id": "...", "title": "...", "type": "prose"|"probleem",
         "text": "...", "pages": [1]},
        ...
      ]
    }

Safe to run LOCALLY (PyMuPDF + BeautifulSoup, CPU-only, no GPU/API key needed). Idempotent:
re-parses every acquired document each run (parsing is cheap; unlike acquisition there is no
"skip if present" check -- if the extraction logic improves, re-running picks that up
immediately rather than silently keeping a stale JSON).

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
from core.text_segmentation import join_hyphenated_linebreaks  # noqa: E402

import pymupdf  # noqa: E402
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

# PyMuPDF, NOT pdfplumber (fixed 2026-10-09, design doc Deel F #13/G.17) -- pdfplumber's
# extract_text() sorts words primarily by vertical position across the FULL page width, which
# interleaves a narrative column with an adjacent product/spec sidebar line-by-line into
# semantically-broken text (confirmed directly in the Netafim adviesrapport and a BIOFRUITNET
# factsheet's sidebar table). Auto Pilot (../Auto Pilot) hit and fixed the EXACT same problem
# for its 2-column CHIRP newsletters/Navy yearbooks: switching to PyMuPDF's own
# ``page.get_text("text")`` (NOT ``sort=True`` -- that mode interleaved even MORE aggressively
# for them) follows the PDF's content-stream block order instead, which reads one column fully
# before the next for every multi-column document tested there. Applying the same proven fix
# here rather than re-deriving a column-detection approach from scratch.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b-\x1f]")  # non-printable font/ligature artifacts

# A section whose text is a structurally-complete, self-contained unit on its own (here: one
# numbered "probleem" from a curated markdown doc) -- NEVER split by topic-boundary detection
# or merged with a neighbouring section in build_orchard_rag.py, regardless of its own token
# count. Mirrors Auto Pilot's STANDALONE_TYPES set exactly (its "rule"/"chirp_report"/
# "moos_case" -- one complete logical unit per chunk, always).
STANDALONE_SECTION_TYPES: set[str] = {"probleem"}


def _parse_pdf(path: Path) -> list[dict]:
    """Returns one ``"prose"`` section per non-empty page -- the natural structural unit for a
    PDF (a page boundary), left to build_orchard_rag.py's topic-boundary/merge logic to reshape
    into actual retrieval chunks."""
    sections = []
    with pymupdf.open(path) as pdf:
        for i, page in enumerate(pdf, start=1):
            raw = _CONTROL_CHAR_RE.sub("", page.get_text("text") or "")
            text = join_hyphenated_linebreaks(raw).strip()
            if text:
                sections.append({"title": None, "type": "prose", "text": text, "pages": [i]})
    return sections


def _parse_html(path: Path) -> list[dict]:
    """Returns a single ``"prose"`` section with the visible body text, EUR-Lex nav chrome
    stripped heuristically (drops any line that is just one of the known boilerplate markers).
    HTML has no natural "page" concept, so this is always exactly one section."""
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    body = soup.find("body") or soup
    raw_lines = [ln.strip() for ln in body.get_text("\n", strip=True).split("\n")]
    lines = [ln for ln in raw_lines if ln and ln not in _EURLEX_BOILERPLATE_MARKERS]
    text = re.sub(r"\n{2,}", "\n", "\n".join(lines)).strip()
    return [{"title": None, "type": "prose", "text": text, "pages": [1]}] if text else []


_MD_H2_RE = re.compile(r"^##\s+(.*)$", re.MULTILINE)
# A hand-curated, numbered knowledge item: "**123. Titel van het probleem**" on its own line
# (always preceded by a blank line in every source file seen so far -- a markdown renderer
# would show it as its own paragraph). Deliberately requires the trailing "**" on the SAME
# line (not DOTALL) so an incidental "**bold phrase**" inside a sentence is never mistaken for
# a genuine numbered item header.
_MD_NUMBERED_ITEM_RE = re.compile(r"^\*\*(\d+)\.\s+(.+?)\*\*\s*$", re.MULTILINE)
_MIN_NUMBERED_ITEMS_FOR_STRUCTURAL_SPLIT = 3  # a couple of incidental bold "**N. ...**"-looking
# lines shouldn't be mistaken for a genuinely itemized document -- require a real run of them.


def _split_numbered_items(text: str) -> list[dict] | None:
    """If `text` contains a genuine run of "**N. Titel**"-style numbered items, returns one
    STANDALONE ``"probleem"`` section per item (from this item's own header up to, but not
    including, the next item's header) -- each item's own sources/citations can then never end
    up merged into or split across a DIFFERENT item's chunk. Returns None if there's no such
    structural pattern (fewer than `_MIN_NUMBERED_ITEMS_FOR_STRUCTURAL_SPLIT` matches), meaning
    "treat this normally" (the caller falls back to ordinary prose handling)."""
    matches = list(_MD_NUMBERED_ITEM_RE.finditer(text))
    if len(matches) < _MIN_NUMBERED_ITEMS_FOR_STRUCTURAL_SPLIT:
        return None
    sections = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        item_text = text[start:end].strip()
        if item_text:
            sections.append({
                "title": f"{m.group(1)}. {m.group(2).strip()}", "type": "probleem",
                "text": item_text, "pages": [],  # filled in by the caller with the H2 group index
            })
    return sections


def _parse_markdown(path: Path) -> list[dict]:
    """Splits on level-2 markdown headings ("## ...") first -- the natural top-level section
    boundary in a hand-written/curated markdown knowledge doc (e.g. `internet_crawl/Kersenteelt
    100 problemen door het jaar heen.md`'s ten "## N. <groep>"-secties). WITHIN each such group,
    if it contains a genuine run of numbered "**N. Titel**" items (Observatie/Actie/Gevolg/
    Waarom/Slechtste-reactie + per-item bronvermelding), each becomes its own STANDALONE
    `"probleem"` section -- never split or merged downstream, so a problem's own sources can
    never drift onto a NEIGHBOURING problem. A group with no such pattern (e.g. the intro
    "Leeswijzer") stays one ordinary `"prose"` section. Falls back to a single prose section if
    there are no H2 headings at all (a short/flat markdown file)."""
    text = _CONTROL_CHAR_RE.sub("", path.read_text(encoding="utf-8", errors="replace"))
    h2_matches = list(_MD_H2_RE.finditer(text))
    if not h2_matches:
        stripped = text.strip()
        return [{"title": None, "type": "prose", "text": stripped, "pages": [1]}] if stripped else []

    sections: list[dict] = []
    for group_idx, m in enumerate(h2_matches, start=1):
        start = m.start()
        end = h2_matches[group_idx].start() if group_idx < len(h2_matches) else len(text)
        group_text = text[start:end].strip()
        if not group_text:
            continue
        items = _split_numbered_items(group_text)
        if items is not None:
            for item in items:
                item["pages"] = [group_idx]
            sections.extend(items)
        else:
            sections.append({
                "title": m.group(1).strip(), "type": "prose", "text": group_text,
                "pages": [group_idx],
            })
    return sections


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
        raw_sections = _parse_pdf(path)
    elif suffix in (".html", ".htm"):
        raw_sections = _parse_html(path)
    elif suffix == ".md":
        raw_sections = _parse_markdown(path)
    else:
        print(f"[skip, unsupported type] {entry['id']}: {suffix}")
        return None

    if not raw_sections:
        print(f"[WARNING, no extractable text] {entry['id']}: {path}")
        return None

    doc_id = entry["id"]
    sections = [
        {"section_id": f"{doc_id}_s{i + 1}", **s}
        for i, s in enumerate(raw_sections)
    ]
    n_standalone = sum(1 for s in sections if s["type"] in STANDALONE_SECTION_TYPES)
    n_chars = sum(len(s["text"]) for s in sections)
    extra = f", waarvan {n_standalone} genummerde items" if n_standalone else ""
    print(f"[parsed] {doc_id}: {len(sections)} secties{extra}, {n_chars} chars")
    return {
        "doc_id": doc_id, "title": entry["title"], "category": entry["category"],
        "language": entry["language"], "url": entry.get("url"), "source_file": path.name,
        "sections": sections,
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
