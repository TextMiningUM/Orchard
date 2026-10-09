"""Build the Orchard procedural graph from the reasoning traces (derived from the QC-passed chunks).

    .venv\\Scripts\\python.exe -m pipeline.ingest.build_orchard_pg [--thresh 0.893]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.paths import AgentPaths  # noqa: E402
from pipeline.orchard_pg import CANON_THRESH, build_pg, collect_steps, sample_path, save_pg  # noqa: E402


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--thresh", type=float, default=CANON_THRESH, help="cosine threshold for merging equal steps")
    ap.add_argument("--traces-file", type=Path, nargs="*", help="default: <cache>/orchard_reasoning_traces*.jsonl")
    args = ap.parse_args(argv)

    paths = AgentPaths.orchard()
    files = args.traces_file or sorted(paths.cache_dir.glob("orchard_reasoning_traces*.jsonl"))
    rows = [json.loads(line) for f in files for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    records = collect_steps(rows)
    if not records:
        raise SystemExit("Geen traces met >= 2 stappen gevonden -- draai eerst extract_orchard_oac.")

    meta = json.loads((paths.cache_dir / "orchard_rag_meta.json").read_text(encoding="utf-8"))
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(meta["embedder"], device="cpu")
    model.max_seq_length = int(meta.get("max_seq_length", 512))
    embed = lambda texts: model.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False)

    pg = build_pg(records, embed, args.thresh)
    out = save_pg(pg, paths.cache_dir)
    s = pg["stats"]
    print(f"PG: {s['n_traces']} traces, {s['n_steps']} steps -> {s['n_nodes']} nodes ({s['merged_nodes']} merged), "
          f"{s['n_edges']} edges ({s['edges_with_support_gt1']} with support > 1) -> {out}")
    print("Top transitions by support:")
    for e in pg["edges"][:6]:
        print(f"  [{e['support']}x] {pg['nodes'][e['u']]['label'][:55]}  ->  {pg['nodes'][e['v']]['label'][:55]}")
    fam = next(iter(s["families"]), None)
    if fam:
        print(f"Sample path ({fam}):")
        for nid in sample_path(pg, fam):
            print("   ->", pg["nodes"][nid]["label"][:90])
    return pg


if __name__ == "__main__":
    main()
