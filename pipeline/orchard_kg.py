"""Knowledge graph over the QC-passed RAG chunks + hybrid (dense + graph) retrieval.

Port of Auto Pilot's ``build_kg.py`` (Tutorial 13 section 8): NOT a subject-predicate-object triple store but an
inverted-index style graph on top of the existing chunks --

    concept   -> chunk_ids            (inverted index, from ``orchard_concepts.py``)
    concept   <-> concept             (co-occurrence, symmetric, weighted)
    chunk     -> concepts (+ counts, + "in title" flag)
    document  -> chunk_ids
    chunk     <-> chunk               (adjacency inside one document, in reading order)
    alias     -> concept              (query-time normalisation: "hagelschot" -> Stigmina, shot hole, ...)

Built ONLY from chunks that passed the QC gate (``build_orchard_rag.load_indexable_chunks`` is the shared entry
point), so the graph is as clean as the index. Fully deterministic: no model decides what a concept is.

``retrieve_hybrid`` = dense cosine similarity + a concept boost. A concept's boost is weighted by its inverse document
frequency (a concept that tags half the corpus -- "gewasbescherming" -- must not steer retrieval like a rare one),
raised when the concept is in the chunk's TITLE, and a small co-occurrence boost lets "kersenvlieg" also lift chunks
about its usual neighbours (monitoring, netting, ...).
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from pipeline.orchard_concepts import CONCEPTS, aliases_for_kg, concept_category, tag_text

KG_FILENAME = "orchard_kg.json"
DEFAULT_CONCEPT_BOOST = 0.10
DEFAULT_COOCCUR_BOOST = 0.03
TITLE_MULTIPLIER = 1.5
MIN_COOCCUR_COUNT = 2  # a pair seen in a single chunk is not a relation


def build_kg(chunks: list[dict]) -> dict:
    chunk_meta: dict[str, dict] = {}
    chunk_concepts: dict[str, dict[str, int]] = {}
    title_concepts: dict[str, list[str]] = {}
    concept_chunks: dict[str, list[str]] = defaultdict(list)
    cooccur: dict[str, Counter] = defaultdict(Counter)
    doc_chunks: dict[str, list[str]] = defaultdict(list)

    for c in chunks:
        cid = c["chunk_id"]
        body = c.get("text_with_context") or c["text"]
        counts = tag_text(body)
        in_title = sorted(tag_text(" ".join([c.get("title", ""), *c.get("heading_path", [])])))
        chunk_concepts[cid] = counts
        title_concepts[cid] = [t for t in in_title if t in counts]
        chunk_meta[cid] = {"doc_id": c["doc_id"], "title": c.get("title", ""), "heading_path": c.get("heading_path", []),
                           "type": c.get("type", "prose"), "pages": c.get("pages", [])}
        for concept in counts:
            concept_chunks[concept].append(cid)
        doc_chunks[c["doc_id"]].append(cid)
        names = sorted(counts)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                cooccur[a][b] += 1
                cooccur[b][a] += 1

    adjacency: dict[str, list[str]] = {}
    for cids in doc_chunks.values():
        for i, cid in enumerate(cids):
            adjacency[cid] = [cids[j] for j in (i - 1, i + 1) if 0 <= j < len(cids)]

    n = max(1, len(chunk_meta))
    df = {concept: len(cids) for concept, cids in concept_chunks.items()}
    return {
        "chunk_meta": chunk_meta,
        "chunk_concepts": chunk_concepts,
        "title_concepts": title_concepts,
        "concept_chunks": dict(concept_chunks),
        "concept_cooccur": {a: {b: w for b, w in cnt.items() if w >= MIN_COOCCUR_COUNT} for a, cnt in cooccur.items()},
        "document_chunks": dict(doc_chunks),
        "adjacency": adjacency,
        "aliases": aliases_for_kg(),
        "concept_df": df,
        "concept_category": {concept: concept_category(concept) for concept in df},
        "stats": {
            "n_chunks": len(chunk_meta), "n_concepts_in_lexicon": len(CONCEPTS), "n_concepts_used": len(df),
            "n_docs": len(doc_chunks), "chunks_without_concepts": sum(1 for v in chunk_concepts.values() if not v),
            "avg_concepts_per_chunk": round(sum(len(v) for v in chunk_concepts.values()) / n, 2),
        },
    }


def idf_weight(kg: dict, concept: str) -> float:
    """1.0 for a concept in a single chunk, -> 0 for one that tags (almost) every chunk."""
    n = max(2, kg["stats"]["n_chunks"])
    df = max(1, kg["concept_df"].get(concept, 1))
    return max(0.0, math.log(n / df) / math.log(n))


def query_concepts(query: str, kg: dict) -> list[str]:
    """Concepts the question mentions (via the shared alias lexicon), restricted to concepts that occur in the KG."""
    return sorted(c for c in tag_text(query) if c in kg["concept_chunks"])


def retrieve_hybrid(query: str, index, kg: dict, k: int = 5, *, concept_boost: float = DEFAULT_CONCEPT_BOOST,
                    cooccur_boost: float = DEFAULT_COOCCUR_BOOST, max_per_document: int = 3,
                    return_trace: bool = False):
    """Dense cosine + graph boost over ALL chunks of ``index`` (a ``pipeline.orchard_rag.RagIndex``; ~400 chunks,
    so scoring every chunk is cheap). Returns chunk records with ``score``, ``dense_score`` and ``concept_hits``."""
    q_emb = index.embedder.encode([index.query_prefix + query], convert_to_numpy=True, normalize_embeddings=True)[0]
    dense = index.embeddings @ q_emb
    q_concepts = query_concepts(query, kg)
    weights = {c: idf_weight(kg, c) for c in q_concepts}

    neighbour_weight: dict[str, float] = defaultdict(float)
    for c in q_concepts:
        top = sorted(kg["concept_cooccur"].get(c, {}).items(), key=lambda kv: -kv[1])[:5]
        for other, _w in top:
            if other not in weights:
                neighbour_weight[other] = max(neighbour_weight[other], idf_weight(kg, other))

    scores = dense.astype(float).copy()
    hits_by_chunk: dict[str, list[str]] = {}
    for i, cid in enumerate(index.chunk_ids):
        have = kg["chunk_concepts"].get(cid, {})
        in_title = set(kg["title_concepts"].get(cid, []))
        matched = [c for c in q_concepts if c in have]
        boost = sum(concept_boost * weights[c] * (TITLE_MULTIPLIER if c in in_title else 1.0) for c in matched)
        boost += sum(cooccur_boost * w for other, w in neighbour_weight.items() if other in have)
        scores[i] += boost
        if matched:
            hits_by_chunk[cid] = matched

    order = np.argsort(-scores)
    out: list[dict] = []
    per_doc: dict[str, int] = {}
    for i in order:
        cid = index.chunk_ids[i]
        rec = index.chunk_by_id[cid]
        if rec.get("type") != "probleem":  # standalone cards are exempt from the per-document cap (see orchard_rag)
            if per_doc.get(rec["doc_id"], 0) >= max_per_document:
                continue
            per_doc[rec["doc_id"]] = per_doc.get(rec["doc_id"], 0) + 1
        out.append({**rec, "score": float(scores[i]), "dense_score": float(dense[i]),
                    "concept_hits": hits_by_chunk.get(cid, [])})
        if len(out) >= k:
            break
    if return_trace:
        return out, {"query_concepts": q_concepts, "expanded": sorted(neighbour_weight)}
    return out


def kg_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / KG_FILENAME


def save_kg(kg: dict, cache_dir: Path) -> Path:
    path = kg_path(cache_dir)
    path.write_text(json.dumps(kg, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


_KG: dict | None = None


def load_kg(cache_dir: Path | None = None) -> dict | None:
    """Memoised; None (never raises) when the KG has not been built, so callers degrade to dense-only retrieval."""
    global _KG
    if _KG is not None:
        return _KG
    if cache_dir is None:
        from core.paths import AgentPaths
        cache_dir = AgentPaths.orchard().cache_dir
    path = kg_path(cache_dir)
    if not path.exists():
        return None
    _KG = json.loads(path.read_text(encoding="utf-8"))
    return _KG
