"""Training-data extraction for the later SFT / DPO / Reflection rounds (roadmap Deel E stap 5-7).

NOTHING here trains a model -- it turns what we already trust into datasets, with the rules that make them safe to train on:

* **Track 1, problem cards** (deterministic, from ``extract_orchard_oac``; every field is a verbatim span of a card):
    - ``sft_cards``        grounded Dutch advice: the question is a grower's observation / a problem title, the context is
                           what the live retriever returns for it (so the model learns to answer FROM the fragments, with
                           the real distractors), the answer = Actie + Gevolg + Waarom + Vermijd + "Bronnen: ...".
    - ``dpo_cards``        chosen = that answer; rejected = the card's own "Slechtste reactie" given as advice (a
                           plausible-but-wrong answer the literature itself documents -- no synthetic negatives).
    - ``reflection_cards`` draft (= the worst-case answer) -> critique (the card's WAAROM) -> revision (= the answer): the
                           self-refine format (Madaan et al.) with the correction grounded in the source.
* **Track 2, logbook** (LOCAL ONLY -- real business data, gitignored, never copied to the pod): open-book SFT where the
  retrieved logbook rows are IN the prompt and the answer only cites them (``logbook_sft``), including abstentions ("dat
  staat niet in je logboek"). The log records actions and weather, never outcomes, so there is no logbook DPO/Reflection.
* **Feedback** (``orchard_dpo_feedback*.jsonl``): thumbs up/down answers are paired per question; unpaired ones are counted
  but unusable for DPO.

Safeguards (each one learned from looking at the data, see design doc G.27):
* cards whose source status is "nog geen bron gevonden" are NOT verified: written to a separate ``*_unverified`` file;
* cards that state a dose / product amount are excluded: the advisor's system prompt forbids doses as advice;
* cards that the hand-written GOLD set expects as a source are held out (``held_out_gold``): never train on the eval set;
* logbook rows flagged ``onzeker`` are skipped, and no logbook row is human-verified yet, so ALL logbook records are
  labelled ``silver``.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.paths import AgentPaths  # noqa: E402

VERIFIED_STATUSES = ("bevestigd", "deels bevestigd", "bevestigd voor spint")
_DOSE_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:ml|l|liter|kg|g|gr|gram|%|kg/ha|l/ha|g/l|ml/l)\b", re.I)
MONTHS = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober",
          "november", "december"]
LOGBOOK_SYSTEM_ADDENDUM = (
    " Bij vragen over het eigen logboek van de teler citeer je UITSLUITEND wat in de aangeleverde logboekfragmenten "
    "staat; staat het er niet in, zeg dat dan. Geef daarbij geen advies over middelen of doseringen."
)


# ── cards ───────────────────────────────────────────────────────────────────────────────

def mentions_dose(rec: dict) -> bool:
    return bool(_DOSE_RE.search(" ".join(rec.get(k, "") for k in ("action", "consequence", "why", "worst_case"))))


def gold_card_numbers(gold_items: list[dict], doc_id: str) -> set[int]:
    nums = set()
    for item in gold_items:
        for s in item.get("sources", []):
            d, _, n = s.partition("#")
            if d == doc_id and n.isdigit():
                nums.add(int(n))
    return nums


def card_answer(rec: dict, source_line: str) -> str:
    parts = [f"**Wat je ziet:** {rec['observation']}", f"**Wat te doen:** {rec['action']}"]
    if rec.get("consequence"):
        parts.append(f"**Effect:** {rec['consequence']}")
    if rec.get("why"):
        parts.append(f"**Waarom:** {rec['why']}")
    if rec.get("worst_case"):
        parts.append(f"**Vermijd:** {rec['worst_case']}")
    parts.append(source_line)
    return "\n\n".join(parts)


def worst_case_answer(rec: dict, source_line: str) -> str:
    """A plausible-but-wrong answer: the card's documented worst reaction presented as advice (same format and same
    citation as the good answer, so the preference pair differs in CONTENT only)."""
    return "\n\n".join([f"**Wat je ziet:** {rec['observation']}", f"**Wat te doen:** {rec['worst_case']}", source_line])


def card_prompts(rec: dict) -> list[str]:
    return [f"Ik zie het volgende in mijn kersenboomgaard: {rec['observation']} Wat kan ik doen?",
            f"Wat moet ik doen bij dit probleem: {rec['title'][0].lower() + rec['title'][1:]}?"]


def user_message(question: str, context: str) -> str:
    return f"Vraag: {question}\n\nRelevante kennisbank-fragmenten:\n{context}"


def reflection_critique(rec: dict) -> str:
    why = rec.get("why", "").rstrip(".")
    base = "Dit advies volgt de slechtste reactie bij dit probleem en lost de oorzaak niet op."
    return f"{base} {why + '.' if why else ''} Beter is: {rec['action']}".replace("  ", " ").strip()


def build_card_datasets(records: list[dict], retrieve_fn, format_context, format_sources, system_prompt: str,
                        held_out: set[int], index_chunks: dict[str, dict]) -> tuple[dict[str, list[dict]], Counter]:
    """``retrieve_fn(question) -> hits`` (the live retriever). Returns datasets + a counter of why cards were skipped."""
    out: dict[str, list[dict]] = {"sft_cards": [], "sft_cards_unverified": [], "dpo_cards": [], "reflection_cards": []}
    skipped: Counter = Counter()
    for rec in records:
        if rec["card_no"] in held_out:
            skipped["held_out_gold"] += 1
            continue
        if mentions_dose(rec):
            skipped["mentions_dose"] += 1
            continue
        verified = rec["sources_status"] in VERIFIED_STATUSES
        card_chunk = index_chunks.get(rec["chunk_id"])
        for q in card_prompts(rec):
            hits = retrieve_fn(q)
            if not any(h["chunk_id"] == rec["chunk_id"] for h in hits):
                skipped["card_not_retrieved"] += 1
                continue  # the answer would not be grounded in the prompt: never train that
            src = format_sources([h for h in hits if h["chunk_id"] == rec["chunk_id"]] or [card_chunk])
            source_line = "Bronnen: " + "; ".join(src) + f" (kaart {rec['card_no']}, bron-status: {rec['sources_status']})."
            prompt = user_message(q, format_context(hits))
            good, bad = card_answer(rec, source_line), worst_case_answer(rec, source_line)
            meta = {"card_no": rec["card_no"], "chunk_id": rec["chunk_id"], "verified": verified,
                    "sources_status": rec["sources_status"]}
            if not verified:
                out["sft_cards_unverified"].append({"messages": _chat(system_prompt, prompt, good), "meta": meta})
                continue
            out["sft_cards"].append({"messages": _chat(system_prompt, prompt, good), "meta": meta})
            if rec.get("worst_case"):
                out["dpo_cards"].append({"prompt": prompt, "system": system_prompt, "chosen": good, "rejected": bad, "meta": meta})
                out["reflection_cards"].append({"prompt": prompt, "system": system_prompt, "draft": bad,
                                                "critique": reflection_critique(rec), "revision": good, "meta": meta})
    return out, skipped


def _chat(system: str, user: str, assistant: str) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user},
            {"role": "assistant", "content": assistant}]


# ── logbook (local only) ────────────────────────────────────────────────────────────────

def load_logbook(db_path: Path) -> list[dict]:
    """Usable logbook entries: dated, not flagged uncertain, with at least one application."""
    import sqlite3

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    entries = []
    for e in con.execute("select * from entries where datum_iso is not null and onzeker = 0 order by datum_iso, id"):
        apps = [dict(a) for a in con.execute(
            "select middel, hoeveelheid from toepassingen where entry_id = ? order by volgorde", (e["id"],))]
        if apps:
            entries.append({"id": e["id"], "date": e["datum_iso"], "time": e["tijd"], "remarks": (e["opmerkingen"] or "").strip(),
                            "apps": apps, "verified": bool(e["geverifieerd"])})
    con.close()
    return entries


def _nl_date(iso: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{d} {MONTHS[m - 1]} {y}"


def _apps_text(apps: list[dict]) -> str:
    return ", ".join(f"{a['middel']} ({a['hoeveelheid']})" if a.get("hoeveelheid") else a["middel"] for a in apps)


def _fragment(e: dict) -> str:
    rem = f" Opmerkingen: {e['remarks']}" if e["remarks"] else ""
    return f"[Logboek {_nl_date(e['date'])}] Middelen: {_apps_text(e['apps'])}.{rem}"


def build_logbook_dataset(entries: list[dict], system_prompt: str, seed: int = 13, n_abstain: int = 40) -> list[dict]:
    rng = random.Random(seed)
    by_year: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_year[e["date"][:4]].append(e)
    rows: list[dict] = []

    def add(question: str, shown: list[dict], answer: str, kind: str, extra: dict | None = None) -> None:
        rng.shuffle(shown)
        ctx = "\n".join(_fragment(e) for e in shown) or "(geen logboekfragmenten gevonden)"
        rows.append({"messages": _chat(system_prompt + LOGBOOK_SYSTEM_ADDENDUM,
                                       f"Vraag: {question}\n\nRelevante logboekfragmenten:\n{ctx}", answer),
                     "meta": {"kind": kind, "silver": True, "verified": False, **(extra or {})}})

    by_date: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_date[e["date"]].append(e)

    for day, day_entries in sorted(by_date.items()):
        pool = [o for o in by_year[day[:4]] if o["date"] != day]
        distract = rng.sample(pool, min(3, len(pool)))
        lines = []
        for e in day_entries:
            rem = f" ({e['remarks'].rstrip('.')})" if e["remarks"] else ""
            lines.append(f"- {_apps_text(e['apps'])}{rem}")
        answer = (f"Op {_nl_date(day)} staan in je logboek:\n" + "\n".join(lines) +
                  f"\n\nBronnen: eigen logboek, {_nl_date(day)}.")
        add(f"Wat heb ik op {_nl_date(day)} gespoten of gestrooid?", [*day_entries, *distract], answer,
            "recall_day", {"date": day, "entry_ids": [e["id"] for e in day_entries]})
    for e in entries:
        pool = [o for o in by_year[e["date"][:4]] if o["id"] != e["id"]]
        distract = rng.sample(pool, min(3, len(pool)))
        m = re.search(r"\b[Tt]egen ([A-Za-z][A-Za-z\- ]{2,30}?)(?:[.,;]|$)", e["remarks"])
        if m:
            target = m.group(1).strip()
            add(f"Wat heb ik in {e['date'][:4]} gebruikt tegen {target}?", [e, *distract],
                f"In je logboek staat op {_nl_date(e['date'])}: {_apps_text(e['apps'])} ({e['remarks'].rstrip('.')}).\n\n"
                f"Bronnen: eigen logboek, {_nl_date(e['date'])}.", "recall_target", {"entry_id": e["id"], "target": target})

    months: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        months[e["date"][:7]].append(e)
    for ym, es in sorted(months.items()):
        if len(es) < 2 or len(es) > 8:
            continue
        y, mo = ym.split("-")
        lines = [f"- {_nl_date(e['date'])}: {_apps_text(e['apps'])}" for e in es]
        add(f"Welke middelen heb ik in {MONTHS[int(mo) - 1]} {y} gebruikt?", list(es),
            "In je logboek staan voor die maand:\n" + "\n".join(lines) + f"\n\nBronnen: eigen logboek, {MONTHS[int(mo) - 1]} {y}.",
            "recall_month", {"month": ym})

    # abstention: a date with no entry -> the model must say so, not invent an application
    have = {e["date"] for e in entries}
    years = sorted(by_year)
    tries = 0
    n_done = 0
    while n_done < n_abstain and tries < n_abstain * 20 and years:
        tries += 1
        y = int(rng.choice(years))
        d = date(y, rng.randint(4, 9), rng.randint(1, 28)).isoformat()
        if d in have:
            continue
        near = sorted(by_year[str(y)], key=lambda e: abs((date.fromisoformat(e["date"]) - date.fromisoformat(d)).days))[:3]
        add(f"Wat heb ik op {_nl_date(d)} gespoten of gestrooid?", list(near),
            f"Voor {_nl_date(d)} staat in de aangeleverde logboekfragmenten geen bespuiting of bemesting. "
            "Ik kan daar dus niets over zeggen zonder te gokken.\n\nBronnen: eigen logboek (geen regel voor die datum).",
            "abstain_day", {"date": d})
        n_done += 1
    return rows


# ── feedback ────────────────────────────────────────────────────────────────────────────

def pair_feedback(records: list[dict]) -> tuple[list[dict], dict]:
    """Thumbs up (chosen) and thumbs down (rejected) answers to the SAME question form a DPO pair."""
    by_q: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"chosen": [], "rejected": []})
    for r in records:
        if r.get("preference") in ("chosen", "rejected") and r.get("answer"):
            by_q[re.sub(r"\s+", " ", r["question"]).strip().lower()][r["preference"]].append(r["answer"])
    pairs = []
    for q, d in by_q.items():
        for c in d["chosen"]:
            for rej in d["rejected"]:
                pairs.append({"prompt": q, "chosen": c, "rejected": rej, "meta": {"source": "feedback"}})
    stats = {"records": len(records), "questions": len(by_q), "pairs": len(pairs),
             "chosen_only_questions": sum(1 for d in by_q.values() if d["chosen"] and not d["rejected"]),
             "rejected_only_questions": sum(1 for d in by_q.values() if d["rejected"] and not d["chosen"])}
    return pairs, stats


# ── driver ──────────────────────────────────────────────────────────────────────────────

def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""), encoding="utf-8")


def split_by_card(rows: list[dict], val_fraction: float = 0.1) -> tuple[list[dict], list[dict]]:
    """Deterministic train/val split BY CARD (both phrasings of one card stay on the same side)."""
    def is_val(row: dict) -> bool:
        key = str(row["meta"].get("card_no", row["meta"].get("entry_id", row["meta"].get("month", row["meta"].get("date", "")))))
        return int(hashlib.md5(key.encode()).hexdigest(), 16) % 1000 < val_fraction * 1000
    train = [r for r in rows if not is_val(r)]
    return train, [r for r in rows if is_val(r)]


def main(argv: list[str] | None = None) -> dict:
    paths = AgentPaths.orchard()
    out_dir = paths.cache_dir / "training"
    out_dir.mkdir(exist_ok=True)

    from pipeline.orchard_agent import SYSTEM_PROMPT
    from pipeline.orchard_eval import load_gold
    from pipeline.orchard_rag import format_context, format_sources, load_index, retrieve

    index = load_index(paths)
    if index is None:
        raise SystemExit("RAG-index ontbreekt.")
    records = [json.loads(line) for line in (paths.cache_dir / "orchard_oac_cards.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    gold = load_gold(paths.gold_file)
    doc_id = records[0]["doc_id"]
    held_out = gold_card_numbers(gold, doc_id)

    datasets, skipped = build_card_datasets(records, lambda q: retrieve(q, index, k=6), format_context, format_sources,
                                            SYSTEM_PROMPT, held_out, index.chunk_by_id)
    report: dict = {"cards": len(records), "held_out_gold": sorted(held_out), "skipped": dict(skipped), "files": {}}
    for name, rows in datasets.items():
        train, val = split_by_card(rows)
        write_jsonl(out_dir / f"{name}_train.jsonl", train)
        write_jsonl(out_dir / f"{name}_val.jsonl", val)
        report["files"][name] = {"train": len(train), "val": len(val)}

    db = paths.logbooks_dir / "orchard_logbook.db"
    if db.exists():
        entries = load_logbook(db)
        rows = build_logbook_dataset(entries, SYSTEM_PROMPT)
        train, val = split_by_card(rows)
        write_jsonl(out_dir / "LOCALONLY_logbook_sft_train.jsonl", train)
        write_jsonl(out_dir / "LOCALONLY_logbook_sft_val.jsonl", val)
        report["files"]["logbook_sft (LOCAL ONLY)"] = {"train": len(train), "val": len(val),
                                                       "kinds": dict(Counter(r["meta"]["kind"] for r in rows)),
                                                       "usable_entries": len(entries),
                                                       "human_verified_entries": sum(e["verified"] for e in entries)}

    fb_records = []
    for f in sorted(paths.cache_dir.glob("orchard_dpo_feedback*.jsonl")):
        fb_records += [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    pairs, fb_stats = pair_feedback(fb_records)
    write_jsonl(out_dir / "dpo_feedback.jsonl", pairs)
    report["feedback"] = fb_stats
    (out_dir / "training_data_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return report


if __name__ == "__main__":
    main()
