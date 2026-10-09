"""CLI: run the Orchard gold evaluation (see ``pipeline/orchard_eval.py``).

    python -m pipeline.run_orchard_eval --validate-only      # gold set vs. current knowledge base
    python -m pipeline.run_orchard_eval                      # retrieval hit@k / MRR (local, CPU)
    python -m pipeline.run_orchard_eval --rerank             # ablation: + cross-encoder rerank (off by default)
    python -m pipeline.run_orchard_eval --answers            # + full advisor answers (needs the
                                                             #   Qwen server / SSH tunnel on :8811)
    python -m pipeline.run_orchard_eval --answers --no-rag   # ablation: advisor without RAG

Results land in ``Data/Orchard/Orchard_Eval/_runs/`` (gitignored scratch); paste the markdown
report into the design doc when a run is worth keeping.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from types import SimpleNamespace

from core.paths import AgentPaths
from pipeline.orchard_eval import (DEFAULT_KS, evaluate_answers, evaluate_retrieval,
                                   format_report, load_gold, validate_gold)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gold", help="Pad naar de gouden set (default: AgentPaths.gold_file)")
    parser.add_argument("--validate-only", action="store_true", help="Alleen de gouden set valideren")
    parser.add_argument("--answers", action="store_true", help="Ook volledige adviseur-antwoorden meten (Qwen-server nodig)")
    parser.add_argument("--rerank", action="store_true", help="Ablatie: dense retrieval + cross-encoder-rerank (standaard UIT)")
    parser.add_argument("--no-rag", action="store_true", help="Ablatie (met --answers): adviseur zonder kennisbank")
    parser.add_argument("--category", choices=["kennisbank", "praktijk", "guardrail"], help="Alleen deze categorie")
    parser.add_argument("--limit", type=int, help="Maximaal N vragen (snelle rooktest)")
    parser.add_argument("--max-new-tokens", type=int, default=700)
    parser.add_argument("--label", default="", help="Korte naam voor de resultaatbestanden")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    paths = AgentPaths.orchard()
    gold_path = args.gold or paths.gold_file
    items = load_gold(gold_path)

    from pipeline.orchard_rag import load_index
    index = load_index(paths, use_reranker=args.rerank)
    if index is None:
        print("Kennisbank-index ontbreekt -- draai eerst pipeline/ingest/build_orchard_rag.py", file=sys.stderr)
        return 2

    problems = validate_gold(items, list(index.chunk_by_id.values()))
    if problems:
        print(f"Gouden set is NIET geldig ({len(problems)} problemen):")
        for p in problems:
            print(" -", p)
        return 1
    print(f"Gouden set geldig: {len(items)} vragen tegen {index.n_chunks} fragmenten.")
    if args.validate_only:
        return 0

    if args.category:
        items = [i for i in items if i["category"] == args.category]
    if args.limit:
        items = items[:args.limit]

    from pipeline.orchard_rag import retrieve
    rerank = args.rerank
    retrieval = evaluate_retrieval(
        items, lambda q: retrieve(q, index, k=max(DEFAULT_KS), rerank=rerank), DEFAULT_KS)

    answers = None
    if args.answers:
        from pipeline.orchard_agent import ask_orchard_advisor
        from pipeline.qwen_remote import is_remote_server_up, reconnect_tunnel
        if not is_remote_server_up():
            ok, msg = reconnect_tunnel()
            if not ok:
                print(f"Qwen-server niet bereikbaar: {msg}", file=sys.stderr)
                return 3
        # Neutral context, no weather snapshot: reproducible, and keeps the real farm location out.
        ctx = SimpleNamespace(lat=52.0, lon=5.5, variety="Kordia", stage="bloei")
        rag = None if args.no_rag else index
        answers = evaluate_answers(
            items, lambda q: ask_orchard_advisor(q, ctx, snapshot=None, rag_index=rag,
                                                 max_new_tokens=args.max_new_tokens))

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = "_".join(filter(None, [args.label, "rerank" if args.rerank else "", "norag" if args.no_rag else ""]))
    report = format_report(retrieval, answers, label=f"({stamp} {label})".replace(" )", ")"))
    runs_dir = paths.eval_dir / "_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{stamp}_{label}" if label else stamp
    (runs_dir / f"{stem}.json").write_text(
        json.dumps({"retrieval": retrieval, "answers": answers}, ensure_ascii=False, indent=1), encoding="utf-8")
    (runs_dir / f"{stem}.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"\nOpgeslagen: {runs_dir / stem}.json / .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
