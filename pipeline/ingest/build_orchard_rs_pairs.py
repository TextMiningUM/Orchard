"""Rejection sampling: DPO pairs from the model's OWN answers, ranked by the deterministic reward (``orchard_reward``).

For every verified training prompt (problem cards NOT in the gold or held-out sets) the base model is sampled N times at
temperature > 0 with the exact live prompt. Each sample -- plus the card-derived reference answer -- gets a reward;
the best answer with a clean compliance gate becomes ``chosen`` and the worst ``rejected`` when they differ by at least
``--min-gap``. This yields on-policy preference pairs (the failure modes are the model's own: too short, no sources,
invented numbers, a leaked dose, cut off) instead of only the card's documented "worst reaction".

Also writes ``rs_report.json``: how far the base model is from the reference answer per reward component -- the
analysis that says WHAT fine-tuning has to fix.

    .venv\\Scripts\\python.exe -m pipeline.ingest.build_orchard_rs_pairs --samples 4
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.paths import AgentPaths  # noqa: E402
from pipeline.orchard_reward import card_key_facts, score_answer  # noqa: E402

COMPONENTS = ("coverage", "focus", "grounding", "numeric", "complete", "concise", "reward")


def split_think(raw: str) -> str:
    """The visible answer of a raw generation (Qwen's <think> block removed; an unfinished one means no answer)."""
    if "<think>" in raw and "</think>" not in raw:
        return ""
    return raw.split("</think>", 1)[-1].strip() if "</think>" in raw else raw.strip()


def choose_pair(candidates: list[dict], min_gap: float) -> tuple[dict, dict] | None:
    """``candidates`` carry ``answer``, ``origin`` and ``score`` (from ``score_answer``). chosen = highest reward with gate 1;
    rejected = lowest reward; both must differ by ``min_gap`` and have different text."""
    clean = [c for c in candidates if c["score"]["gate"] == 1.0 and c["answer"].strip()]
    if not clean:
        return None
    best = max(clean, key=lambda c: (c["score"]["reward"], c["origin"] == "card"))
    worst = min(candidates, key=lambda c: c["score"]["reward"])
    if worst["answer"] == best["answer"] or best["score"]["reward"] - worst["score"]["reward"] < min_gap:
        return None
    return best, worst


def process_prompt(row: dict, key_facts: list[list[str]], sample_fn, n_samples: int, min_gap: float) -> dict:
    system, user, reference = (m["content"] for m in row["messages"])
    context = user
    candidates = [{"origin": "card", "answer": reference,
                   "score": score_answer(reference, key_facts=key_facts, context=context, gold_text=reference)}]
    for _ in range(n_samples):
        try:
            answer = split_think(sample_fn([{"role": "system", "content": system}, {"role": "user", "content": user}]))
        except Exception as exc:  # noqa: BLE001 -- one failed sample never aborts the batch
            candidates.append({"origin": f"error:{type(exc).__name__}", "answer": "",
                               "score": score_answer("", key_facts=key_facts, gold_text=reference)})
            continue
        candidates.append({"origin": "sample", "answer": answer,
                           "score": score_answer(answer, key_facts=key_facts, context=context, gold_text=reference)})
    pair = choose_pair(candidates, min_gap)
    return {"row": row, "candidates": candidates, "pair": pair}


def summarise(results: list[dict]) -> dict:
    samples = [c for r in results for c in r["candidates"] if c["origin"] == "sample"]
    refs = [c for r in results for c in r["candidates"] if c["origin"] == "card"]

    def means(cands):
        return {k: round(statistics.fmean(c["score"][k] for c in cands), 3) for k in COMPONENTS} if cands else {}

    paired = [r["pair"] for r in results if r["pair"]]
    return {
        "prompts": len(results), "samples": len(samples),
        "sample_means": means(samples), "reference_means": means(refs),
        "gate_violations": dict(Counter(v for c in samples for v in c["score"]["violations"])),
        "incomplete_samples": sum(1 for c in samples if c["score"]["complete"] == 0.0),
        "empty_samples": sum(1 for c in samples if not c["answer"]),
        "pairs": len(paired),
        "pair_chosen_origin": dict(Counter(p[0]["origin"] for p in paired)),
        "mean_gap": round(statistics.fmean(p[0]["score"]["reward"] - p[1]["score"]["reward"] for p in paired), 3) if paired else None,
    }


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--samples", type=int, default=4)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--max-new-tokens", type=int, default=900)
    ap.add_argument("--min-gap", type=float, default=0.15)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, help="smoke test: only the first N prompts per split")
    ap.add_argument("--weights", default="W0_base")
    ap.add_argument("--tag", default="", help="suffix for the output files (so a run with an adapter does not overwrite the base run)")
    ap.add_argument("--splits", default="train,val", help="comma separated: train,val")
    args = ap.parse_args(argv)

    paths = AgentPaths.orchard()
    tdir = paths.cache_dir / "training"
    cards = {}
    for line in (paths.cache_dir / "orchard_oac_cards.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        cards[rec["card_no"]] = rec

    from pipeline.qwen_remote import generate_remote, is_remote_server_up, reconnect_tunnel
    if not is_remote_server_up() and not reconnect_tunnel()[0]:
        raise SystemExit("Qwen-server niet bereikbaar.")

    def sample_fn(messages):
        return generate_remote(messages, weights=args.weights, max_new_tokens=args.max_new_tokens, enable_thinking=False,
                               temperature=args.temperature, top_p=0.95, timeout_s=180)

    sfx = f"_{args.tag}" if args.tag else ""
    report: dict = {"args": vars(args), "splits": {}}
    for split in args.splits.split(","):
        rows = [json.loads(line) for line in (tdir / f"sft_cards_{split}.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        if args.limit:
            rows = rows[:args.limit]
        facts = [card_key_facts(cards[row["meta"]["card_no"]]["steps"]) for row in rows]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(lambda i: process_prompt(rows[i], facts[i], sample_fn, args.samples, args.min_gap), range(len(rows))))
        out = []
        for r in results:
            if r["pair"]:
                best, worst = r["pair"]
                out.append({"prompt": r["row"]["messages"][1]["content"], "system": r["row"]["messages"][0]["content"],
                            "chosen": best["answer"], "rejected": worst["answer"],
                            "meta": {**r["row"]["meta"], "source": "rejection_sampling", "chosen_origin": best["origin"],
                                     "rejected_origin": worst["origin"], "chosen_reward": round(best["score"]["reward"], 3),
                                     "rejected_reward": round(worst["score"]["reward"], 3),
                                     "rejected_violations": worst["score"]["violations"]}})
        (tdir / f"dpo_rs{sfx}_{split}.jsonl").write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in out) + ("\n" if out else ""),
                                                   encoding="utf-8")
        (tdir / f"rs_candidates{sfx}_{split}.json").write_text(json.dumps(
            [{"card_no": r["row"]["meta"]["card_no"], "candidates": r["candidates"]} for r in results], ensure_ascii=False, indent=1),
            encoding="utf-8")
        report["splits"][split] = summarise(results)
    (tdir / f"rs_report{sfx}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report["splits"], ensure_ascii=False, indent=1))
    return report


if __name__ == "__main__":
    main()
