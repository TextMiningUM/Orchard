"""Runtime retrieval (+ optional reranking) over the Track 1 RAG index built by
``pipeline/ingest/build_orchard_rag.py``.

Loaded once per process (module-level cache, like Auto Pilot's ``chief_engineer_agent_live.py``
``_RETRIEVAL`` singleton) -- cheap enough on CPU that both the Streamlit app and standalone
scripts can import this directly without a separate retrieval service.

Two-stage retrieval: cosine similarity over the bi-encoder index first pulls a wider candidate
pool (``pool_n``), then (if available) a pretrained multilingual cross-encoder reranks that pool
down to the final ``k`` -- same "cheap recall, precise rerank" shape as Auto Pilot's
``kg_retrieve()`` + ``rerank_hits()``. The reranker is a stock pretrained checkpoint
(``cross-encoder/mmarco-mMiniLMv2-L12-H384-v1``, Dutch is one of mMARCO's 14 languages), not a
project-specific fine-tune -- there isn't yet a labelled query/passage dataset to train one on
(Auto Pilot's own ``train_reranker.py`` needed built-up eval/training history first); revisit
once Track 1 has a gold Q&A eval set (design doc Sec C.3-ish / roadmap Fase 4).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sentence_transformers import CrossEncoder, SentenceTransformer

from core.paths import AgentPaths

EMBEDDER_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
RERANKER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

RAG_MAX_PER_DOCUMENT = 3  # avoid one long document crowding out every other source in top-k


class RagIndex:
    """Holds the loaded embedder, embeddings matrix, chunk records, and (optionally) the
    reranker. Build once via `load_index()`, reuse across many `retrieve()` calls."""

    def __init__(self, embedder: SentenceTransformer, embeddings: np.ndarray,
                 chunk_ids: list[str], chunks: list[dict], reranker: CrossEncoder | None):
        self.embedder = embedder
        self.embeddings = embeddings
        self.chunk_ids = chunk_ids
        self.chunk_by_id = {c["chunk_id"]: c for c in chunks}
        self.reranker = reranker

    @property
    def n_chunks(self) -> int:
        return len(self.chunk_ids)


_INDEX: RagIndex | None = None


def load_index(paths: AgentPaths | None = None, use_reranker: bool = True) -> RagIndex | None:
    """Lazily loads and memoizes the RAG index. Returns None (never raises) if the index hasn't
    been built yet -- callers should degrade to "no RAG context available" rather than crash,
    same posture as `pipeline/orchard_tools.py`'s stubs returning clear errors instead of fake
    data."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    paths = paths or AgentPaths.orchard()
    cache_dir = paths.cache_dir
    chunks_path = cache_dir / "orchard_rag_chunks.json"
    emb_path = cache_dir / "orchard_rag_embeddings.npy"
    ids_path = cache_dir / "orchard_rag_chunk_ids.json"
    if not (chunks_path.exists() and emb_path.exists() and ids_path.exists()):
        return None

    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    embeddings = np.load(emb_path)
    chunk_ids = json.loads(ids_path.read_text(encoding="utf-8"))
    embedder = SentenceTransformer(EMBEDDER_MODEL, device="cpu")
    reranker = CrossEncoder(RERANKER_MODEL, device="cpu") if use_reranker else None

    _INDEX = RagIndex(embedder, embeddings, chunk_ids, chunks, reranker)
    return _INDEX


def _dense_search(index: RagIndex, query: str, pool_n: int) -> list[tuple[str, float]]:
    q_emb = index.embedder.encode([query], convert_to_numpy=True, normalize_embeddings=True)[0]
    sims = index.embeddings @ q_emb  # both normalized -> dot product == cosine similarity
    top = np.argsort(-sims)[:pool_n]
    return [(index.chunk_ids[i], float(sims[i])) for i in top]


def _cap_per_document(hits: list[dict], max_per_document: int) -> list[dict]:
    seen: dict[str, int] = {}
    out = []
    for h in hits:
        doc_id = h["doc_id"]
        if seen.get(doc_id, 0) >= max_per_document:
            continue
        seen[doc_id] = seen.get(doc_id, 0) + 1
        out.append(h)
    return out


def retrieve(query: str, index: RagIndex, k: int = 5, pool_n: int = 60,
             rerank: bool = True, max_per_document: int = RAG_MAX_PER_DOCUMENT) -> list[dict]:
    """Returns up to `k` chunk records (each the chunk dict + a `score` field), best first.
    Dense search always runs; a cross-encoder rerank pass narrows the `pool_n` dense hits down to
    `k` whenever `rerank` is True AND a reranker was loaded (silently falls back to dense-only
    ranking otherwise, same graceful-degradation posture as the rest of this module).

    `pool_n=60` (raised from 25 on 2026-10-09, Fase 4 corpus-uitbreiding): with ~400 chunks across
    20 documents, a genuinely relevant chunk for a narrower topic (e.g. a single HTML page about
    vogelschade) can rank outside the top 25 purely on cosine similarity even though it is clearly
    the best match once reranked -- confirmed empirically (rank 28-43) while diagnosing why some
    newly-added sources weren't surfacing. A wider pool costs a few extra reranker calls (still
    well under a second on CPU) but meaningfully improves recall for narrow/single-source topics."""
    dense_hits = _dense_search(index, query, pool_n)
    if rerank and index.reranker is not None:
        pairs = [(query, index.chunk_by_id[cid]["text"]) for cid, _ in dense_hits]
        scores = index.reranker.predict(pairs)
        ranked = sorted(zip([cid for cid, _ in dense_hits], scores), key=lambda t: -t[1])
    else:
        ranked = dense_hits

    hits = [{**index.chunk_by_id[cid], "score": float(score)} for cid, score in ranked]
    hits = _cap_per_document(hits, max_per_document)
    return hits[:k]


def _format_pages(h: dict) -> str:
    """Renders a chunk's page(s) for a citation -- "p.2", "p.2-4" for a contiguous run (a
    merged, multi-section chunk), or "p.2, 5" for a non-contiguous set. Falls back to the
    legacy single `page_num` field if `pages` isn't present (defensive, e.g. older test
    fixtures)."""
    pages = h.get("pages")
    if not pages:
        return f"p.{h.get('page_num', 1)}"
    pages = sorted(pages)
    if pages == list(range(pages[0], pages[-1] + 1)) and len(pages) > 1:
        return f"p.{pages[0]}-{pages[-1]}"
    return "p." + ", ".join(str(p) for p in pages)


def format_context(hits: list[dict]) -> str:
    """Renders retrieved chunks as labelled, citable excerpts for a prompt -- mirrors Auto
    Pilot's `_format_context()` helpers in captain_agent_live.py/chief_engineer_agent_live.py."""
    if not hits:
        return "(geen relevante fragmenten gevonden in de kennisbank)"
    parts = []
    for j, h in enumerate(hits, 1):
        lang_note = "" if h["language"] == "nl" else " [Engelstalige bron]"
        parts.append(
            f"[Fragment {j} -- {h['title']}{lang_note}, {_format_pages(h)}]\n{h['text']}"
        )
    return "\n\n".join(parts)


def format_sources(hits: list[dict]) -> list[str]:
    """One short citation string per unique source document among `hits`, for a "Bronnen:"
    footer -- never duplicates the same document twice even if multiple chunks from it were used."""
    seen: set[str] = set()
    out = []
    for h in hits:
        if h["doc_id"] in seen:
            continue
        seen.add(h["doc_id"])
        out.append(f"{h['title']} ({_format_pages(h)})" + (f" -- {h['url']}" if h.get("url") else ""))
    return out
