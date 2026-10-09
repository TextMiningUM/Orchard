"""Evaluate retrieval over the teler's own logbook (LOCAL ONLY; needs the logbook database).

    $env:ORCHARD_LOGBOOK_RAG='1'; .venv\\Scripts\\python.exe -m pipeline.run_logbook_eval
"""
from __future__ import annotations

import json
import sys

from core.paths import AgentPaths
from pipeline.orchard_logbook_rag import LogbookIndex, evaluate, load_entries, synthetic_items


def main() -> int:
    paths = AgentPaths.orchard()
    db = paths.logbooks_dir / "orchard_logbook.db"
    if not db.exists():
        print("Logboek-database niet gevonden (lokaal-only data).", file=sys.stderr)
        return 2
    entries = load_entries(db)
    items = synthetic_items(entries)
    from pipeline.orchard_rag import load_index
    rag = load_index(paths)
    embedder, prefix = (rag.embedder, rag.query_prefix) if rag else (None, "")
    rows = {}
    for name, emb in (("lexicaal+tijd", None), ("hybride (+dense)", embedder)):
        rows[name] = evaluate(LogbookIndex(entries, emb, prefix), items)
    print(f"{len(entries)} logboekregels, {len(items)} synthetische vragen")
    for name, res in rows.items():
        print(f"\n{name}")
        for kind, r in res.items():
            print(f"  {kind:7} n={r['n']:3}  volledige recall@6/8: {r['full_recall']:.0%}  gem. recall: {r['mean_recall']:.0%}")
    out = paths.eval_dir / "_runs" / "logbook_retrieval_LOCALONLY.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
