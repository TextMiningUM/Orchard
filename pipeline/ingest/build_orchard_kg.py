"""Build the Orchard knowledge graph from the QC-passed chunks (same chunks as the RAG index).

    .venv\\Scripts\\python.exe -m pipeline.ingest.build_orchard_kg
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.paths import AgentPaths  # noqa: E402
from pipeline.orchard_kg import build_kg, save_kg  # noqa: E402


def main(paths: AgentPaths | None = None) -> dict:
    paths = paths or AgentPaths.orchard()
    chunks_path = paths.cache_dir / "orchard_rag_chunks.json"
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))  # == load_indexable_chunks() output
    kg = build_kg(chunks)
    out = save_kg(kg, paths.cache_dir)
    s = kg["stats"]
    print(f"KG: {s['n_chunks']} chunks, {s['n_concepts_used']}/{s['n_concepts_in_lexicon']} concepts used, "
          f"{s['chunks_without_concepts']} chunks without a concept, avg {s['avg_concepts_per_chunk']} concepts/chunk -> {out}")
    by_cat = Counter(kg["concept_category"].values())
    print("concepts per category:", dict(by_cat))
    top = sorted(kg["concept_df"].items(), key=lambda kv: -kv[1])[:12]
    print("most common concepts:", ", ".join(f"{c}={n}" for c, n in top))
    return kg


if __name__ == "__main__":
    main()
