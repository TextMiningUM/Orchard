"""Source documents (PDF / HTML / Markdown) -> ONE structured JSON per document -- the single
input for RAG, KG and PG (design doc Deel B; Auto Pilot's ``build_*_json.py`` stage, but with
the chunk definition stored in the JSON itself).

Pipeline per document::

    extractor (format specific)  ->  reading-ordered blocks
        heading / paragraph / list_item / caption / table / figure
    orchard_structure (format independent)
        merge_continuations  -> sections (heading tree) -> chunks (structure, not length)

What the JSON guarantees (and the tests / quality report verify):

- text that runs over a column or page break is ONE paragraph (page = metadata only);
- running headers/footers/page numbers, navigation menus, cookie banners are dropped;
- tables and figures never enter chunk text: they live in ``tables`` / ``figures`` (with caption
  and the section they belong to) and chunks only reference them by id;
- a chunk is a structural unit (a section / a numbered card), never a fixed number of words.

Output: ``Data/Orchard/Orchard_JSON/<doc_id>.json``::

    {"doc_id", "title", "category", "language", "url", "source_file", "source_type",
     "chapters": [{"title", "section_ids"}],
     "sections": [{"section_id", "title", "level", "type", "heading_path", "pages", "text",
                   "blocks": [...], "table_ids", "figure_ids"}],
     "tables":  [{"table_id", "section_id", "page", "caption", "rows", "text"}],
     "figures": [{"figure_id", "section_id", "page", "caption", "text"}],
     "chunks":  [{"chunk_id", "type", "title", "heading_path", "section_ids", "pages", "text",
                  "text_with_context", "word_count", "table_ids", "figure_ids", "<flags>"}],
     "quality": {...}, "parsing_notes": [...]}

Safe to run locally (PyMuPDF + BeautifulSoup, CPU). Usage::

    .venv\\Scripts\\python.exe -m pipeline.ingest.build_orchard_json            # all documents
    .venv\\Scripts\\python.exe -m pipeline.ingest.build_orchard_json --only bayer_monilia_vruchtrot
    .venv\\Scripts\\python.exe -m pipeline.ingest.build_orchard_json --no-semantic-split
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pymupdf  # noqa: E402
from bs4 import BeautifulSoup, Comment, NavigableString, Tag  # noqa: E402

from core.paths import AgentPaths  # noqa: E402
from pipeline.ingest.orchard_structure import (  # noqa: E402
    build_sections, configure_hyphenation, define_chunks, ends_sentence, find_repeating_furniture, group_chapters,
    is_boilerplate_paragraph, is_furniture, NON_PROSE_KINDS,
    looks_like_caps_heading, make_block, merge_continuations, normalize_text, tabular_score, word_count,
)

# Confirmed 2026-10-08: English text behind a /NL/ URL (EUR-Lex content negotiation, design doc
# Deel F #8) -- excluded rather than indexed under a false "nl" label.
SKIP_FROM_RAG: set[str] = {"eu_reg_2018_848_organic_nl"}

# Per-document override of the PDF heading strategy ("font" | "caps"); otherwise auto-detected.
PDF_PROFILE_OVERRIDES: dict[str, str] = {}

_CAPTION_RE = re.compile(
    r"^(?:[A-Z]{1,3}-?\d{2,6}\s+)?(figuur|figure|fig\.|afbeelding|foto|tabel|table|grafiek|graph|chart|schema)\s*"
    r"[\dIVX]+\s*[.:\u2014\u2013-]", re.I)
_BULLET_ONLY_RE = re.compile(r"^\s*[\u2022\u25aa\u25cf\u25e6\u2013\u2014\-*\u00b7\u25ba]\s+")
_NUMBERED_RE = re.compile(r"^\d{1,2}[.)]\s+\S")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_MD_NUMBERED_ITEM_RE = re.compile(r"^\*\*(\d+)\.\s+(.+?)\*\*\s*$")
_MIN_NUMBERED_ITEMS = 3  # a couple of incidental bold "**N. ..**" lines must not become cards

_HTML_DROP_TAGS = ["script", "style", "noscript", "svg", "iframe", "form", "button", "template", "select"]
_HTML_JUNK_ATTR_RE = re.compile(
    r"cookie|consent|gdpr|breadcrumb|sidebar|share|social|newsletter|popup|modal|"
    r"comment|widget|searchform|winkelwagen|minicart|skip-link|toolbar", re.I)
_HTML_BOILERPLATE_RE = re.compile(
    r"^(lees meer|meer informatie|meer lezen|deel (dit|deze)|delen|print|pagina afdrukken|afdrukken|terug$|"
    r"volg ons|inloggen|aanmelden|"
    r"zoeken|home|menu|terug naar|ga naar|naar boven|\u00a9|copyright|alle rechten|privacy|cookie|"
    r"disclaimer|sitemap|in winkelwagen|toevoegen aan|skip to|bestel nu|abonneer)", re.I)


# ── helpers ─────────────────────────────────────────────────────────────────────────────

def resolve_source_path(entry: dict, source_dir: Path) -> Path:
    """The manifest's ``file_path`` is an absolute path from whatever machine acquired the file
    (guideline: never trust a stored absolute path). Keep everything after the
    ``OrchardKnowledge`` marker and re-root it under THIS machine's source dir."""
    raw = str(entry["file_path"]).replace("\\", "/")
    marker = "OrchardKnowledge/"
    tail = raw.split(marker, 1)[1] if marker in raw else f"{entry['category']}/{Path(raw).name}"
    return source_dir / tail


def _rows_to_text(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(row) for row in rows)


def _clean_rows(rows: list[list]) -> list[list[str]]:
    cleaned = [[normalize_text(str(c)) if c is not None else "" for c in row] for row in rows]
    return [r for r in cleaned if any(r)]


def _strip_md(text: str) -> tuple[str, list[str]]:
    """Markdown emphasis and ``[label](url)`` links -> plain text; the URLs are returned
    separately (kept as citation metadata instead of embedded noise)."""
    urls = [m.group(2) for m in _MD_LINK_RE.finditer(text)]
    text = _MD_LINK_RE.sub(r"\1", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    return text.replace("**", "").strip(), urls


class Extraction:
    """What an extractor hands to ``build_document``: reading-ordered blocks plus notes."""

    def __init__(self, blocks: list[dict], notes: list[str] | None = None):
        self.blocks = blocks
        self.notes = notes or []


# ── PDF ─────────────────────────────────────────────────────────────────────────────────

def _inside(bbox, region, margin: float = 2.0) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return region[0] - margin <= cx <= region[2] + margin and region[1] - margin <= cy <= region[3] + margin


def _overlap_ratio(a, b) -> float:
    """Share of rectangle ``a`` that lies inside rectangle ``b``."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    area = (a[2] - a[0]) * (a[3] - a[1])
    return (w * h) / area if w > 0 and h > 0 and area else 0.0


def _page_tables(page) -> list[dict]:
    out = []
    try:
        found = page.find_tables().tables
    except Exception:  # noqa: BLE001 -- table detection is best effort, never fatal
        return out
    for t in found:
        rows = _clean_rows(t.extract())
        n_cols = max((len(r) for r in rows), default=0)
        cells = [c for r in rows for c in r]
        if len(rows) < 2 or n_cols < 2 or not cells:
            continue
        non_empty = sum(1 for c in cells if c)
        # merged / row-spanning cells leave many empty cells: only reject grids that are mostly empty
        if non_empty / len(cells) < 0.2 or non_empty < 4:
            continue
        out.append({"bbox": tuple(t.bbox), "rows": rows})
    return out


def _page_figures(page, table_bboxes: list[tuple]) -> list[tuple]:
    """Image / vector-graphic regions that are NOT tables and NOT the full-page scan
    background of an OCR'd book."""
    page_area = page.rect.width * page.rect.height
    regions: list[tuple] = []
    try:
        for info in page.get_image_info():
            x0, y0, x1, y1 = info["bbox"]
            area = (x1 - x0) * (y1 - y0)
            if 0.015 * page_area <= area <= 0.7 * page_area and (x1 - x0) > 50 and (y1 - y0) > 50:
                regions.append((x0, y0, x1, y1))
    except Exception:  # noqa: BLE001
        pass
    try:
        for r in page.cluster_drawings():
            if r.width * r.height >= 0.03 * page_area and r.width > 60 and r.height > 40:
                regions.append((r.x0, r.y0, r.x1, r.y1))
    except Exception:  # noqa: BLE001
        pass
    return [r for r in regions if not any(_overlap_ratio(r, t) > 0.5 or _overlap_ratio(t, r) > 0.5
                                           for t in table_bboxes)]


def _detect_pdf_profile(line_sizes: list[tuple[float, int]]) -> tuple[str, float]:
    """("font" | "caps", body_size). OCR'd scans carry per-line font sizes that are pure noise
    (the USDA handbook ranges 13-25pt for body text), so size-based heading detection only works
    on born-digital PDFs; for scans headings are ALL-CAPS lines instead."""
    if not line_sizes:
        return "font", 10.0
    expanded = sorted(s for s, n in line_sizes for _ in range(min(n, 200)))
    body = expanded[len(expanded) // 2]
    p10, p90 = expanded[len(expanded) // 10], expanded[(9 * len(expanded)) // 10]
    return ("caps" if (p90 - p10) / body > 0.35 else "font"), body


def _estimate_body_size(pages_raw: list[dict], fallback: float) -> float:
    """Body text size = the size carrying most characters among multi-line text blocks (running
    prose), ignoring text inside tables and figures and short lines (captions, table cells, labels).
    A plain median over all lines is skewed by small print and would make every 11pt body line look
    like a heading."""
    weights: Counter[float] = Counter()
    for pg in pages_raw:
        for rb in pg["blocks"]:
            if rb["edge"] or len(rb["lines"]) < 3:
                continue
            if any(_inside(rb["bbox"], t["bbox"]) for t in pg["tables"]) or \
                    any(_inside(rb["bbox"], f) for f in pg["figures"]):
                continue
            for ln in rb["lines"]:
                if len(ln["text"]) >= 25:
                    weights[round(ln["size"] * 2) / 2] += len(ln["text"])
    return max(weights, key=weights.get) if weights else fallback


def _is_symbol_font(font: str) -> bool:
    return any(k in font.lower() for k in ("wingdings", "symbol", "zapfdingbats"))


def _merge_inline_blocks(blocks: list[dict]) -> list[dict]:
    """PyMuPDF sometimes closes a block in the middle of a visual line (a bullet glyph set as an
    image, an inline font switch): the remainder starts to the right of the previous block on the
    same baseline and continues in lowercase. Those fragments are re-attached to the line they
    belong to; otherwise they surface as a paragraph that starts mid-sentence."""
    out: list[dict] = []
    for b in blocks:
        if out:
            prev = out[-1]
            last, first = prev["lines"][-1], b["lines"][0]
            lead = first["text"].lstrip()[:1]
            starts_cont = lead.islower() or "\ue000" <= lead <= "\uf8ff"
            top, bottom = max(last["bbox"][1], first["bbox"][1]), min(last["bbox"][3], first["bbox"][3])
            height = min(last["bbox"][3] - last["bbox"][1], first["bbox"][3] - first["bbox"][1]) or 1.0
            if starts_cont and (bottom - top) / height >= 0.5 and first["bbox"][0] >= last["bbox"][2] - 3:
                last = dict(last)
                last["text"] = last["text"].rstrip() + " " + re.sub(r"^[\ue000-\uf8ff\s]+", "", first["text"])
                last["bbox"] = (last["bbox"][0], min(last["bbox"][1], first["bbox"][1]),
                                max(last["bbox"][2], first["bbox"][2]), max(last["bbox"][3], first["bbox"][3]))
                prev = {**prev, "lines": [*prev["lines"][:-1], last, *b["lines"][1:]],
                        "bbox": (min(prev["bbox"][0], b["bbox"][0]), prev["bbox"][1],
                                 max(prev["bbox"][2], b["bbox"][2]), max(prev["bbox"][3], b["bbox"][3]))}
                out[-1] = prev
                continue
        out.append(b)
    return out


def _merge_drop_caps(lines: list[dict]) -> list[dict]:
    """A drop cap ("T" set in 44pt before "he distribution, density ...") is a line of its own;
    it belongs to the start of the next line. (Done before visual-line merging, which would
    otherwise join the two with a space and leave "T he".)"""
    out: list[dict] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        letter = ln["text"].strip()
        if len(letter) == 1 and letter.isalpha() and i + 1 < len(lines) and ln["size"] >= 1.8 * lines[i + 1]["size"]:
            nxt = dict(lines[i + 1])
            nxt["text"] = letter + nxt["text"].lstrip()
            nxt["bbox"] = (min(ln["bbox"][0], nxt["bbox"][0]), nxt["bbox"][1], nxt["bbox"][2], nxt["bbox"][3])
            out.append(nxt)
            i += 2
            continue
        out.append(ln)
        i += 1
    return out


def _merge_visual_lines(lines: list[dict]) -> list[dict]:
    """PyMuPDF sometimes splits ONE visual line into several line objects (a Symbol-font
    bullet glyph, a font change): lines that share (most of) their vertical extent are joined."""
    merged: list[dict] = []
    for ln in lines:
        if merged:
            prev = merged[-1]
            top, bottom = max(prev["bbox"][1], ln["bbox"][1]), min(prev["bbox"][3], ln["bbox"][3])
            smaller = min(prev["bbox"][3] - prev["bbox"][1], ln["bbox"][3] - ln["bbox"][1]) or 1.0
            # same visual line = shared vertical extent AND the later piece continues to the RIGHT
            # (OCR line boxes overlap vertically on scans; those must stay separate lines)
            if (bottom - top) / smaller >= 0.5 and ln["bbox"][0] >= prev["bbox"][2] - 3:
                prev["spans"] += ln["spans"]
                prev["text"] = prev["text"] + " " + ln["text"]
                prev["size"] = max(prev["size"], ln["size"])
                prev["bold"] = prev["bold"] and ln["bold"]
                prev["bbox"] = (prev["bbox"][0], min(prev["bbox"][1], ln["bbox"][1]),
                                max(prev["bbox"][2], ln["bbox"][2]), max(prev["bbox"][3], ln["bbox"][3]))
                continue
        merged.append(dict(ln))
    return merged


def _is_bold_span(s: dict) -> bool:
    return bool(s["flags"] & 16) or "bold" in s["font"].lower()


def extract_pdf(path: Path, doc_id: str) -> Extraction:
    doc = pymupdf.open(path)
    pages_raw: list[dict] = []
    line_sizes: list[tuple[float, int]] = []
    edge_lines: list[list[str]] = []
    scanned_pages = 0

    for pno, page in enumerate(doc, start=1):
        height = page.rect.height
        page_area = page.rect.width * height
        try:
            if any((i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]) >= 0.7 * page_area
                   for i in page.get_image_info()):
                scanned_pages += 1
        except Exception:  # noqa: BLE001
            pass
        tables = _page_tables(page)
        figures = _page_figures(page, [t["bbox"] for t in tables])
        raw_blocks, edges = [], []
        for b in page.get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            lines = []
            for ln in b["lines"]:
                spans = [{"text": s["text"], "size": s["size"], "bold": _is_bold_span(s)} for s in ln["spans"]]
                # bullets set in a symbol font (Wingdings "n-with-bar" etc.) are glyph codes, not text
                text = "".join("\u2022 " if _is_symbol_font(s["font"]) and s["text"].strip() else s["text"]
                               for s in ln["spans"])
                if not normalize_text(text):
                    continue
                kept = [s for s in spans if normalize_text(s["text"])]
                lines.append({"text": text, "size": max(s["size"] for s in kept),
                              "bold": all(s["bold"] for s in kept), "bbox": tuple(ln["bbox"]), "spans": spans})
            lines = _merge_visual_lines(_merge_drop_caps(lines))
            for ln in lines:
                line_sizes.append((ln["size"], len(ln["text"])))
            if not lines:
                continue
            bbox = b["bbox"]
            in_edge = bbox[3] < 0.10 * height or bbox[1] > 0.90 * height
            if in_edge:
                edges.append(normalize_text(" ".join(l["text"] for l in lines)))
            raw_blocks.append({"bbox": bbox, "lines": lines, "edge": in_edge, "page_h": height})
        edge_lines.append(edges)
        pages_raw.append({"page": pno, "blocks": raw_blocks, "tables": tables, "figures": figures,
                          "width": page.rect.width})

    if not line_sizes:
        return Extraction([], ["scanned_pdf_ocr_needed"])
    _, fallback_body = _detect_pdf_profile(line_sizes)
    body = _estimate_body_size(pages_raw, fallback_body)
    profile = "caps" if scanned_pages / max(1, len(doc)) > 0.5 else "font"
    profile = PDF_PROFILE_OVERRIDES.get(doc_id, profile)
    notes = [f"pdf_profile={profile} body_size={body:.1f} pages={len(doc)} scanned_pages={scanned_pages}"]
    furniture = find_repeating_furniture(edge_lines)

    blocks: list[dict] = []
    for pg in pages_raw:
        pno = pg["page"]
        text_blocks: list[dict] = []
        figure_text: dict[tuple, list[str]] = {}
        page_blocks = _order_by_columns(pg["blocks"], pg["width"]) if profile == "caps" else pg["blocks"]
        page_blocks = _merge_inline_blocks([rb for rb in page_blocks
                                            if not any(_inside(rb["bbox"], t["bbox"]) for t in pg["tables"])
                                            and not any(_inside(rb["bbox"], f) for f in pg["figures"])])
        for rb in page_blocks:
            if any(_inside(rb["bbox"], t["bbox"]) for t in pg["tables"]):
                continue
            joined = normalize_text(" ".join(l["text"] for l in rb["lines"]))
            if sum(c.isalpha() for c in joined) < 3 or (rb["edge"] and is_furniture(joined, furniture)):
                continue  # OCR specks ("V", "-j-,") and running headers/footers
            if _is_ocr_junk(joined):
                continue
            fig = next((f for f in pg["figures"] if _inside(rb["bbox"], f)), None)
            if fig is not None:
                figure_text.setdefault(fig, []).append(joined)
                continue
            classified = _classify_pdf_block(rb, pno, profile, body)
            for cb in classified:
                cb["x"], cb["y1"] = rb["bbox"][0], rb["bbox"][3]
            text_blocks.extend(classified)
        text_blocks = _fold_caption_continuations(text_blocks)
        blocks.extend(_interleave_visuals(text_blocks, pg, figure_text))
    if profile == "caps":
        blocks = _group_table_zones(blocks)
    return Extraction(blocks, notes)


def _order_by_columns(blocks: list[dict], width: float) -> list[dict]:
    """Reading order for two-column scanned pages. The OCR engine emits blocks in "top band first"
    order, so the lower half of the left column comes AFTER the whole top of the right column and
    a sentence that flows from the bottom of the left column to the top of the right one is torn
    apart. On a page with two real columns the order is made explicit: full-width blocks (titles,
    headers) split the page into bands; inside a band the left column is read top to bottom, then
    the right one. Pages that are not two-column keep the engine's order."""
    mid = width / 2
    left = [b for b in blocks if b["bbox"][2] <= mid + 8 and b["bbox"][2] - b["bbox"][0] > 0.2 * width]
    right = [b for b in blocks if b["bbox"][0] >= mid - 8 and b["bbox"][2] - b["bbox"][0] > 0.2 * width]
    if len(left) < 3 or len(right) < 3:
        return blocks
    out: list[dict] = []
    band: dict[str, list[dict]] = {"L": [], "R": []}

    def flush() -> None:
        for side in ("L", "R"):
            out.extend(sorted(band[side], key=lambda b: b["bbox"][1]))
            band[side] = []

    for b in sorted(blocks, key=lambda b: b["bbox"][1]):
        w = b["bbox"][2] - b["bbox"][0]
        if w > 0.6 * width or (b["bbox"][0] < mid - 15 and b["bbox"][2] > mid + 15):
            flush()  # full-width block, or one that straddles the gutter (a centred heading)
            out.append(b)
        else:
            band["L" if (b["bbox"][0] + b["bbox"][2]) / 2 < mid else "R"].append(b)
    flush()
    return out


def _fold_caption_continuations(blocks: list[dict]) -> list[dict]:
    """A figure caption is often set over several OCR blocks ("FIGURE 5.--Overgrowth ... / variety.
    Such overgrowth ... / pointed out by the arrow."). The later lines are not body text: they are
    vertically adjacent to the caption, share its left edge, and the caption has not yet ended. Left
    unfolded they look like a paragraph that starts mid-sentence AND they cut the real paragraph
    that flows around the figure in two."""
    out: list[dict] = []
    open_caption: dict | None = None
    for b in blocks:
        if open_caption is not None and b["kind"] == "paragraph" and "x" in b:
            adjacent = (abs(b["x"] - open_caption["x"]) <= 14 and -14 <= b["y"] - open_caption["y1"] <= 12
                        and word_count(b["text"]) <= 45)
            unfinished = not ends_sentence(open_caption["text"]) or not (b["text"][:1].isupper())
            if adjacent and unfinished:
                open_caption["text"] += " " + b["text"]
                open_caption["y1"] = b["y1"]
                continue
        open_caption = b if b["kind"] == "caption" and "x" in b else None
        out.append(b)
    return out


_OCR_OPEN_QUOTE_RE = re.compile(r"(?<![\w'])[\^*\u25a0](?=[A-Z][A-Za-z\-]{2,}['\\\u2019\"])")
_OCR_CLOSE_QUOTE_RE = re.compile(r"(?<=[A-Za-z])\\(?=[\s,.;)]|$)")
_FOOTNOTE_RE = re.compile(r"^[\^*\u2020\u2021]\s?[A-Z][a-z]")
_FOOTNOTE_MARK_RE = re.compile(r"^(?:[\^*\"'\u2020\u2021\-\u2013]{1,3}|\d)\s+[A-Z][a-z]")  # OCR'd footnote marker + space
_CAPTION_START_RE = re.compile(r"^(?:[A-Z]{1,3}-?\d{2,6}\s+)?(figure|fig\.|figuur)\s*[\dIVX]+\s*[.:\u2014\u2013-]", re.I)
_INLINE_CAPTION_RE = re.compile(r"(?<=\s)(?=(?:FIGURE|Figure)\s*\d+\s*[.:\u2014\u2013-])")
_RATING_DOTS_RE = re.compile(r"\u2022{2,}|\u2022 \u2022")  # variety tables rate traits with "•••"
_PHOTO_ID_RE = re.compile(r"\b[A-Z]{1,3}-\d{3,5}\b\s*")  # "PN-3067": the photo's catalogue number
_TABLE_CAPTION_RE = re.compile(r"^(?:[A-Z]{1,3}-?\d{2,6}\s+)?(table|tabel)\s*[\dIVX]+\s*[.:\u2014\u2013-]", re.I)


def _clean_ocr_quotes(text: str) -> str:
    """Scanned cultivar names come out as ``*Corum'`` / ``^SPALDING\\``: the quote marks are
    misread. Only this narrow, unambiguous pattern is repaired (name between a stray symbol and a
    closing quote/backslash); digits and ordinary words are never touched."""
    return _PHOTO_ID_RE.sub("", _OCR_CLOSE_QUOTE_RE.sub("'", _OCR_OPEN_QUOTE_RE.sub("'", text)))


def _is_ocr_junk(text: str) -> bool:
    """Rotated or speckled text the OCR turned into a handful of 1-2 letter tokens ("> u td O o")."""
    words = text.split()
    return 0 < len(words) <= 8 and sum(len(w.strip("^*'\".,;:") ) <= 2 for w in words) / len(words) >= 0.6 \
        and not ends_sentence(text)


def _group_table_zones(blocks: list[dict]) -> list[dict]:
    """Scanned books have no ruled tables, so ``find_tables`` finds nothing and a table leaks into
    the prose as caption + header fragments + number rows + footnotes. A ``TABLE n`` caption opens
    a table zone: its continuation line, the short header fragments, the number rows and the
    footnotes all become ONE ``table`` block (caption kept separately); the zone ends at the first
    block that reads as running prose."""
    out: list[dict] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b["kind"] != "caption" or not _TABLE_CAPTION_RE.match(b["text"]):
            out.append(b)
            i += 1
            continue
        caption = b["text"]
        rows: list[str] = []
        j = i + 1
        first = True
        while j < len(blocks):
            nb = blocks[j]
            if nb["kind"] == "table":
                rows.append(nb["text"])
            elif nb["kind"] == "paragraph":
                text, n = nb["text"], word_count(nb["text"])
                if first and not caption.rstrip().endswith((".", "?")) and (text[:1].islower() or n < 40):
                    caption += " " + text  # the caption's own second line
                elif _FOOTNOTE_RE.match(text) and n <= 70 or n < 12 and not ends_sentence(text):
                    rows.append(text)
                else:
                    break
            elif nb["kind"] == "figure":
                pass
            else:
                break
            first = False
            j += 1
        out.append({**b, "text": caption})
        if rows:
            out.append(make_block("table", "\n".join(rows), b["page"], rows=[r.split() for r in rows],
                                  source="scan_zone"))
        i = j
    return out


def _run_in_heading(ln: dict) -> tuple[str, str] | None:
    """A line that starts with a short bold label followed by regular text
    ("Probleem Zwarte kersenluis ...", "Productkeuze Een TAF-filter ...") -> (label, rest).
    The rest must start with a capital so an emphasised word inside a sentence is not split off."""
    lead: list[str] = []
    i = 0
    spans = ln["spans"]
    while i < len(spans) and (spans[i]["bold"] or not normalize_text(spans[i]["text"])):
        lead.append(spans[i]["text"])
        i += 1
    label = normalize_text("".join(lead))
    rest = normalize_text("".join(s["text"] for s in spans[i:]))
    if not label or not rest or word_count(label) > 8 or not rest[0].isupper():
        return None
    return label, rest


def _heading_styled(ln: dict, body: float) -> bool:
    return ln["size"] >= body * 1.2 or ln["bold"]


def _classify_pdf_block(rb: dict, pno: int, profile: str, body: float) -> list[dict]:
    """One raw PyMuPDF block -> typed blocks.

    Born-digital PDFs ("font" profile): a heading is judged at BLOCK level -- leading lines (max 3,
    <= 14 words, no sentence punctuation) that are larger or bold while the lines after them are
    not; a block whose every line is large/bold and longer than 3 lines is just emphasised text.
    A short bold label at the start of the first line ("Probleem Zwarte kersenluis ...") is split off
    as a run-in heading. OCR'd scans ("caps" profile) use ALL-CAPS lines instead. Every bullet
    starts its own list item and a block that is really a data grid becomes a table."""
    y = rb["bbox"][1]
    lines = rb["lines"]
    out: list[dict] = []
    para: list[str] = []

    def flush_para():
        if not para:
            return
        text = normalize_text("\n".join(para))
        para.clear()
        if not text:
            return
        if word_count(text) <= 60 and _CAPTION_RE.match(text):
            out.append(make_block("caption", text, pno, y=y))
        elif profile == "caps" and word_count(text) <= 80 and (
                _FOOTNOTE_RE.match(text)
                or (_FOOTNOTE_MARK_RE.match(text) and rb["bbox"][3] >= 0.78 * rb.get("page_h", 1e9))):
            out.append(make_block("footnote", text, pno, y=y))
        elif (word_count(text) >= 6 and tabular_score(text) >= 0.45) or len(_RATING_DOTS_RE.findall(text)) >= 2:
            out.append(make_block("table", text, pno, y=y, source="heuristic", rows=[text.split()]))
        elif _BULLET_ONLY_RE.match(text):
            out.append(make_block("list_item", _BULLET_ONLY_RE.sub("", text), pno, y=y))
        elif _NUMBERED_RE.match(text):
            out.append(make_block("list_item", text, pno, y=y))
        else:
            out.append(make_block("paragraph", text, pno, y=y))

    def emit_heading(heading_lines: list[dict]) -> None:
        text = normalize_text("\n".join(l["text"] for l in heading_lines))
        size = max(l["size"] for l in heading_lines)
        level = 2 if profile == "caps" else 1 if size >= body * 1.5 else 2 if size >= body * 1.2 else 3
        if text:
            out.append(make_block("heading", text, pno, level=level, y=y))

    start = 0
    if profile == "font":
        k = 0
        while k < min(3, len(lines)) and _heading_styled(lines[k], body):
            k += 1
        lead_text = normalize_text(" ".join(l["text"] for l in lines[:k]))
        if (k > 0 and not any(_heading_styled(l, body) for l in lines[k:]) and word_count(lead_text) <= 14
                and not lead_text.endswith((".", ";", ",", "\u2026")) and not _CAPTION_RE.match(lead_text)):
            emit_heading(lines[:k])
            start = k

    cap_lines: list[str] = []

    def flush_caption() -> None:
        if cap_lines:
            out.append(make_block("caption", normalize_text("\n".join(cap_lines)), pno, y=y))
            cap_lines.clear()

    for i in range(start, len(lines)):
        ln = lines[i]
        text = normalize_text(ln["text"])
        if profile == "caps":
            text = _clean_ocr_quotes(text)
            if not cap_lines:
                inline = _INLINE_CAPTION_RE.search(text)
                if inline and inline.start() > 8:  # "... but the cherry. FIGURE 28.--Plum curculio ..."
                    para.append(text[:inline.start()].rstrip())
                    text = text[inline.start():].lstrip()
            # OCR blocks mix a figure caption into the paragraph beside it: the caption starts at the
            # "FIGURE n" line and ends at the first line that finishes a sentence
            if cap_lines:
                cap_lines.append(text)
                if ends_sentence(text):
                    flush_caption()
                continue
            if _CAPTION_START_RE.match(text):
                flush_para()
                cap_lines.append(text)
                if ends_sentence(text):
                    flush_caption()
                continue
        raw_first = ln["text"].lstrip()[:1]
        is_symbol_bullet = bool(raw_first) and "\ue000" <= raw_first <= "\uf8ff"
        if profile == "caps":
            if looks_like_caps_heading(text):
                flush_para()
                emit_heading([{**ln, "text": text}])
                continue
        elif i == start == 0:
            run_in = _run_in_heading(ln)
            if run_in:
                label, rest = run_in
                out.append(make_block("heading", label, pno, level=3, y=y))
                para.append(rest)
                continue
        if is_symbol_bullet or _BULLET_ONLY_RE.match(text):
            flush_para()
            text = "\u2022 " + _BULLET_ONLY_RE.sub("", text)
        para.append(text)
    flush_para()
    flush_caption()
    return out


def _interleave_visuals(text_blocks: list[dict], pg: dict, figure_text: dict[tuple, list[str]]) -> list[dict]:
    """Places a page's tables/figures into the (content-stream ordered) text blocks at the first
    text block that starts below them; text inside a figure is kept on the figure, not as prose."""
    visuals: list[dict] = []
    for t in pg["tables"]:
        visuals.append({"kind": "table", "text": _rows_to_text(t["rows"]), "rows": t["rows"], "page": pg["page"],
                        "y": t["bbox"][1], "source": "pymupdf"})
    for f in pg["figures"]:
        visuals.append({"kind": "figure", "text": " ".join(figure_text.get(f, [])), "page": pg["page"], "y": f[1]})
    out: list[dict] = []
    pending = sorted(visuals, key=lambda v: v["y"])
    for b in text_blocks:
        while pending and pending[0]["y"] <= b.get("y", 0) + 2:
            out.append(pending.pop(0))
        out.append(b)
    out.extend(pending)
    return out


# ── HTML ────────────────────────────────────────────────────────────────────────────────

def _link_density(el: Tag) -> float:
    total = len(el.get_text(" ", strip=True))
    if not total:
        return 0.0
    return sum(len(a.get_text(" ", strip=True)) for a in el.find_all("a")) / total


def _prune_html(soup: BeautifulSoup) -> Tag:
    """Content root without navigation, banners and link-only lists."""
    for tag in soup(_HTML_DROP_TAGS):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    article = root.find("article") if root.name == "main" else None
    if article is not None and len(article.get_text()) >= 0.6 * len(root.get_text()):
        root = article
    for tag in root.find_all(["nav", "aside", "footer"]):
        tag.decompose()
    if root.name not in ("main", "article"):
        for tag in root.find_all("header"):
            tag.decompose()
    total = max(1, len(root.get_text()))
    for el in list(root.find_all(["div", "section", "ul", "ol", "span", "p"])):
        if getattr(el, "decomposed", False):
            continue
        attrs = " ".join([" ".join(el.get("class", []) or []), el.get("id", "") or ""])
        if _HTML_JUNK_ATTR_RE.search(attrs) and len(el.get_text()) < 0.4 * total and not el.find(["h1", "h2"]):
            el.decompose()
    for lst in list(root.find_all(["ul", "ol"])):
        if getattr(lst, "decomposed", False):
            continue
        if len(lst.find_all("li", recursive=False)) >= 3 and _link_density(lst) >= 0.7:
            lst.decompose()
    return root


def _html_emit_list(lst: Tag, out: list[dict], page: int) -> None:
    for li in lst.find_all("li", recursive=False):
        nested = [n.extract() for n in li.find_all(["ul", "ol"])]
        text = normalize_text(li.get_text(" ", strip=True))
        if text and not (word_count(text) < 12 and _HTML_BOILERPLATE_RE.match(text)):
            out.append(make_block("list_item", text, page))
        for n in nested:
            _html_emit_list(n, out, page)


def _html_walk(node: Tag, out: list[dict], page: int = 1) -> None:
    for child in node.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            text = normalize_text(str(child))
            if len(text) > 1 and not text.startswith("<!"):
                out.append(make_block("paragraph", text, page))
            continue
        name = child.name
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = normalize_text(child.get_text(" ", strip=True))
            if text:
                out.append(make_block("heading", text, page, level=int(name[1])))
        elif name in ("p", "blockquote", "pre", "dd", "dt", "figcaption", "caption"):
            text = normalize_text(child.get_text(" ", strip=True))
            if text and not (word_count(text) < 12 and _HTML_BOILERPLATE_RE.match(text)):
                out.append(make_block("caption" if name in ("figcaption", "caption") else "paragraph", text, page))
        elif name in ("ul", "ol"):
            _html_emit_list(child, out, page)
        elif name == "table":
            rows = _clean_rows([[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                                for tr in child.find_all("tr")])
            if rows:
                out.append(make_block("table", _rows_to_text(rows), page, rows=rows, source="html"))
        elif name == "figure":
            cap = child.find("figcaption")
            out.append(make_block("figure", "", page))
            if cap is not None:
                out.append(make_block("caption", normalize_text(cap.get_text(" ", strip=True)), page))
        elif name == "img":
            out.append(make_block("figure", normalize_text(child.get("alt", "") or ""), page))
        else:
            _html_walk(child, out, page)


def extract_html(path: Path, doc_id: str) -> Extraction:
    root = _prune_html(BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "lxml"))
    blocks: list[dict] = []
    _html_walk(root, blocks)
    deduped = [b for i, b in enumerate(blocks)
               if i == 0 or (b["kind"], b["text"]) != (blocks[i - 1]["kind"], blocks[i - 1]["text"])]
    return Extraction(deduped, [])


# ── Markdown ────────────────────────────────────────────────────────────────────────────

def extract_markdown(path: Path, doc_id: str) -> Extraction:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    cards_enabled = sum(1 for ln in lines if _MD_NUMBERED_ITEM_RE.match(ln.strip())) >= _MIN_NUMBERED_ITEMS
    blocks: list[dict] = []
    para: list[str] = []
    table_rows: list[list[str]] = []

    def flush_para():
        if para:
            text, urls = _strip_md(" ".join(para))
            para.clear()
            if text:
                blocks.append(make_block("paragraph", normalize_text(text), 1, urls=urls))

    def flush_table():
        if table_rows:
            rows = _clean_rows(table_rows)
            table_rows.clear()
            if rows:
                blocks.append(make_block("table", _rows_to_text(rows), 1, rows=rows, source="markdown"))

    for raw in lines:
        stripped = raw.strip()
        if re.match(r"^\|.*\|$", stripped):
            flush_para()
            if not re.match(r"^\|[\s:\-|]+\|$", stripped):
                table_rows.append([c.strip() for c in stripped.strip("|").split("|")])
            continue
        flush_table()
        m_head = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        m_card = _MD_NUMBERED_ITEM_RE.match(stripped)
        if m_head:
            flush_para()
            blocks.append(make_block("heading", _strip_md(m_head.group(2))[0], 1, level=len(m_head.group(1))))
        elif m_card and cards_enabled:
            flush_para()
            blocks.append(make_block("heading", f"{m_card.group(1)}. {m_card.group(2).strip()}", 1, level=3,
                                     section_type="probleem"))
        elif not stripped or stripped == "---":
            flush_para()
        elif re.match(r"^[-*+]\s+", stripped):
            flush_para()
            text, urls = _strip_md(re.sub(r"^[-*+]\s+", "", stripped))
            blocks.append(make_block("list_item", normalize_text(text), 1, urls=urls))
        else:
            para.append(stripped)
    flush_para()
    flush_table()
    return Extraction(blocks, [])


# ── document assembly ───────────────────────────────────────────────────────────────────

def _attach_visuals(doc_id: str, sections: list[dict]) -> tuple[list[dict], list[dict]]:
    """Moves tables/figures out of the prose into doc-level lists (with ids), linking an
    adjacent caption; the section keeps only the ids."""
    tables: list[dict] = []
    figures: list[dict] = []
    for sec in sections:
        blocks = sec["blocks"]
        for i, b in enumerate(blocks):
            if b["kind"] not in ("table", "figure"):
                continue
            neighbours = [blocks[j] for j in (i - 1, i + 1) if 0 <= j < len(blocks) and blocks[j]["kind"] == "caption"]
            caption = neighbours[0]["text"] if neighbours else ""
            if b["kind"] == "table":
                b["table_id"] = f"{doc_id}_t{len(tables) + 1}"
                tables.append({"table_id": b["table_id"], "section_id": sec["section_id"], "page": b["page"],
                               "caption": caption, "rows": b.get("rows", []), "text": b["text"],
                               "source": b.get("source", "")})
            else:
                b["figure_id"] = f"{doc_id}_f{len(figures) + 1}"
                figures.append({"figure_id": b["figure_id"], "section_id": sec["section_id"], "page": b["page"],
                                "caption": caption, "text": b["text"]})
        sec["table_ids"] = [b["table_id"] for b in blocks if b.get("table_id")]
        sec["figure_ids"] = [b["figure_id"] for b in blocks if b.get("figure_id")]
    return tables, figures


def quality_report(sections: list[dict], chunks: list[dict], tables: list[dict], figures: list[dict]) -> dict:
    words = [c["word_count"] for c in chunks]
    return {
        "n_sections": len(sections), "n_chunks": len(chunks), "n_tables": len(tables), "n_figures": len(figures),
        "chunk_words": {"min": min(words, default=0), "median": int(statistics.median(words)) if words else 0,
                        "max": max(words, default=0)},
        "flag_starts_midsentence": sum(1 for c in chunks if c["starts_midsentence"]),
        "flag_ends_open": sum(1 for c in chunks if c["ends_open"]),
        "flag_tabular": sum(1 for c in chunks if c["tabular_score"] >= 0.3),
        "stub_chunks": sum(1 for c in chunks if c["word_count"] < 30),
        "merged_stub_chunks": sum(1 for c in chunks if c["merged_stubs"]),
        "semantic_split_chunks": sum(1 for c in chunks if c["semantic_split"]),
    }


def _close_unpunctuated(blocks: list[dict]) -> list[dict]:
    """Web copy often leaves the full stop off a closing sentence ("... voor nieuwe infecties").
    A paragraph of >= 6 words that is followed by something that starts a NEW sentence (an uppercase
    paragraph / list / heading, or the end of the page) is a complete sentence missing its period, not
    a truncated one -- only the punctuation is added, never any words. (Not applied to PDFs, where an
    unfinished paragraph really can be a cut-off one.)"""
    out = [dict(b) for b in blocks]
    for i, b in enumerate(out):
        if b["kind"] != "paragraph" or ends_sentence(b["text"]) or word_count(b["text"]) < 6:
            continue
        nxt = next((o for o in out[i + 1:] if o["kind"] not in NON_PROSE_KINDS), None)
        if nxt is None or nxt["kind"] in ("heading", "list_item") or nxt["text"][:1].isupper() or nxt["text"][:1].isdigit():
            b["text"] = b["text"].rstrip() + "."
            b["period_added"] = True
    return out


def build_document(entry: dict, extraction: Extraction, source_type: str, split_fn=None) -> dict:
    doc_id = entry["id"]
    web_like = source_type in ("html", "markdown")
    kept = [b for b in extraction.blocks
            if not (b["kind"] in ("paragraph", "list_item") and is_boilerplate_paragraph(b["text"]))
            # site chrome leaves short label fragments ("Terug", "Lees meer", tag clouds); a real
            # paragraph is a sentence, a real list item has at least three words
            and not (web_like and b["kind"] == "paragraph" and word_count(b["text"]) < 4 and not ends_sentence(b["text"]))
            and not (web_like and b["kind"] == "list_item" and word_count(b["text"]) < 3 and not ends_sentence(b["text"]))]
    blocks = merge_continuations(kept)
    if web_like:
        blocks = _close_unpunctuated(blocks)
    sections = build_sections(blocks, doc_id, entry["title"])
    tables, figures = _attach_visuals(doc_id, sections)
    chunks = define_chunks({"doc_id": doc_id, "title": entry["title"]}, sections, split_fn=split_fn)
    for sec in sections:
        for b in sec["blocks"]:
            b.pop("y", None)
    return {
        "doc_id": doc_id, "title": entry["title"], "category": entry["category"],
        "language": entry["language"], "url": entry.get("url"), "source_file": Path(entry["file_path"]).name,
        "source_type": source_type,
        "chapters": group_chapters(sections, entry["title"]),
        "sections": sections, "tables": tables, "figures": figures, "chunks": chunks,
        "quality": quality_report(sections, chunks, tables, figures),
        "parsing_notes": extraction.notes,
        "cited_urls": sorted({u for b in blocks for u in b.get("urls", [])}),
    }


def make_topic_split_fn(model_name: str):
    """Paragraph-level Hearst/GraphSeg boundary detection (Auto Pilot's method, fed paragraph
    embeddings); only used for a section that is too big to be one retrieval unit."""
    from sentence_transformers import SentenceTransformer

    from core.text_segmentation import semantic_split_sentence_indices
    model = SentenceTransformer(model_name, device="cpu")
    model.max_seq_length = 512

    def split(units: list[str]) -> list[int]:
        emb = model.encode(units, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
        return semantic_split_sentence_indices(emb, percentile_cutoff=75.0, min_sentences=4)

    return split


def parse_entry(entry: dict, source_dir: Path, split_fn=None) -> dict | None:
    if entry["id"] in SKIP_FROM_RAG:
        print(f"[skip, excluded] {entry['id']}")
        return None
    if entry["status"] not in ("acquired", "already_acquired"):
        print(f"[skip, not acquired] {entry['id']} ({entry['status']})")
        return None
    path = resolve_source_path(entry, source_dir)
    if not path.exists():
        print(f"[skip, file missing] {entry['id']}: {path}")
        return None
    suffix = path.suffix.lower()
    configure_hyphenation(entry.get("language", "nl"))
    if suffix == ".pdf":
        extraction, source_type = extract_pdf(path, entry["id"]), "pdf"
    elif suffix in (".html", ".htm"):
        extraction, source_type = extract_html(path, entry["id"]), "html"
    elif suffix == ".md":
        extraction, source_type = extract_markdown(path, entry["id"]), "markdown"
    else:
        print(f"[skip, unsupported] {entry['id']}: {suffix}")
        return None
    if not any(b["kind"] in ("paragraph", "list_item") for b in extraction.blocks):
        print(f"[WARNING, no text] {entry['id']}: {extraction.notes}")
        return None
    doc = build_document({**entry, "file_path": str(path)}, extraction, source_type, split_fn)
    q = doc["quality"]
    print(f"[json] {entry['id']:<46} sec={q['n_sections']:>3} chunks={q['n_chunks']:>3} "
          f"words(min/med/max)={q['chunk_words']['min']}/{q['chunk_words']['median']}/{q['chunk_words']['max']} "
          f"tab={q['n_tables']} fig={q['n_figures']} flags(mid/open/tab)="
          f"{q['flag_starts_midsentence']}/{q['flag_ends_open']}/{q['flag_tabular']}")
    return doc


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", help="Alleen deze doc_id's")
    parser.add_argument("--no-semantic-split", action="store_true",
                        help="Te grote secties: gebalanceerde paragraaf-split, geen embedder laden")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    paths = AgentPaths.orchard()
    manifest = json.loads((paths.source_dir / "manifest.json").read_text(encoding="utf-8"))
    split_fn = None
    if not args.no_semantic_split:
        from pipeline.orchard_rag import EMBEDDER_MODEL
        split_fn = make_topic_split_fn(EMBEDDER_MODEL)

    paths.json_dir.mkdir(parents=True, exist_ok=True)
    if not args.only:
        for stale in paths.json_dir.glob("*.json"):  # regenerable output; never keep an old-format file
            stale.unlink()
    n_ok = 0
    for entry in manifest:
        if args.only and entry["id"] not in args.only:
            continue
        doc = parse_entry(entry, paths.source_dir, split_fn)
        if doc is None:
            continue
        (paths.json_dir / f"{doc['doc_id']}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        n_ok += 1
    print(f"\n{n_ok} document(en) -> {paths.json_dir}")


if __name__ == "__main__":
    main()
