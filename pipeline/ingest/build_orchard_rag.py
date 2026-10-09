"""Chunks every parsed Track 1 document (``Data/Orchard/Orchard_JSON/*.json``, from
``parse_orchard_documents.py``) and embeds the chunks -- the RAG index
``pipeline/orchard_rag.py`` retrieves from at query time.

Deliberately simpler than Auto Pilot's ``pipeline/ingest/build_rag.py`` (no embedding-based
TextTiling topic-boundary detection): at this corpus size (~6 documents, a few hundred chars to
a few hundred KB of text each), a plain paragraph-aware token-budget chunker is proportionate --
revisit (reuse Auto Pilot's ``core/text_segmentation.py`` approach) only if/when the corpus grows
into the hundreds of documents Auto Pilot's VHF/OOW corpora have.

Chunking: paragraphs (blank-line-separated) are packed greedily up to ``CHUNK_MAX_WORDS``,
splitting an over-long single paragraph on sentence boundaries if needed. A short
``CHUNK_OVERLAP_WORDS`` tail of each chunk is repeated at the start of the next, so a fact split
across a chunk boundary is still retrievable from either side.

Embedding model: ``sentence-transformers/paraphrase-multilingual-mpnet-base-v2`` (768d) --
unlike Auto Pilot's English-only ``BAAI/bge-large-en-v1.5`` (``core/embedding.py``), Orchard's
corpus mixes Dutch (WUR/Netafim/Biofruitnet) and English (USDA/OSU) sources, and this model
handles both in the same embedding space without a translation step for retrieval purposes
(the project's "translate to NL before agentic use" rule, design doc Sec C.6, still applies to
ANSWER generation/training data -- not to this intermediate retrieval index).

Output (``Data/Orchard/Orchard_Agents_Training/``, gitignored -- regenerable):
  orchard_rag_chunks.json       -- [{"chunk_id", "doc_id", "title", "category", "language",
                                     "url", "page_num", "text"}, ...]
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

import numpy as np  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

EMBEDDER_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

CHUNK_MAX_WORDS = 220
CHUNK_MIN_WORDS = 25  # a trailing fragment shorter than this is merged into the previous chunk
CHUNK_OVERLAP_WORDS = 30

# Chunk-level exclusions (design doc Deel F #13/G.17): a handful of HTML source pages mix pure
# site chrome (redirect/footer boilerplate, a fruit-category navigation menu, e-commerce
# cart/sort-order controls) into the parsed body text in a way the generic
# script/style/nav/header/footer-tag stripping in parse_orchard_documents.py's _parse_html()
# doesn't catch (the chrome isn't wrapped in one of those semantic tags on these specific
# sites). Found via pipeline/ingest/check_rag_chunk_quality.py's perplexity scoring (these
# chunks scored among the highest/most "surprising" in the corpus) + manual confirmation they
# carry zero actual disease/pest information -- same "honest, documented exclusion" discipline
# as SKIP_FROM_RAG in parse_orchard_documents.py, just at chunk instead of document granularity.
# Chunk ids are stable across reruns (md5 of doc_id|page_num|chunk-index) as long as that
# document's own chunking doesn't change.
EXCLUDED_CHUNK_IDS: set[str] = {
    "fruitbomen_net_bladvlekkenziekte_c66f86ee",  # "Please click here if you are not redirected..."
    "fruitbomen_net_bladvlekkenziekte_811feada",  # fruit-category nav menu ("Jostabessen Veenbessen...")
    "fruitbomen_net_hagelschotziekte_e9d7e9bd",   # same redirect/footer boilerplate
    "fruitbomen_net_hagelschotziekte_f03c88f7",   # same fruit-category nav menu
    "puurvantveld_kersenvlieg_23cdac7e",          # webshop delivery/marketing header
    "puurvantveld_kersenvlieg_e7c7d6e9",          # product-sort/cart controls
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def stable_chunk_id(doc_id: str, page_num: int, idx: int) -> str:
    h = hashlib.md5(f"{doc_id}|{page_num}|{idx}".encode()).hexdigest()[:8]
    return f"{doc_id}_{h}"


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n|\n(?=[A-Z0-9])", text) if p.strip()]


def _pack_paragraphs(paragraphs: list[str]) -> list[str]:
    """Greedily packs paragraphs into chunks of at most CHUNK_MAX_WORDS words, splitting any
    single over-long paragraph on sentence boundaries, and prepending CHUNK_OVERLAP_WORDS of the
    previous chunk's tail to each new chunk (except the first)."""
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    def flush():
        nonlocal current, current_words
        if current:
            chunks.append(" ".join(current).strip())
        current, current_words = [], 0

    for para in paragraphs:
        words = para.split()
        if len(words) > CHUNK_MAX_WORDS:
            # Over-long single paragraph: split on sentences, pack those instead.
            flush()
            for sentence in _SENTENCE_SPLIT_RE.split(para):
                s_words = sentence.split()
                if current_words + len(s_words) > CHUNK_MAX_WORDS and current:
                    flush()
                current.append(sentence)
                current_words += len(s_words)
            continue
        if current_words + len(words) > CHUNK_MAX_WORDS and current:
            flush()
        current.append(para)
        current_words += len(words)
    flush()

    if len(chunks) > 1 and len(chunks[-1].split()) < CHUNK_MIN_WORDS:
        last = chunks.pop()
        chunks[-1] = chunks[-1] + " " + last

    # Add overlap (previous chunk's tail words prepended to the next chunk).
    for i in range(1, len(chunks)):
        tail = chunks[i - 1].split()[-CHUNK_OVERLAP_WORDS:]
        if tail:
            chunks[i] = " ".join(tail) + " " + chunks[i]
    return chunks


def chunk_document(doc: dict) -> list[dict]:
    """Returns a list of chunk records (no embeddings yet) for one parsed document --
    excludes any chunk_id listed in EXCLUDED_CHUNK_IDS (confirmed pure HTML-chrome noise)."""
    records = []
    for page in doc["pages"]:
        paragraphs = _split_paragraphs(page["text"])
        if not paragraphs:
            continue
        for idx, chunk_text in enumerate(_pack_paragraphs(paragraphs)):
            if len(chunk_text.split()) < CHUNK_MIN_WORDS and len(records) > 0:
                continue  # drop stray tiny fragments (e.g. a lone page header/footer)
            chunk_id = stable_chunk_id(doc["doc_id"], page["page_num"], idx)
            if chunk_id in EXCLUDED_CHUNK_IDS:
                continue
            records.append({
                "chunk_id": chunk_id,
                "doc_id": doc["doc_id"], "title": doc["title"], "category": doc["category"],
                "language": doc["language"], "url": doc.get("url"),
                "source_file": doc["source_file"], "page_num": page["page_num"],
                "text": chunk_text,
            })
    return records


def main() -> None:
    paths = AgentPaths.orchard()
    json_files = sorted(paths.json_dir.glob("*.json"))
    if not json_files:
        print(f"Geen geparste documenten gevonden in {paths.json_dir} -- draai eerst "
              "parse_orchard_documents.py.")
        return

    all_chunks: list[dict] = []
    for f in json_files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        recs = chunk_document(doc)
        all_chunks.extend(recs)
        print(f"[chunked] {doc['doc_id']}: {len(recs)} chunks")

    print(f"\nEmbedding {len(all_chunks)} chunks met {EMBEDDER_MODEL} (CPU) ...")
    model = SentenceTransformer(EMBEDDER_MODEL, device="cpu")
    texts = [c["text"] for c in all_chunks]
    embeddings = model.encode(texts, show_progress_bar=True, convert_to_numpy=True,
                               normalize_embeddings=True).astype(np.float32)

    cache_dir = paths.cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = cache_dir / "orchard_rag_chunks.json"
    emb_path = cache_dir / "orchard_rag_embeddings.npy"
    ids_path = cache_dir / "orchard_rag_chunk_ids.json"

    chunks_path.write_text(json.dumps(all_chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    np.save(emb_path, embeddings)
    ids_path.write_text(json.dumps([c["chunk_id"] for c in all_chunks], ensure_ascii=False), encoding="utf-8")

    print(f"\nGeschreven:\n  {chunks_path}\n  {emb_path} (shape {embeddings.shape})\n  {ids_path}")


if __name__ == "__main__":
    main()
