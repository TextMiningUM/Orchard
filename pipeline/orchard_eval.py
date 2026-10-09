"""Evaluation harness for the Orchard advisor (design doc Deel E stap 9 / B.10).

Measures the three things the roadmap calls for before any fine-tuning is worth attempting:

- **Retrieval hit@k / MRR** -- does the knowledge-base search surface the expected source
  (a whole document, or one numbered problem card of the 200-probleem document)?
- **Answer quality proxies** -- grounding percentage (``assess_grounding`` heuristic), key-fact
  coverage (the answer must contain the facts the gold set says the source contains) and
  compliance (guardrail questions must not produce a concrete dose).
- **Latency** -- retrieval-only and end-to-end answer latency (mean/p50/p95).

Everything here is pure/deterministic except the two callables the caller injects
(``retrieve_fn`` / ``ask_fn``), so the logic is unit-testable without loading models or
reaching the cloud server. The gold set (``Data/Orchard/Orchard_Eval/orchard_gold_qa.json``) is
held-out: never train on it. Matching is lexical on purpose (accent-folded, lowercase
substrings) -- cheap, reproducible, and an honest lower bound; it is not an LLM judge.
"""
from __future__ import annotations

import json
import re
import statistics
import time
import unicodedata
from pathlib import Path

DEFAULT_KS = (1, 3, 5, 6, 10)
CATEGORIES = ("kennisbank", "praktijk", "guardrail")


def normalize(text: str) -> str:
    """Accent-folded, lowercase, whitespace-collapsed -- the shared basis for every lexical
    comparison in this module (gold key facts are authored in this normalized form)."""
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", folded.lower()).strip()


def load_gold(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["items"]


def parse_source(source: str) -> tuple[str, int | None]:
    """``"doc_id#12"`` -> ("doc_id", 12); ``"doc_id"`` -> ("doc_id", None)."""
    doc_id, sep, number = source.partition("#")
    return doc_id, (int(number) if sep else None)


def hit_matches_source(hit: dict, source: str) -> bool:
    doc_id, problem_no = parse_source(source)
    if hit["doc_id"] != doc_id:
        return False
    if problem_no is None:
        return True
    prefix = f"{problem_no}. "
    return any(title.startswith(prefix) for title in hit.get("section_titles", []))


def first_hit_rank(hits: list[dict], sources: list[str]) -> int | None:
    """1-based rank of the first hit matching ANY expected source, else None."""
    for rank, hit in enumerate(hits, 1):
        if any(hit_matches_source(hit, s) for s in sources):
            return rank
    return None


def retrieval_summary(ranks: list[int | None], ks: tuple[int, ...] = DEFAULT_KS) -> dict:
    n = len(ranks)
    if n == 0:
        return {"n": 0}
    out: dict = {"n": n}
    for k in ks:
        out[f"hit@{k}"] = sum(1 for r in ranks if r is not None and r <= k) / n
    out["mrr"] = sum(1 / r for r in ranks if r) / n
    out["miss_rate"] = sum(1 for r in ranks if r is None) / n
    return out


def fact_coverage(answer: str, key_facts: list[list[str]]) -> tuple[float, list[list[str]]]:
    """Fraction of key facts present in `answer` (a fact is present if ANY of its alternative
    substrings occurs), plus the facts that were missing. No facts -> (1.0, [])."""
    if not key_facts:
        return 1.0, []
    text = normalize(answer)
    missing = [fact for fact in key_facts if not any(normalize(alt) in text for alt in fact)]
    return (len(key_facts) - len(missing)) / len(key_facts), missing


def forbidden_matches(answer: str, patterns: list[str]) -> list[str]:
    return [p for p in patterns if re.search(p, normalize(answer))]


def latency_stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, max(0, round(0.95 * len(ordered)) - 1))
    return {"n": len(ordered), "mean": statistics.fmean(ordered),
            "p50": statistics.median(ordered), "p95": ordered[p95_index], "max": ordered[-1]}


def validate_gold(items: list[dict], chunks: list[dict]) -> list[str]:
    """Self-consistency check of the gold set against the current knowledge base: unique ids,
    known categories, every expected source resolves to at least one chunk, and every key
    fact literally occurs in the text of the expected source chunks (so the gold set can't
    demand facts the sources don't contain). Returns human-readable problems ([] = valid)."""
    problems: list[str] = []
    seen_ids: set[str] = set()
    for item in items:
        iid = item.get("id", "<geen id>")
        if iid in seen_ids:
            problems.append(f"{iid}: dubbel id")
        seen_ids.add(iid)
        if item.get("category") not in CATEGORIES:
            problems.append(f"{iid}: onbekende categorie {item.get('category')!r}")
        if not item.get("question", "").strip():
            problems.append(f"{iid}: lege vraag")
        for pattern in item.get("forbidden_patterns", []):
            try:
                re.compile(pattern)
            except re.error as exc:
                problems.append(f"{iid}: ongeldige regex {pattern!r}: {exc}")
        sources = item.get("sources", [])
        if item.get("category") != "guardrail" and not sources:
            problems.append(f"{iid}: geen verwachte bron")
        expected_text = ""
        resolved = 0
        for source in sources:
            matched = [c for c in chunks if hit_matches_source(c, source)]
            if matched:
                resolved += 1
            expected_text += " " + " ".join(normalize(c["text"]) for c in matched)
        # Sources are ALTERNATIVES: an item is only unanswerable when none of them exists in the
        # knowledge base (a source can legitimately be absent, e.g. quarantined by the QC gate).
        if sources and not resolved:
            problems.append(f"{iid}: geen enkele verwachte bron bestaat in de kennisbank ({sources})")
        if sources:
            for fact in item.get("key_facts", []):
                if not any(normalize(alt) in expected_text for alt in fact):
                    problems.append(f"{iid}: feit {fact} staat in geen enkele verwachte bron")
    return problems


def evaluate_retrieval(items: list[dict], retrieve_fn, ks: tuple[int, ...] = DEFAULT_KS) -> dict:
    """`retrieve_fn(question) -> list[hit]` (best first, at least ``max(ks)`` deep). Only items
    with expected sources take part. Returns per-item results plus overall/per-category
    summaries and retrieval latency stats (seconds)."""
    per_item = []
    for item in items:
        if not item.get("sources"):
            continue
        start = time.perf_counter()
        hits = retrieve_fn(item["question"])
        elapsed = time.perf_counter() - start
        per_item.append({
            "id": item["id"], "category": item["category"], "question": item["question"],
            "rank": first_hit_rank(hits, item["sources"]), "latency_s": elapsed,
            "top_docs": [h["doc_id"] for h in hits[:3]],
        })
    by_category = {
        cat: retrieval_summary([r["rank"] for r in per_item if r["category"] == cat], ks)
        for cat in CATEGORIES if any(r["category"] == cat for r in per_item)
    }
    return {
        "per_item": per_item,
        "summary": {"overall": retrieval_summary([r["rank"] for r in per_item], ks),
                    "by_category": by_category,
                    "latency_s": latency_stats([r["latency_s"] for r in per_item])},
    }


def evaluate_answers(items: list[dict], ask_fn) -> dict:
    """`ask_fn(question) -> object with .answer/.grounding/.sources` (an ``AdvisorResponse``).
    A failure of the callable (e.g. the cloud tunnel is down) is recorded per item and never
    aborts the run. Latency is end-to-end wall-clock seconds per question."""
    per_item = []
    for item in items:
        start = time.perf_counter()
        try:
            resp = ask_fn(item["question"])
        except Exception as exc:  # noqa: BLE001 -- per-item isolation is the point
            per_item.append({"id": item["id"], "category": item["category"],
                             "error": f"{type(exc).__name__}: {exc}",
                             "latency_s": time.perf_counter() - start})
            continue
        elapsed = time.perf_counter() - start
        answer = resp.answer or ""
        coverage, missing = fact_coverage(answer, item.get("key_facts", []))
        record = {
            "id": item["id"], "category": item["category"], "question": item["question"],
            "answer": answer, "grounding": resp.grounding, "latency_s": elapsed,
            "answered": bool(answer.strip()) and not answer.startswith("(geen antwoord"),
            "n_sources": len(resp.sources), "fact_coverage": coverage, "missing_facts": missing,
        }
        if item["category"] == "guardrail":
            violations = forbidden_matches(answer, item.get("forbidden_patterns", []))
            mentions = item.get("must_mention", [])
            mention_ok = all(any(normalize(alt) in normalize(answer) for alt in group) for group in mentions)
            record.update({"violations": violations, "mentions_authority": mention_ok,
                           "guardrail_pass": not violations and mention_ok})
        per_item.append(record)
    return {"per_item": per_item, "summary": _answer_summary(per_item)}


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _answer_summary(per_item: list[dict]) -> dict:
    ok = [r for r in per_item if "error" not in r]
    content = [r for r in ok if r["category"] != "guardrail"]
    guardrails = [r for r in ok if r["category"] == "guardrail"]
    summary: dict = {
        "n_total": len(per_item), "n_errors": len(per_item) - len(ok),
        "answered_pct": _mean([1.0 if r["answered"] else 0.0 for r in ok]),
        "grounding_green_pct": _mean([1.0 if r["grounding"] == "green" else 0.0 for r in ok]),
        "latency_s": latency_stats([r["latency_s"] for r in ok]),
        "content": {
            "n": len(content),
            "mean_fact_coverage": _mean([r["fact_coverage"] for r in content]),
            "full_coverage_pct": _mean([1.0 if r["fact_coverage"] == 1.0 else 0.0 for r in content]),
        },
        "guardrail": {
            "n": len(guardrails),
            "pass_pct": _mean([1.0 if r["guardrail_pass"] else 0.0 for r in guardrails]),
            "dose_violations": sum(1 for r in guardrails if r["violations"]),
        },
    }
    for cat in ("kennisbank", "praktijk"):
        rows = [r for r in content if r["category"] == cat]
        if rows:
            summary["content"][cat] = {
                "n": len(rows), "mean_fact_coverage": _mean([r["fact_coverage"] for r in rows]),
                "grounding_green_pct": _mean([1.0 if r["grounding"] == "green" else 0.0 for r in rows]),
            }
    return summary


def _pct(value: float | None) -> str:
    return "n.v.t." if value is None else f"{100 * value:.0f}%"


def _secs(stats: dict, key: str) -> str:
    return f"{stats[key]:.2f}s" if stats.get(key) is not None else "n.v.t."


def format_report(retrieval: dict | None, answers: dict | None, label: str = "") -> str:
    """Markdown report of one evaluation run (what gets pasted into the design doc)."""
    lines = [f"# Orchard-evaluatie {label}".rstrip(), ""]
    if retrieval:
        s = retrieval["summary"]
        ks = [k for k in s["overall"] if k.startswith("hit@")]
        lines += ["## Retrieval", "", "| Set | n | " + " | ".join(ks) + " | MRR |",
                  "|---|---|" + "---|" * len(ks) + "---|"]
        rows = [("totaal", s["overall"])] + list(s["by_category"].items())
        for name, row in rows:
            lines.append(f"| {name} | {row['n']} | " + " | ".join(_pct(row[k]) for k in ks)
                         + f" | {row['mrr']:.2f} |")
        lat = s["latency_s"]
        lines += ["", f"Retrieval-latency: gem. {_secs(lat, 'mean')}, p50 {_secs(lat, 'p50')}, "
                      f"p95 {_secs(lat, 'p95')}", ""]
        misses = [r for r in retrieval["per_item"] if r["rank"] is None]
        if misses:
            lines += [f"### Gemiste vragen ({len(misses)})", ""]
            lines += [f"- `{r['id']}` {r['question']} -> top: {', '.join(r['top_docs'])}" for r in misses]
            lines.append("")
    if answers:
        s = answers["summary"]
        lat = s["latency_s"]
        lines += ["## Antwoorden", "",
                  f"- Vragen: {s['n_total']} (fouten: {s['n_errors']})",
                  f"- Beantwoord: {_pct(s['answered_pct'])}",
                  f"- Grounding (groen): {_pct(s['grounding_green_pct'])}",
                  f"- Feitendekking (gem.): {_pct(s['content']['mean_fact_coverage'])}; "
                  f"volledig: {_pct(s['content']['full_coverage_pct'])}",
                  f"- Guardrail geslaagd: {_pct(s['guardrail']['pass_pct'])} "
                  f"(dosering-overtredingen: {s['guardrail']['dose_violations']})",
                  f"- Latency: gem. {_secs(lat, 'mean')}, p50 {_secs(lat, 'p50')}, "
                  f"p95 {_secs(lat, 'p95')}, max {_secs(lat, 'max')}", ""]
    return "\n".join(lines)
