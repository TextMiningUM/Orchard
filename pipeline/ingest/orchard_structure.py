"""Pure structure logic for the document -> JSON stage (no file/network/model access).

The extractors in ``build_orchard_json.py`` (PDF / HTML / Markdown) only turn a source file
into a flat, reading-ordered list of *blocks*:

    {"kind": "heading" | "paragraph" | "list_item" | "caption" | "table" | "figure" | "furniture",
     "text": str, "page": int, "level": int (headings), ...}

Everything after that is format-independent and lives here, mirroring Auto Pilot's
``build_*_json.py`` -> ``build_rag.py`` split (``../Auto Pilot``), but with the chunk definition
moved INTO the JSON so RAG, KG and PG all consume the same, already-structured chunks:

1. ``merge_continuations``  -- a paragraph that runs over a column/page break is ONE paragraph
   (page breaks are metadata, never a boundary; Auto Pilot docs/rag_chunking_design_and_verification.md Sec 4).
2. ``build_sections``       -- heading tree -> sections (each with its ``heading_path``).
3. ``define_chunks``        -- a chunk is a structural unit (a section), never a fixed number of
   words/tokens: stub sections merge into a sibling, standalone items (numbered problem cards)
   are never touched, and only a section that is genuinely too large for one retrieval unit
   is split -- at a topic boundary when a splitter is supplied, else at paragraph boundaries.
4. Tables and figures are separated out (``tables`` / ``figures``) and never enter chunk text.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Callable

from core.text_segmentation import join_hyphenated_linebreaks

# One complete, self-contained unit on its own (one numbered "probleem" card): never split,
# never merged with a neighbour -- Auto Pilot's STANDALONE_TYPES mechanism.
STANDALONE_SECTION_TYPES: set[str] = {"probleem"}

PROSE_KINDS = ("paragraph", "list_item")
NON_PROSE_KINDS = ("table", "figure", "caption", "furniture", "footnote")

MIN_SECTION_WORDS = 30   # below this a section is a "stub" that is merged into a sibling
MAX_SECTION_WORDS = 600  # above this a section is too big to be ONE retrieval unit

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\ue000-\uf8ff\u200b-\u200d\u2060\ufeff]")  # control, private-use (Symbol-font bullets), zero-width
_SOFT_HYPHEN_BREAK_RE = re.compile(r"\u00ad\s*\n\s*")
_HYPHEN_VARIANTS_RE = re.compile(r"[\u2010\u2011\u00ad]")
_WS_RE = re.compile(r"[ \t\u00a0]+")
_TERMINAL = ".!?:;\u2026"
_NUMERIC_TOKEN_RE = re.compile(r"^[\d.,%\u00b1()/\-\u2013+<>=\u00b0]+[a-zA-Z%\u00b0]{0,3}$")


def stable_id(prefix: str, *parts) -> str:
    digest = hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{digest}"


_ENGLISH_WORDS: set[str] | None = None
_LINE_BREAK_HYPHEN_RE = re.compile(r"([^\W\d_]{2,})-\n([a-z]{2,})")


def configure_hyphenation(language: str) -> None:
    """Tell ``normalize_text`` which language the document is in. A hyphen at a line end is
    normally just a wrap ("contin-" / "ued" -> "continued"), but in English a real compound also
    breaks that way ("long-" / "distance"): when the joined word is not a dictionary word but both
    halves are, the hyphen is kept. Dutch compounds are written together, so for Dutch (and when no
    language is configured) the break is always joined."""
    global _ENGLISH_WORDS
    if language == "en":
        from spellchecker import SpellChecker
        _ENGLISH_WORDS = set(SpellChecker(language="en").word_frequency.dictionary)
    else:
        _ENGLISH_WORDS = None


def _join_line_break(m: re.Match) -> str:
    left, right = m.group(1), m.group(2)
    if (_ENGLISH_WORDS is not None and (left + right).lower() not in _ENGLISH_WORDS
            and left.lower() in _ENGLISH_WORDS and right.lower() in _ENGLISH_WORDS):
        return f"{left}-{right}"
    return left + right


def normalize_text(text: str) -> str:
    """Control characters out, hyphen-broken words rejoined, runs of whitespace (including
    line breaks inside ONE paragraph) collapsed to single spaces."""
    text = _CONTROL_RE.sub("", text or "")
    text = _SOFT_HYPHEN_BREAK_RE.sub("", text)  # a soft hyphen at a line end: the word continues
    text = _HYPHEN_VARIANTS_RE.sub("-", text)
    text = _LINE_BREAK_HYPHEN_RE.sub(_join_line_break, text)
    text = join_hyphenated_linebreaks(text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return _WS_RE.sub(" ", text).strip()


def word_count(text: str) -> int:
    return len(text.split())


def ends_sentence(text: str) -> bool:
    stripped = text.rstrip().rstrip("\"'\u201d\u2019)]")
    return bool(stripped) and stripped[-1] in _TERMINAL


def tabular_score(text: str) -> float:
    """Fraction of whitespace-separated tokens that look like table cells (numbers, ranges,
    percentages, short units). Running prose scores ~0.05, a table/spec grid > 0.4."""
    tokens = text.split()
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if _NUMERIC_TOKEN_RE.match(t)) / len(tokens)


def make_block(kind: str, text: str, page: int, **extra) -> dict:
    return {"kind": kind, "text": text, "page": page, **extra}


# ── 1. continuation across column / page breaks ─────────────────────────────────────────

def _continues(prev: str, nxt: str) -> bool:
    if not prev or not nxt:
        return False
    if prev.endswith("-") and nxt[0].islower():
        return True
    return not ends_sentence(prev) and (nxt[0].islower() or nxt[0].isdigit() and not prev.rstrip().endswith(":"))


def _join(prev: str, nxt: str) -> str:
    if prev.endswith("-") and nxt[:1].islower():
        return prev[:-1] + nxt
    return prev + " " + nxt


LOOKBACK_BLOCKS = 8  # how far back a lowercase-starting paragraph may look for the paragraph it continues


def merge_continuations(blocks: list[dict]) -> list[dict]:
    """Merges a paragraph with the one it continues. Text that flows over a column or page break
    stops mid-sentence and resumes with a lowercase word, usually right after it -- but footnotes,
    figure notes and side text can sit in between. So a paragraph that starts in lowercase attaches
    to the nearest earlier paragraph (within ``LOOKBACK_BLOCKS`` blocks, never across a heading)
    that is still open, i.e. does not end in sentence punctuation; whatever sat in between stays
    where it was. Tables, figures, captions and footnotes never interrupt; a heading or list item
    closes the paragraph."""
    out: list[dict] = []
    open_idx: int | None = None
    for block in blocks:
        kind = block["kind"]
        if kind == "paragraph":
            target = open_idx if open_idx is not None and _continues(out[open_idx]["text"], block["text"]) else None
            if target is None and block["text"][:1].islower():
                for j in range(len(out) - 1, max(-1, len(out) - 1 - LOOKBACK_BLOCKS), -1):
                    if out[j]["kind"] == "heading":
                        break
                    if out[j]["kind"] == "paragraph" and not ends_sentence(out[j]["text"]):
                        target = j
                        break
            if target is not None:
                prev = out[target]
                prev["text"] = _join(prev["text"], block["text"])
                prev["pages"] = sorted(set(prev.get("pages", [prev["page"]])) | {block["page"]})
                open_idx = target
                continue
            block = dict(block)
            block["pages"] = [block["page"]]
            out.append(block)
            open_idx = len(out) - 1
        elif kind in NON_PROSE_KINDS:
            out.append(block)
        else:
            out.append(block)
            open_idx = None
    return out


# ── 2. heading tree -> sections ─────────────────────────────────────────────────────────

def _prose_units(blocks: list[dict]) -> list[str]:
    """Paragraphs stay single units; consecutive list items form ONE unit ("- a\\n- b")."""
    units: list[str] = []
    items: list[str] = []
    for b in blocks:
        if b["kind"] == "list_item":
            items.append(b["text"] if re.match(r"^\d+[.)]\s", b["text"]) else "- " + b["text"])
            continue
        if items:
            units.append("\n".join(items))
            items = []
        if b["kind"] == "paragraph":
            units.append(b["text"])
    if items:
        units.append("\n".join(items))
    return units


def build_sections(blocks: list[dict], doc_id: str, doc_title: str) -> list[dict]:
    """Groups the reading-ordered blocks by the heading tree. Each section holds the blocks
    between its heading and the next heading of ANY level (so a parent heading followed
    directly by a sub-heading yields no empty section; it only lives on in the children's
    ``heading_path``). Block ids are assigned here, in reading order."""
    sections: list[dict] = []
    stack: list[tuple[int, str]] = []
    current: dict | None = None
    block_no = 0

    def open_section(title: str, level: int, section_type: str) -> dict:
        sec = {"title": title, "level": level, "type": section_type,
               "heading_path": [t for _, t in stack], "blocks": []}
        sections.append(sec)
        return sec

    for block in blocks:
        if block["kind"] == "heading":
            level = block.get("level", 2)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, block["text"]))
            current = open_section(block["text"], level, block.get("section_type", "prose"))
            continue
        if current is None:
            current = open_section(doc_title, 0, "prose")
        block_no += 1
        block = dict(block)
        block["block_id"] = f"{doc_id}_b{block_no}"
        current["blocks"].append(block)

    finished = []
    for i, sec in enumerate(s for s in sections if s["blocks"]):
        units = _prose_units(sec["blocks"])
        pages = sorted({p for b in sec["blocks"] for p in b.get("pages", [b["page"]])})
        sec.update(
            section_id=f"{doc_id}_s{i + 1}",
            units=units,
            text="\n\n".join(units),
            pages=pages,
            table_ids=[b["table_id"] for b in sec["blocks"] if b["kind"] == "table" and "table_id" in b],
            figure_ids=[b["figure_id"] for b in sec["blocks"] if b["kind"] == "figure" and "figure_id" in b],
        )
        finished.append(sec)
    return finished


def group_chapters(sections: list[dict], doc_title: str) -> list[dict]:
    """Chapter = the top-level heading a section lives under (or the document itself)."""
    chapters: list[dict] = []
    for sec in sections:
        title = sec["heading_path"][0] if sec["heading_path"] else doc_title
        if not chapters or chapters[-1]["title"] != title:
            chapters.append({"title": title, "section_ids": []})
        chapters[-1]["section_ids"].append(sec["section_id"])
    return chapters


# ── 3. chunk definition (structure, not length) ─────────────────────────────────────────

SplitFn = Callable[[list[str]], list[int]]


def _balanced_paragraph_split(units: list[str]) -> list[int]:
    """Fallback splitter: boundaries between paragraphs, as balanced as possible, only used
    when a section is bigger than MAX_SECTION_WORDS and no topic splitter was supplied."""
    total = sum(word_count(u) for u in units)
    parts = max(2, math.ceil(total / MAX_SECTION_WORDS))
    target = total / parts
    bounds, running = [], 0
    for i, u in enumerate(units[:-1], start=1):
        running += word_count(u)
        if running >= target * (len(bounds) + 1) and len(bounds) < parts - 1:
            bounds.append(i)
    return bounds


def chunk_flags(text: str) -> dict:
    return {
        "starts_midsentence": bool(text) and text[0].islower(),
        "ends_open": bool(text) and not ends_sentence(text.split("\n")[-1]) and not text.rstrip().endswith(")"),
        "tabular_score": round(tabular_score(text), 3),
    }


def _make_chunk(doc: dict, index: int, sections: list[dict], units: list[str], *,
                part: tuple[int, int] | None = None, semantic_split: bool = False) -> dict:
    body = "\n\n".join(units)
    path = sections[0]["heading_path"] or [doc["title"]]
    if len(sections) > 1:
        # merged stubs: keep each stub's own heading inline so the text stays self-explanatory
        body = "\n\n".join(
            (f"{s['title']}\n{s['text']}" if i else s["text"]) for i, s in enumerate(sections))
    title = sections[0]["title"] if len(sections) == 1 else " / ".join(s["title"] for s in sections)
    if part:
        title = f"{title} (deel {part[0]}/{part[1]})"
    context = f"Bron: {doc['title']}\nSectie: {' > '.join(path)}" + (f" > {title}" if title not in path else "")
    return {
        "chunk_id": stable_id("chunk", doc["doc_id"], index, body[:200]),
        "doc_id": doc["doc_id"],
        "chunk_index": index,
        "type": sections[0]["type"],
        "title": title,
        "heading_path": path,
        "section_ids": [s["section_id"] for s in sections],
        "block_ids": [b["block_id"] for s in sections for b in s["blocks"] if b["kind"] in PROSE_KINDS],
        "pages": sorted({p for s in sections for p in s["pages"]}),
        "text": body,
        "text_with_context": f"{context}\n\n{body}",
        "word_count": word_count(body),
        "table_ids": [t for s in sections for t in s["table_ids"]],
        "figure_ids": [f for s in sections for f in s["figure_ids"]],
        "merged_stubs": len(sections) > 1,
        "semantic_split": semantic_split,
        **chunk_flags(body),
    }


def define_chunks(doc: dict, sections: list[dict], split_fn: SplitFn | None = None) -> list[dict]:
    """The chunk definition stored in the JSON. One chunk per section unless:

    - the section is STANDALONE (never touched);
    - it is a stub (< MIN_SECTION_WORDS): merged with the next sibling under the same parent
      (or the previous one when it is the last), never across parents, never with a standalone;
    - it is larger than MAX_SECTION_WORDS: split at topic boundaries (``split_fn``) or, if none
      is given, at balanced paragraph boundaries.
    Sections without prose (only a table/figure) produce no chunk."""
    usable = [s for s in sections if s["units"]]
    groups: list[list[dict]] = []
    i = 0
    while i < len(usable):
        sec = usable[i]
        group = [sec]
        if sec["type"] not in STANDALONE_SECTION_TYPES and word_count(sec["text"]) < MIN_SECTION_WORDS:
            j = i + 1
            while (j < len(usable) and usable[j]["type"] not in STANDALONE_SECTION_TYPES
                   and usable[j]["heading_path"][:-1] == sec["heading_path"][:-1]
                   and word_count(" ".join(s["text"] for s in group)) < MIN_SECTION_WORDS):
                group.append(usable[j])
                j += 1
            i = j
        else:
            i += 1
        groups.append(group)

    # a trailing stub that found no following sibling joins the previous chunk's group
    merged: list[list[dict]] = []
    for group in groups:
        stub = (len(group) == 1 and group[0]["type"] not in STANDALONE_SECTION_TYPES
                and word_count(group[0]["text"]) < MIN_SECTION_WORDS)
        if (stub and merged and merged[-1][-1]["type"] not in STANDALONE_SECTION_TYPES
                and merged[-1][-1]["heading_path"][:-1] == group[0]["heading_path"][:-1]):
            merged[-1].extend(group)
        else:
            merged.append(group)

    chunks: list[dict] = []
    for group in merged:
        total_words = sum(word_count(s["text"]) for s in group)
        if len(group) == 1 and group[0]["type"] not in STANDALONE_SECTION_TYPES and total_words > MAX_SECTION_WORDS:
            units = group[0]["units"]
            bounds = (split_fn(units) if split_fn and len(units) > 1 else [])
            used_topic_split = bool(bounds)
            if not bounds and len(units) > 1:
                bounds = _balanced_paragraph_split(units)
            if bounds:
                edges = [0, *bounds, len(units)]
                pieces = [units[a:b] for a, b in zip(edges, edges[1:]) if units[a:b]]
                # a topic boundary next to a tiny paragraph must not leave a stub chunk: fold stubs
                # into the previous piece (or, for the first one, into the next)
                merged_pieces: list[list[str]] = []
                for piece in pieces:
                    if merged_pieces and word_count(" ".join(piece)) < MIN_SECTION_WORDS:
                        merged_pieces[-1].extend(piece)
                    else:
                        merged_pieces.append(list(piece))
                if len(merged_pieces) > 1 and word_count(" ".join(merged_pieces[0])) < MIN_SECTION_WORDS:
                    merged_pieces[1] = merged_pieces[0] + merged_pieces[1]
                    merged_pieces.pop(0)
                pieces = merged_pieces
                if len(pieces) > 1:
                    for n, piece in enumerate(pieces, start=1):
                        chunks.append(_make_chunk(doc, len(chunks), group, piece, part=(n, len(pieces)),
                                                  semantic_split=used_topic_split))
                    continue
        chunks.append(_make_chunk(doc, len(chunks), group, [u for s in group for u in s["units"]]))
    return chunks


# ── 4. PDF furniture (running headers / footers / page numbers) ─────────────────────────

_PAGE_NUMBER_RE = re.compile(r"^\W*(?:p(?:ag(?:ina|e)?|\.)?\s*)?\d{1,4}(?:\s*(?:/|of|van)\s*\d{1,4})?\W*$", re.I)


def _furniture_key(text: str) -> str:
    """Digits and punctuation masked: "50 AGRICULTURE HANDBOOK NO. 442" and "52 AGRICULTURE
    HANDBOOK NO. 442" are the same running header."""
    return re.sub(r"[^a-z]+", " ", text.lower()).strip()


def _similar(a: str, b: str, threshold: float = 0.85) -> bool:
    return a == b or SequenceMatcher(None, a, b).ratio() >= threshold


def is_page_number(text: str) -> bool:
    return bool(_PAGE_NUMBER_RE.match(text.strip()))


_BOILERPLATE_RE = re.compile(
    r"subsidieovereenkomst|dit project is gefinancierd|research executive agency|"
    r"project has received funding|grant agreement n|alle rechten voorbehouden|"
    r"accepteer (alle )?cookies|cookie-?(instellingen|beleid|voorkeuren)|"
    r"html public|<!doctype|^\s*\{\w+\}|\u00b7 @\w+|^\s*\d{1,2}/\d{1,2}/\d{4}\s*$|"
    r"please click here if you are not redirected|google tag manager|"
    r"vrijblijvende offerte|commentaarfunctie|disqus|zich registreren bij de|abonneer u|schrijf je in voor de nieuwsbrief",
    re.I)


def is_boilerplate_paragraph(text: str) -> bool:
    """Funding statements, cookie notices: legal/site boilerplate, not knowledge."""
    return bool(_BOILERPLATE_RE.search(text))


def find_repeating_furniture(edge_lines_per_page: list[list[str]], min_pages: int = 3,
                             min_ratio: float = 0.4) -> set[str]:
    """Keys of lines that repeat (fuzzily: OCR varies a character or two) in the top/bottom
    margin of many pages -- running headers/footers, which never belong in the text."""
    n_pages = len(edge_lines_per_page)
    if n_pages < min_pages:
        return set()
    clusters: list[tuple[str, set[int]]] = []  # (representative key, pages it occurs on)
    for page_no, lines in enumerate(edge_lines_per_page):
        for line in lines:
            key = _furniture_key(line)
            if len(key) < 6:
                continue
            for rep, pages in clusters:
                if _similar(key, rep):
                    pages.add(page_no)
                    break
            else:
                clusters.append((key, {page_no}))
    need = max(min_pages, math.ceil(min_ratio * n_pages))
    return {rep for rep, pages in clusters if len(pages) >= need}


def is_furniture(text: str, furniture_keys: set[str]) -> bool:
    if is_page_number(text):
        return True
    key = _furniture_key(text)
    return len(key) >= 6 and any(_similar(key, rep) for rep in furniture_keys)


# ── 5. heading heuristics shared by the extractors ──────────────────────────────────────

_HEADING_CHARS_RE = re.compile(r"^[A-Za-z\u00c0-\u017f0-9 \-:,&'()/]+$")


def looks_like_caps_heading(text: str) -> bool:
    """OCR'd books (the USDA handbook) have noisy font sizes, but their section headings are
    short ALL-CAPS lines ("BOTANICAL CLASSIFICATION"), not sentences. Bibliography entry titles
    ("1955. FRESH-FRUIT AND CANNING ..."), running headers and OCR garbage ("INSECTS AND MITES ^^")
    are also upper-case but are not headings."""
    text = text.strip()
    letters = [c for c in text if c.isalpha()]
    words = text.split()
    if len(letters) < 4 or not 1 <= len(words) <= 9 or len(text) > 70:
        return False
    if text.endswith((".", ",", ";", "-")) or not _HEADING_CHARS_RE.match(text):
        return False
    if re.match(r"^\d{4}\b", text) or sum(c.isdigit() for c in text) > 2:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) >= 0.9
