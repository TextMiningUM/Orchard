"""Observation-Action-Consequence(-Why / Worst-case) extraction from the numbered problem cards (design doc Deel F #14).

The 200 cards of "Kersenteelt: 100 problemen door het jaar heen" ALREADY have the OAC structure on purpose::

    - Observatie: <what the grower sees>            -> situation / condition
    - Actie: <what to do>                           -> ordered procedure steps
    - Gevolg: <what that achieves>                  -> consequence
    - Waarom: <the mechanism>                       -> why / guidance
    - Slechtste reactie: <what NOT to do>           -> pitfall / worst case
    - Bronnen (bevestigd|deels bevestigd): ...      -> provenance + verification status

so for them extraction is a deterministic parse -- no LLM, nothing invented, every field is a verbatim span of the
chunk. The records come in two shapes: ``orchard_oac_cards.jsonl`` (one OAC tuple per card, for SFT / reflection data)
and ``orchard_reasoning_traces.jsonl`` (the schema ``build_orchard_pg.py`` reads, same as Auto Pilot's reasoning
traces: ``trace.procedures[{step, action, why}]``, ``constraints``, ``warnings``). Prose chunks (handbook, web pages)
need an LLM or a human for this; see ``extract_orchard_oac_llm.py``.

    .venv\\Scripts\\python.exe -m pipeline.ingest.extract_orchard_oac
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.paths import AgentPaths  # noqa: E402

FIELDS = {
    "Observatie": "observation", "Actie": "action", "Gevolg": "consequence", "Waarom": "why",
    "Slechtste reactie": "worst_case",
}
_FIELD_RE = re.compile(r"^-\s*(Observatie|Actie|Gevolg|Waarom|Slechtste reactie|Bronnen)(?:\s*\(([^)]*)\))?:\s*(.*)$")
_NUMBER_RE = re.compile(r"^\s*(\d+)\.\s*(.+)$")
_MIN_STEP_CHARS = 6


def parse_card(chunk: dict) -> dict | None:
    """OAC record for one card chunk, or None when it is not a complete card (missing observation or action)."""
    rec: dict = {}
    sources_status = ""
    for line in chunk["text"].split("\n"):
        m = _FIELD_RE.match(line.strip())
        if not m:
            continue
        name, qualifier, value = m.groups()
        if name == "Bronnen":
            rec["sources"] = value.strip()
            sources_status = (qualifier or "").strip().lower()
        else:
            rec[FIELDS[name]] = value.strip()
    title = chunk.get("title", "")
    heading = (chunk.get("heading_path") or [""])[-1] or title
    num = _NUMBER_RE.match(heading) or _NUMBER_RE.match(title)
    if not (rec.get("observation") and rec.get("action") and num):
        return None
    rec.update(card_no=int(num.group(1)), title=num.group(2).strip(),
               section=(chunk.get("heading_path") or ["", ""])[-2] if len(chunk.get("heading_path") or []) > 1 else "",
               sources_status=sources_status or "onbekend", chunk_id=chunk["chunk_id"], doc_id=chunk["doc_id"])
    rec["steps"] = split_steps(rec["action"])
    return rec


def split_steps(action: str) -> list[str]:
    """Ordered procedure steps of an ``Actie`` line: sentences, then ``;``, then commas. The order is the order in
    the text (cards list actions in the order a grower carries them out). Fragments that are too short are dropped; a
    leading conjunction ("en", "of") is stripped; the first letter is lowercased so steps read as imperatives."""
    parts: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", action.strip()):
        for chunk in sentence.split(";"):
            parts.extend(chunk.split(", "))
    steps = []
    for p in parts:
        p = re.sub(r"^(?:en dan|en daarna|en vervolgens|daarna|vervolgens|en|of|dan)\s+", "", p.strip().rstrip("."), flags=re.I).strip()
        if len(p) >= _MIN_STEP_CHARS:
            steps.append(p[0].lower() + p[1:] if p[:2].isalpha() and not p[:2].isupper() else p)
    return steps


def card_to_trace(rec: dict) -> dict | None:
    """The reasoning-trace form ``build_orchard_pg.py`` consumes (>= 2 ordered steps or None)."""
    if len(rec["steps"]) < 2:
        return None
    why = rec.get("why", "")
    return {
        "source_file": f"{rec['doc_id']}#{rec['card_no']}",
        "chunk_id": rec["chunk_id"],
        "trace": {
            "situation": rec["observation"],
            "procedures": [{"step": i + 1, "action": s, "why": why if i == 0 else ""} for i, s in enumerate(rec["steps"])],
            "constraints": [rec["observation"]],
            "warnings": [rec["worst_case"]] if rec.get("worst_case") else [],
            "consequence": rec.get("consequence", ""),
        },
        "family": rec.get("section", ""),
        "card_title": rec["title"],
        "sources_status": rec["sources_status"],
    }


def extract_cards(chunks: list[dict]) -> tuple[list[dict], list[dict]]:
    records, traces = [], []
    for chunk in chunks:
        if chunk.get("type") != "probleem":
            continue
        rec = parse_card(chunk)
        if not rec:
            continue
        records.append(rec)
        trace = card_to_trace(rec)
        if trace:
            traces.append(trace)
    return records, traces


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def main(paths: AgentPaths | None = None) -> None:
    paths = paths or AgentPaths.orchard()
    chunks = json.loads((paths.cache_dir / "orchard_rag_chunks.json").read_text(encoding="utf-8"))
    records, traces = extract_cards(chunks)
    write_jsonl(paths.cache_dir / "orchard_oac_cards.jsonl", records)
    write_jsonl(paths.cache_dir / "orchard_reasoning_traces.jsonl", traces)
    status = {}
    for r in records:
        status[r["sources_status"]] = status.get(r["sources_status"], 0) + 1
    print(f"OAC: {len(records)} cards parsed, {len(traces)} with >= 2 steps (PG input); verification status: {status}")


if __name__ == "__main__":
    main()
