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
import time
from datetime import datetime
from types import SimpleNamespace

from core.paths import AgentPaths
from pipeline.orchard_eval import (DEFAULT_KS, aggregate_answer_runs, evaluate_answers, evaluate_retrieval,
                                   format_aggregate, format_report, load_gold, validate_gold)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gold", help="Pad naar een eigen vragenset (overschrijft --set)")
    parser.add_argument("--set", choices=["gold", "heldout", "both"], default="gold",
                        help="Vragenset: gouden set (waarop configuraties gekozen zijn), held-out v2, of beide")
    parser.add_argument("--repeats", type=int, default=1,
                        help="Herhaal de antwoordmeting N keer (parallel) en rapporteer gemiddelde ± sd (met --answers)")
    parser.add_argument("--weights", default="W0_base",
                        help="Gewichten op de inferentieserver: W0_base of de naam van een LoRA-adapter")
    parser.add_argument("--rep-penalty", type=float, default=None,
                        help="repetition_penalty voor alle adviseur-aanroepen (bv. 1.05 tegen herhalings-lussen)")
    parser.add_argument("--ids", help="Alleen deze vraag-id's (komma-gescheiden), bv. ho04,gh09")
    parser.add_argument("--validate-only", action="store_true", help="Alleen de gouden set valideren")
    parser.add_argument("--answers", action="store_true", help="Ook volledige adviseur-antwoorden meten (Qwen-server nodig)")
    parser.add_argument("--rerank", action="store_true", help="Ablatie: dense retrieval + cross-encoder-rerank (standaard UIT)")
    parser.add_argument("--hybrid", action="store_true", help="Hybride retrieval: dense + kennisgraaf (concept-boost)")
    parser.add_argument("--concept-boost", type=float, default=0.10, help="Gewicht concept-boost (met --hybrid)")
    parser.add_argument("--cooccur-boost", type=float, default=0.03, help="Gewicht co-occurrence-boost (met --hybrid)")
    parser.add_argument("--obs-cards", action="store_true",
                        help="Onafhankelijke synthetische set: observatie-regel van elke probleemkaart -> die kaart")
    parser.add_argument("--max-per-doc", type=int, default=3, help="Max. fragmenten per bron in de top-k")
    parser.add_argument("--no-rag", action="store_true", help="Ablatie (met --answers): adviseur zonder kennisbank")
    parser.add_argument("--category", choices=["kennisbank", "praktijk", "guardrail"], help="Alleen deze categorie")
    parser.add_argument("--limit", type=int, help="Maximaal N vragen (snelle rooktest)")
    parser.add_argument("--max-new-tokens", type=int, default=1500)
    parser.add_argument("--prompt-style", choices=["full", "short"], default="full",
                        help="Systeemprompt: 'full' (volledig maar beknopt, standaard) of 'short' (oude, kortere stijl)")
    parser.add_argument("--label", default="", help="Korte naam voor de resultaatbestanden")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    paths = AgentPaths.orchard()
    if args.gold:
        items = load_gold(args.gold)
    else:
        items = []
        if args.set in ("gold", "both"):
            items += load_gold(paths.gold_file)
        if args.set in ("heldout", "both"):
            items += load_gold(paths.heldout_file)

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
    if args.obs_cards:
        from pipeline.orchard_eval import observation_card_items
        items = observation_card_items(list(index.chunk_by_id.values()))
        print(f"Synthetische set: {len(items)} observatie-vragen uit de probleemkaarten.")
    if args.limit:
        items = items[:args.limit]
    if args.ids:
        wanted = set(args.ids.split(","))
        items = [i for i in items if i["id"] in wanted]

    from pipeline.orchard_rag import retrieve
    rerank = args.rerank
    if args.hybrid:
        from pipeline.orchard_kg import load_kg, retrieve_hybrid
        kg = load_kg(paths.cache_dir)
        if kg is None:
            print("KG ontbreekt -- draai eerst pipeline/ingest/build_orchard_kg.py", file=sys.stderr)
            return 2
        retrieve_fn = lambda q: retrieve_hybrid(q, index, kg, k=max(DEFAULT_KS), concept_boost=args.concept_boost,
                                                cooccur_boost=args.cooccur_boost, max_per_document=args.max_per_doc)
    else:
        retrieve_fn = lambda q: retrieve(q, index, k=max(DEFAULT_KS), rerank=rerank, max_per_document=args.max_per_doc,
                                         hybrid=False)  # explicit dense baseline (retrieve() is hybrid by default)
    retrieval = evaluate_retrieval(items, retrieve_fn, DEFAULT_KS)

    answers = None
    aggregate = None
    runs: list[dict] = []
    if args.answers:
        from pipeline import orchard_agent
        if args.prompt_style == "short":
            orchard_agent.SYSTEM_PROMPT = orchard_agent.SYSTEM_PROMPT_SHORT
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
        orchard_agent.ADVISOR_WEIGHTS = args.weights
        if args.rep_penalty:
            orchard_agent.ADVISOR_SAMPLING["repetition_penalty"] = args.rep_penalty

        def ask(q):
            # A tunnel that drops mid-run must not turn into dozens of "errors": reconnect and retry (twice) first.
            for attempt in range(3):
                try:
                    return ask_orchard_advisor(q, ctx, snapshot=None, rag_index=rag, max_new_tokens=args.max_new_tokens)
                except ConnectionError:
                    if attempt == 2:
                        raise
                    reconnect_tunnel()
                    time.sleep(3)
        if args.repeats > 1:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=args.repeats) as pool:
                runs = list(pool.map(lambda _i: evaluate_answers(items, ask), range(args.repeats)))
            answers = runs[0]
            aggregate = aggregate_answer_runs(runs)
        else:
            answers = evaluate_answers(items, ask)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = "_".join(filter(None, [args.label, args.set if args.set != "gold" else "", "hybrid" if args.hybrid else "",
                                   "rerank" if args.rerank else "", "norag" if args.no_rag else "",
                                   f"tok{args.max_new_tokens}", f"prompt-{args.prompt_style}" if args.answers else "",
                                   f"w-{args.weights}" if args.weights != "W0_base" else "",
                                   f"rp{args.rep_penalty}" if args.rep_penalty else "",
                                   f"x{args.repeats}" if args.repeats > 1 else ""]))
    report = format_report(retrieval, answers, label=f"({stamp} {label})".replace(" )", ")"))
    if aggregate:
        report += "\n" + format_aggregate(aggregate, label=f"({label})")
    runs_dir = paths.eval_dir / "_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{stamp}_{label}" if label else stamp
    (runs_dir / f"{stem}.json").write_text(
        json.dumps({"retrieval": retrieval, "answers": answers, "runs": runs or None, "aggregate": aggregate},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    (runs_dir / f"{stem}.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"\nOpgeslagen: {runs_dir / stem}.json / .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
