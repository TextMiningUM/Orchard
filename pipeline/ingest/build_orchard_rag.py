"""Chunks every parsed Track 1 document (``Data/Orchard/Orchard_JSON/*.json``, from
``parse_orchard_documents.py``) and embeds the chunks -- the RAG index
``pipeline/orchard_rag.py`` retrieves from at query time.

Ported from Auto Pilot's own ``pipeline/ingest/build_rag.py`` (2026-10-09, design doc Deel F
#18/G.18 -- "just copy the code", not re-derive a simpler version): embedding-based
TextTiling-style topic-boundary detection (Hearst 1997, see ``core/text_segmentation.py``)
splits an over-long section where it genuinely shifts subject, and an adaptive, per-document
merge floor (bottom-quartile adjacent-section embedding similarity) blocks merging two
sections that only coincidentally fit the token budget but aren't actually related. A section
whose ``type`` is in ``STANDALONE_TYPES`` (mirrors ``parse_orchard_documents.STANDALONE_SECTION_
TYPES`` -- currently just ``"probleem"``, one complete numbered item from a curated markdown
doc) is NEVER split or merged, regardless of its own token count -- this is what guarantees a
problem's own sources/citations can never drift onto a DIFFERENT, neighbouring problem.

Deliberately simplified vs. Auto Pilot in two ways, both documented rather than silently
dropped:
  1. No "chapters" grouping -- Orchard's documents aren't chapter-structured, so the merge-floor
     statistics are computed over one whole document's sections directly (equivalent to Auto
     Pilot treating each document as a single chapter).
  2. No keyword-topic Jaccard gate on merges -- Auto Pilot's domains have a built-up per-chunk
     concept/topic tagging pipeline this project doesn't have yet (design doc Deel F #16, the
     Knowledge-Graph item); the adaptive embedding-boundary-similarity floor alone already does
     most of the semantic-coherence gating, so this is a reasonable interim simplification, not
     a shortcut around the actual bug this rewrite fixes.

Embedding model: ``sentence-transformers/paraphrase-multilingual-mpnet-base-v2`` (768d) --
Orchard's corpus mixes Dutch and English sources in the same index (the project's "translate to
NL before agentic use" rule, design doc Sec C.6, applies to ANSWER generation/training data, not
to this intermediate retrieval index).

Output (``Data/Orchard/Orchard_Agents_Training/``, gitignored -- regenerable):
  orchard_rag_chunks.json       -- [{"chunk_id", "doc_id", "title", "category", "language",
                                     "url", "page_num", "text", "token_count", ...}, ...]
  orchard_rag_embeddings.npy    -- float32 array, same row order as chunk_ids
  orchard_rag_chunk_ids.json    -- [chunk_id, ...], same order as the embeddings

Safe to run LOCALLY (CPU-only embedding model, ~280M params -- no GPU needed; the live chat's
final generation still goes through the cloud Qwen3-8B server).

Usage::

    .venv\\Scripts\\python.exe -m pipeline.ingest.build_orchard_rag
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from core.paths import AgentPaths  # noqa: E402
from core.text_segmentation import (  # noqa: E402
    cosine_similarities,
    join_hyphenated_linebreaks,
    percentile,
    semantic_split_sentence_indices,
    split_sentences,
)
from pipeline.ingest.parse_orchard_documents import STANDALONE_SECTION_TYPES  # noqa: E402

import numpy as np  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

EMBEDDER_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

# ── Chunking parameters (same defaults as Auto Pilot's build_rag.py) ──────────────────────
CHUNK_TARGET_TOKENS = 400
CHUNK_MAX_TOKENS = 500
CHUNK_MIN_TOKENS = 40

# Embedding-based topic-boundary parameters (core/text_segmentation.py).
MIN_SENTENCES_FOR_TOPIC_SPLIT = 6
TOPIC_SPLIT_PERCENTILE = 85.0
# When deciding whether to merge two ADJACENT sections into one chunk, block the merge if
# their boundary similarity falls in the bottom quartile of this DOCUMENT's own
# adjacent-section similarities -- adaptive per-document, never a fixed global cosine cutoff.
MERGE_FLOOR_PERCENTILE = 25.0

STANDALONE_TYPES = STANDALONE_SECTION_TYPES  # re-exported for clarity at this module's call sites

_WORD_RE = re.compile(r"[A-Za-z]{2,}")
MIN_REAL_WORDS_PER_CHUNK = 2

# Chunk-level exclusions (design doc Deel F #13/G.17): a handful of HTML source pages mix pure
# site chrome (redirect/footer boilerplate, a fruit-category navigation menu, e-commerce
# cart/sort-order controls) into the parsed body text in a way the generic
# script/style/nav/header/footer-tag stripping in parse_orchard_documents.py's _parse_html()
# doesn't catch (the chrome isn't wrapped in one of those semantic tags on these specific
# sites). Found via pipeline/ingest/check_rag_chunk_quality.py's perplexity scoring + manual
# confirmation they carry zero actual disease/pest information -- same "honest, documented
# exclusion" discipline as parse_orchard_documents.SKIP_FROM_RAG, just at chunk instead of
# document granularity. Chunk ids are a text hash (see stable_chunk_id) -- stable across
# reruns as long as the excluded chunk's OWN text doesn't change, but WILL change if the
# chunking algorithm itself changes (re-verify with check_rag_chunk_quality.py after any such
# change, as happened during the 2026-10-09 Auto-Pilot-style chunker rewrite).
EXCLUDED_CHUNK_IDS: set[str] = {
    "fruitbomen_net_hagelschotziekte_a327bcf9",      # "Please click here if you are not redirected..."
    "fruitbomen_net_hagelschotziekte_f80698fe",      # webshop-promotietekst ("grootste assortiment...")
    "fruitbomen_net_hagelschotziekte_8ffe2a07",      # fruit-categorie-navigatiemenu ("Bloesem & Bloeitijden...")
    "puurvantveld_kersenvlieg_5d7ba424",             # webshop-bezorg-/marketingheader
    "puurvantveld_kersenvlieg_1b0c4181",             # product-sorteer-/winkelmandje-besturing
    "bomenenzo_bestuivingslijst_kersenboom_4fa508df",  # cookie-consent-banner
    "bomenenzo_bestuivingslijst_kersenboom_b728eb78",  # cookie-banner-vervolg + JS-waarschuwing
    "bomenenzo_bestuivingslijst_kersenboom_66e24e03",  # blog-teaser-links ("Lees meer...")
    "fruitbomen_net_bladvlekkenziekte_645b36b0",     # zelfde redirect/footer-boilerplate
    "fruitbomen_net_bladvlekkenziekte_1383330b",     # reclametekst ("...in onze webwinkel?")
    "fruitbomen_net_bladvlekkenziekte_30d82d90",     # zelfde webshop-promotietekst
    "fruitbomen_net_bladvlekkenziekte_0b1c6ba1",     # zelfde fruit-categorie-navigatiemenu
}

# Set by main() before any chunking/embedding happens.
model: SentenceTransformer | None = None
tokenizer = None


def stable_chunk_id(doc_id: str, chunk_index: int, text: str) -> str:
    """Structural id (doc_id + chunk POSITION + a text hash) -- never derived from
    section_ids/titles alone, which can repeat across unrelated sections that happen to share
    a title (same anti-collision reasoning as Auto Pilot's own stable_id)."""
    h = hashlib.md5(f"{doc_id}|{chunk_index}|{text}".encode()).hexdigest()[:8]
    return f"{doc_id}_{h}"


def _is_degenerate_chunk_text(text: str) -> bool:
    """True if `text` has fewer than MIN_REAL_WORDS_PER_CHUNK alphabetic words of length>=2 --
    catches a near-empty chunk (a lone page number, bullet, or 1-2 word caption), never a
    useful retrieval unit."""
    return len(_WORD_RE.findall(text)) < MIN_REAL_WORDS_PER_CHUNK


def token_count(text: str) -> int:
    return len(tokenizer.encode(text, add_special_tokens=False)) if text else 0


def _embed(texts: list[str]) -> np.ndarray:
    """Batch-embed `texts` with the already-loaded global `model` (normalize_embeddings=True,
    matching every other embedding call in this project). Returns an (0, dim) array for an
    empty input so callers never special-case it."""
    if not texts:
        return np.zeros((0, model.get_sentence_embedding_dimension()), dtype=np.float32)
    return model.encode(texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)


def _split_section_by_topic(section: dict) -> list[dict]:
    """Detect a genuine internal topic shift within ONE section's own text and split it there
    -- independent of, and applied BEFORE, the token-budget-driven _split_oversized_section
    below. Returns [section] unchanged if there isn't a confident boundary (short text, or no
    deep enough similarity valley) -- the common case.

    NEVER splits a STANDALONE_TYPES section ("probleem") -- those are already defined as ONE
    complete, independent retrieval unit on purpose."""
    if section["type"] in STANDALONE_TYPES:
        return [section]
    text = join_hyphenated_linebreaks(section["text"])
    sentences = split_sentences(text)
    if len(sentences) < MIN_SENTENCES_FOR_TOPIC_SPLIT:
        return [section]
    embeddings = _embed(sentences)
    split_idxs = semantic_split_sentence_indices(
        embeddings, percentile_cutoff=TOPIC_SPLIT_PERCENTILE, min_sentences=MIN_SENTENCES_FOR_TOPIC_SPLIT)
    if not split_idxs:
        return [section]
    bounds = [0] + split_idxs + [len(sentences)]
    out = []
    for k in range(len(bounds) - 1):
        piece_sentences = sentences[bounds[k]:bounds[k + 1]]
        if not piece_sentences:
            continue
        sub = dict(section)
        sub["text"] = " ".join(piece_sentences)
        sub["section_id"] = f"{section['section_id']}_t{k + 1}"
        sub["semantic_split"] = True
        out.append(sub)
    return out if len(out) > 1 else [section]


def _split_oversized_section(section: dict, max_tokens: int) -> list[dict]:
    """Split a single section whose OWN text already exceeds max_tokens into several smaller
    sections (same metadata, sliced text). NEVER called on a STANDALONE_TYPES section -- those
    stay exactly one chunk regardless of size (checked by the caller)."""
    text = section["text"]
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()] or [text]
    pieces: list[str] = []
    cur, cur_tokens = "", 0
    for p in paras:
        p_tokens = token_count(p)
        if p_tokens > max_tokens:
            for s in split_sentences(p):
                s_tokens = token_count(s)
                if cur_tokens + s_tokens > max_tokens and cur:
                    pieces.append(cur.strip())
                    cur, cur_tokens = "", 0
                cur += (" " if cur else "") + s
                cur_tokens += s_tokens
            continue
        if cur_tokens + p_tokens > max_tokens and cur:
            pieces.append(cur.strip())
            cur, cur_tokens = "", 0
        cur += ("\n\n" if cur else "") + p
        cur_tokens += p_tokens
    if cur.strip():
        pieces.append(cur.strip())
    out = []
    for i, piece in enumerate(pieces):
        sub = dict(section)
        sub["text"] = piece
        sub["section_id"] = f"{section['section_id']}_p{i + 1}"
        out.append(sub)
    return out


def _can_extend(cur_types: list[str], cur_tokens: int, nxt_type: str, nxt_tokens: int,
                 boundary_sim: float, merge_floor: float) -> bool:
    if nxt_type in STANDALONE_TYPES or any(t in STANDALONE_TYPES for t in cur_types):
        return False
    if cur_tokens + nxt_tokens > CHUNK_MAX_TOKENS:
        return False
    # Adaptive floor (core/text_segmentation.py): blocks a merge that's unusually weak
    # relative to the REST of this document's own adjacent-section similarities -- never a
    # fixed global cosine cutoff.
    if boundary_sim < merge_floor:
        return False
    return True


def _finalise_chunk(sections: list[dict], doc: dict, tokens: int, chunk_index: int) -> dict:
    text = "\n\n".join(s["text"] for s in sections)
    pages = sorted({p for s in sections for p in s.get("pages", [])})
    chunk_id = stable_chunk_id(doc["doc_id"], chunk_index, text)
    return {
        "chunk_id": chunk_id,
        "doc_id": doc["doc_id"], "title": doc["title"], "category": doc["category"],
        "language": doc["language"], "url": doc.get("url"), "source_file": doc["source_file"],
        "section_ids": [s["section_id"] for s in sections],
        "section_titles": [s["title"] for s in sections if s.get("title")],
        "types": [s["type"] for s in sections],
        "text": text,
        "pages": pages,
        "page_num": pages[0] if pages else 1,  # back-compat single-page field for citations
        "token_count": tokens,
        "n_sections": len(sections),
        "contains_semantic_split": any(s.get("semantic_split") for s in sections),
    }


def chunk_document(doc: dict) -> list[dict]:
    """Chunk every section of one parsed document into token-budgeted, topic-coherent chunks
    -- mirrors Auto Pilot's chunk_chapter(), with the whole document standing in for a single
    "chapter" (Orchard's documents aren't chapter-structured)."""
    raw_sections = doc.get("sections", [])
    if not raw_sections:
        return []
    sections = []
    for s in raw_sections:
        for piece in _split_section_by_topic(s):
            if piece["type"] not in STANDALONE_TYPES and token_count(piece["text"]) > CHUNK_MAX_TOKENS:
                sections.extend(_split_oversized_section(piece, CHUNK_MAX_TOKENS))
            else:
                sections.append(piece)

    section_embeddings = _embed([s["text"] for s in sections])
    adjacent_sims = cosine_similarities(section_embeddings)
    merge_floor = percentile(adjacent_sims, MERGE_FLOOR_PERCENTILE) if adjacent_sims else 0.0

    chunks = []
    i, chunk_index = 0, 0
    while i < len(sections):
        seed = sections[i]
        seed_tokens = token_count(seed["text"])
        current = [seed]
        cur_tokens = seed_tokens
        cur_types = [seed["type"]]
        j = i + 1
        while j < len(sections):
            nxt = sections[j]
            nxt_tokens = token_count(nxt["text"])
            boundary_sim = adjacent_sims[j - 1] if j - 1 < len(adjacent_sims) else 1.0
            if not _can_extend(cur_types, cur_tokens, nxt["type"], nxt_tokens, boundary_sim, merge_floor):
                break
            if cur_tokens >= CHUNK_TARGET_TOKENS and nxt_tokens >= CHUNK_MIN_TOKENS:
                break
            current.append(nxt)
            cur_tokens += nxt_tokens
            cur_types.append(nxt["type"])
            j += 1
        chunks.append(_finalise_chunk(current, doc, cur_tokens, chunk_index))
        chunk_index += 1
        i = j
    return [c for c in chunks
            if not _is_degenerate_chunk_text(c["text"]) and c["chunk_id"] not in EXCLUDED_CHUNK_IDS]


def main() -> None:
    global model, tokenizer
    paths = AgentPaths.orchard()
    json_files = sorted(paths.json_dir.glob("*.json"))
    if not json_files:
        print(f"Geen geparste documenten gevonden in {paths.json_dir} -- draai eerst "
              f"parse_orchard_documents.py.")
        return

    print(f"Laden van {EMBEDDER_MODEL} (CPU) ...")
    model = SentenceTransformer(EMBEDDER_MODEL, device="cpu")
    tokenizer = model.tokenizer

    all_chunks: list[dict] = []
    for path in json_files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        chunks = chunk_document(doc)
        all_chunks.extend(chunks)
        n_standalone = sum(1 for c in chunks if "probleem" in c["types"])
        extra = f" (waarvan {n_standalone} genummerde items)" if n_standalone else ""
        print(f"[chunked] {doc['doc_id']}: {len(chunks)} chunks{extra}")

    cache_dir = paths.cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = cache_dir / "orchard_rag_chunks.json"
    emb_path = cache_dir / "orchard_rag_embeddings.npy"
    ids_path = cache_dir / "orchard_rag_chunk_ids.json"

    print(f"\nEmbedding {len(all_chunks)} chunks met {EMBEDDER_MODEL} (CPU) ...")
    texts = [c["text"] for c in all_chunks]
    embeddings = _embed(texts)
    chunk_ids = [c["chunk_id"] for c in all_chunks]

    chunks_path.write_text(json.dumps(all_chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    np.save(emb_path, embeddings.astype(np.float32))
    ids_path.write_text(json.dumps(chunk_ids, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nGeschreven:\n  {chunks_path}\n  {emb_path} (shape {embeddings.shape})\n  {ids_path}")


if __name__ == "__main__":
    main()
