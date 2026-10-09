"""Shared text-cleanup + topic-segmentation helpers for document ingestion (mirrors Auto
Pilot's own ``core/text_segmentation.py`` -- same module name/location on purpose, see
``.github/copilot-instructions.md``). Ported near-verbatim; this project's corpus is smaller
so the merge-floor/percentile defaults in ``pipeline/ingest/build_orchard_rag.py`` are tuned
down accordingly, but the algorithms themselves are identical.
"""
from __future__ import annotations

import re

import numpy as np

# A word PDF line-wrapping broke across a line boundary ("contin-\nued" -> "continued").
# Call this BEFORE collapsing newlines to spaces -- a hyphen-broken word can otherwise end up
# permanently split into two separate "words".
_HYPHEN_LINEBREAK_RE = re.compile(r"(\w)-\n(?=[a-z])")


def join_hyphenated_linebreaks(text: str) -> str:
    """Join a word that a PDF's own line-wrapping broke across a line/page boundary
    ("contin-\\nued" -> "continued"). Call this BEFORE any heading/sentence-boundary
    detection, and before collapsing newlines to spaces -- a hyphen-broken word can
    otherwise defeat both."""
    return _HYPHEN_LINEBREAK_RE.sub(r"\1", text)


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split `text` into sentences on [.!?] boundaries. Good enough for the prose this
    project ingests -- not a full sentence-boundary disambiguator, but a stray extra split
    only ever means a slightly-too-fine topic-segmentation window, never a correctness
    problem for the callers below."""
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def cosine_similarities(embeddings: np.ndarray) -> list[float]:
    """Cosine similarity between every CONSECUTIVE pair of rows in `embeddings`
    (length N-1 for N embeddings, [] if fewer than 2). Assumes rows are already
    L2-normalized (every embedding call in this project uses normalize_embeddings=True) --
    a plain dot product is then exactly the cosine similarity."""
    if len(embeddings) < 2:
        return []
    return [float(np.dot(embeddings[i], embeddings[i + 1])) for i in range(len(embeddings) - 1)]


def depth_scores(similarities: list[float]) -> list[float]:
    """Hearst (1997) TextTiling's 'depth score' at each internal gap: how far similarity
    dips below the highest point on EACH side, summed -- a deep, narrow valley (genuine topic
    shift) scores high even if the surrounding similarities are only moderately higher; a
    shallow dip (ordinary sentence-to-sentence variation) scores near zero. Embeddings here
    instead of Hearst's original bag-of-words vectors is the "embedding TextTiling" approach
    (LangChain's SemanticChunker, LlamaIndex's SemanticSplitterNodeParser, GraphSeg/Glavas et
    al. 2016 converge on this)."""
    n = len(similarities)
    scores = [0.0] * n
    for i in range(n):
        left_peak = max(similarities[: i + 1])
        right_peak = max(similarities[i:])
        scores[i] = max(0.0, (left_peak - similarities[i]) + (right_peak - similarities[i]))
    return scores


def percentile(values: list[float], pct: float) -> float:
    """pct-th percentile of `values` (0.0 for an empty list)."""
    return float(np.percentile(values, pct)) if values else 0.0


def semantic_split_sentence_indices(
    embeddings: np.ndarray, *, percentile_cutoff: float = 85.0, min_sentences: int = 6,
    min_depth_score: float = 0.05,
) -> list[int]:
    """Sentence indices i (meaning: split BEFORE sentence i) where embedding similarity dips
    into a genuine topic-shift valley.

    Adaptive, not a fixed cosine cutoff: only the TOP (100-percentile_cutoff)% deepest valleys
    in THIS text's own depth-score distribution count as CANDIDATE boundaries. A percentile
    rank alone isn't enough though -- on a short/single-topic text the single largest ripple in
    an otherwise flat similarity curve still ranks "top 15%" by construction. `min_depth_score`
    is therefore a SECOND, absolute requirement -- a genuine topic shift widens the embedding
    gap by an order of magnitude more than embedding noise does.

    Returns [] (no split) if there aren't enough sentences for the depth-score's "peak on both
    sides" logic to mean anything (`min_sentences` default 6)."""
    n_sentences = len(embeddings)
    if n_sentences < min_sentences:
        return []
    sims = cosine_similarities(embeddings)
    scores = depth_scores(sims)
    if not scores or max(scores) <= 0.0:
        return []
    threshold = max(percentile(scores, percentile_cutoff), min_depth_score)
    return [i + 1 for i, d in enumerate(scores) if d >= threshold]
