"""Builds the RAG index from the structured JSON (``Data/Orchard/Orchard_JSON/*.json``, see
``build_orchard_json.py`` + ``orchard_qc.py``).

The chunks are already DEFINED in the JSON (structure-based, not length-based) and already judged by
the quality gate, so this script does no chunking of its own: it takes every chunk whose QC verdict is
``ok`` or ``warn`` (``orchard_qc.indexable``) -- never ``fail`` or ``references`` -- and embeds it. The
same selection feeds the knowledge graph and the procedural graph, so all three stay clean.

What is embedded is ``text_with_context`` ("Bron: <document>\\nSectie: <heading path>\\n\\n<text>"), so a
numbered problem card is found by its title even though the title is not part of its sentences.

Output (``Data/Orchard/Orchard_Agents_Training/``, gitignored -- regenerable):
  orchard_rag_chunks.json       -- the selected chunk records (document + chunk fields, see below)
  orchard_rag_embeddings.npy    -- float32, same row order as chunk_ids
  orchard_rag_chunk_ids.json    -- [chunk_id, ...]
  orchard_rag_meta.json         -- {"embedder", "max_seq_length", "query_prefix", "doc_prefix", ...} so the
                                   runtime (``orchard_rag.load_index``) uses the SAME model and prefixes

Usage::

    .venv\\Scripts\\python.exe -m pipeline.ingest.build_orchard_rag
    .venv\\Scripts\\python.exe -m pipeline.ingest.build_orchard_rag --embedder BAAI/bge-m3 --max-seq-length 512
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np  # noqa: E402

from core.paths import AgentPaths  # noqa: E402
from pipeline.ingest.orchard_qc import indexable  # noqa: E402

DEFAULT_EMBEDDER = "BAAI/bge-m3"
DEFAULT_MAX_SEQ_LENGTH = 512
# Models that want an instruction prefix on queries/passages (E5 family); everything else uses none.
PREFIXES = {"intfloat/multilingual-e5-large": ("query: ", "passage: "),
            "intfloat/multilingual-e5-base": ("query: ", "passage: ")}


def to_index_record(doc: dict, chunk: dict) -> dict:
    """One index chunk = the chunk fields from the JSON + the document fields retrieval/citation
    need. ``title`` stays the DOCUMENT title (what citations show); ``section_title`` is the chunk's
    own title; ``section_titles`` keeps the older list shape the evaluation harness matches on."""
    return {
        "chunk_id": chunk["chunk_id"], "doc_id": doc["doc_id"], "title": doc["title"],
        "category": doc["category"], "language": doc["language"], "url": doc.get("url"),
        "source_file": doc["source_file"], "source_type": doc.get("source_type"),
        "section_title": chunk["title"], "section_titles": [chunk["title"]],
        "heading_path": chunk["heading_path"], "type": chunk["type"], "types": [chunk["type"]],
        "pages": chunk["pages"], "page_num": (chunk["pages"] or [1])[0],
        "text": chunk["text"], "text_with_context": chunk["text_with_context"],
        "word_count": chunk["word_count"], "table_ids": chunk.get("table_ids", []),
        "figure_ids": chunk.get("figure_ids", []), "qc_verdict": chunk.get("qc", {}).get("verdict", "ok"),
    }


def load_indexable_chunks(json_dir: Path) -> tuple[list[dict], dict]:
    """(index records of every QC-passed chunk, selection statistics). The single entry point the
    RAG, KG and PG builders share."""
    records: list[dict] = []
    stats = {"documents": 0, "chunks_total": 0, "chunks_indexed": 0, "excluded": {}}
    for path in sorted(json_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        stats["documents"] += 1
        for chunk in doc.get("chunks", []):
            stats["chunks_total"] += 1
            if indexable(chunk):
                records.append(to_index_record(doc, chunk))
            else:
                verdict = chunk.get("qc", {}).get("verdict", "?")
                stats["excluded"][verdict] = stats["excluded"].get(verdict, 0) + 1
    stats["chunks_indexed"] = len(records)
    return records, stats


def embed_texts(model, texts: list[str], prefix: str = "", batch_size: int = 16) -> np.ndarray:
    return model.encode([prefix + t for t in texts], batch_size=batch_size, convert_to_numpy=True,
                        normalize_embeddings=True, show_progress_bar=False).astype(np.float32)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--embedder", default=DEFAULT_EMBEDDER)
    parser.add_argument("--max-seq-length", type=int, default=DEFAULT_MAX_SEQ_LENGTH,
                        help="Maximale invoerlengte in tokens (bge-m3 kan 8192, 512 is snel genoeg op CPU)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    paths = AgentPaths.orchard()
    records, stats = load_indexable_chunks(paths.json_dir)
    if not records:
        print(f"Geen indexeerbare chunks in {paths.json_dir} -- draai eerst build_orchard_json.py en orchard_qc.py.")
        return 1
    print(f"{stats['chunks_indexed']}/{stats['chunks_total']} chunks uit {stats['documents']} documenten "
          f"(uitgesloten door QC: {stats['excluded']})")

    from sentence_transformers import SentenceTransformer
    print(f"Laden van {args.embedder} (CPU) ...")
    model = SentenceTransformer(args.embedder, device="cpu")
    if args.max_seq_length:
        model.max_seq_length = args.max_seq_length
    query_prefix, doc_prefix = PREFIXES.get(args.embedder, ("", ""))
    embeddings = embed_texts(model, [r["text_with_context"] for r in records], doc_prefix)

    paths.cache_dir.mkdir(parents=True, exist_ok=True)
    cache = paths.cache_dir
    (cache / "orchard_rag_chunks.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    np.save(cache / "orchard_rag_embeddings.npy", embeddings)
    (cache / "orchard_rag_chunk_ids.json").write_text(json.dumps([r["chunk_id"] for r in records]), encoding="utf-8")
    (cache / "orchard_rag_meta.json").write_text(json.dumps({
        "embedder": args.embedder, "max_seq_length": int(model.max_seq_length), "query_prefix": query_prefix,
        "doc_prefix": doc_prefix, "n_chunks": len(records), "excluded_by_qc": stats["excluded"],
    }, indent=1), encoding="utf-8")
    print(f"Geschreven naar {cache}: {len(records)} chunks, embeddings {embeddings.shape}, "
          f"max_seq_length={model.max_seq_length}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
