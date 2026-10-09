"""The teler's own logbook (Track 2) as a retrieval source for the advisor (design doc Deel F #19).

LOCAL-ONLY by construction: the logbook is real, identifying business data (which product, when, how much, where) and the
public pod deployment must never expose it through the chat. So the ``logboek_zoeken`` tool exists ONLY when the
environment variable ``ORCHARD_LOGBOOK_RAG=1`` is set AND the database is present -- it is unset on the pod. Nothing here
copies the data anywhere; the index lives in memory.

Retrieval is hybrid and deliberately simple, because logbook questions are about WHEN and WHICH PRODUCT rather than meaning:
  * time hints in the question ("mei 2013", "11 mei 2013", "in 2019") are a HARD filter (all hints must match; if nothing
    matches the hints, the filter is dropped so the model can say it is not in the logbook instead of guessing),
  * product / target words ("Syllit", "kersenluis") score lexically against the middelen and the remarks,
  * dense similarity (the same bge-m3 embedder as the knowledge base) breaks ties.
Every fragment is labelled with its date and flagged when the handwritten transcription is uncertain or unverified.
"""
from __future__ import annotations

import os
import re
import sqlite3
import unicodedata
from pathlib import Path

import numpy as np

ENV_FLAG = "ORCHARD_LOGBOOK_RAG"
MONTHS = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober",
          "november", "december"]
_MONTH_NO = {m: i + 1 for i, m in enumerate(MONTHS)} | {"mrt": 3, "sept": 9, "okt": 10}
_STOP = {"heb", "ben", "het", "een", "van", "voor", "met", "wat", "welke", "hoe", "waar", "wanneer", "gebruikt", "gespoten",
         "gestrooid", "mijn", "eigen", "logboek", "tegen", "toen", "deed", "maand", "jaar", "keer", "vaak", "alle", "dat", "die"}


def fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "")
    return re.sub(r"\s+", " ", "".join(c for c in folded if not unicodedata.combining(c)).lower()).strip()


def nl_date(iso: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{d} {MONTHS[m - 1]} {y}"


def logbook_enabled(db_path: Path | None = None) -> bool:
    if os.environ.get(ENV_FLAG) != "1":
        return False
    if db_path is None:
        from core.paths import AgentPaths
        db_path = AgentPaths.orchard().logbooks_dir / "orchard_logbook.db"
    return Path(db_path).exists()


def load_entries(db_path: Path) -> list[dict]:
    """Every dated logbook row with its applications (uncertain ones included, flagged)."""
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    out = []
    for e in con.execute("select * from entries where datum_iso is not null order by datum_iso, id"):
        apps = [dict(a) for a in con.execute(
            "select middel, hoeveelheid from toepassingen where entry_id = ? order by volgorde", (e["id"],))]
        out.append({"id": e["id"], "date": e["datum_iso"], "time": e["tijd"], "remarks": (e["opmerkingen"] or "").strip(),
                    "apps": apps, "uncertain": bool(e["onzeker"]), "verified": bool(e["geverifieerd"])})
    con.close()
    return out


def apps_text(apps: list[dict]) -> str:
    return ", ".join(f"{a['middel']} ({a['hoeveelheid']})" if a.get("hoeveelheid") else str(a["middel"]) for a in apps) or "(geen middelen)"


def entry_text(e: dict) -> str:
    rem = f" Opmerkingen: {e['remarks']}" if e["remarks"] else ""
    return f"Logboek {nl_date(e['date'])}. Middelen: {apps_text(e['apps'])}.{rem}"


def time_hints(query: str) -> dict:
    """``{"years": {...}, "months": {...}, "dates": {iso...}}`` found in the question."""
    q = fold(query)
    years = {int(y) for y in re.findall(r"\b(20[0-3]\d)\b", q)}
    months = {n for name, n in _MONTH_NO.items() if re.search(rf"\b{name}\b", q)}
    dates = set()
    for d, name, y in re.findall(r"\b(\d{1,2})\s+([a-z]+)\s+(20[0-3]\d)\b", q):
        if name in _MONTH_NO:
            dates.add(f"{int(y):04d}-{_MONTH_NO[name]:02d}-{int(d):02d}")
    return {"years": years, "months": months, "dates": dates}


def _matches_time(e: dict, hints: dict) -> bool:
    y, m, _d = (int(x) for x in e["date"].split("-"))
    if hints["dates"]:
        return e["date"] in hints["dates"]
    return (not hints["years"] or y in hints["years"]) and (not hints["months"] or m in hints["months"])


def _terms(query: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{4,}", fold(query)) if t not in _STOP and not t.isdigit()
            and t not in _MONTH_NO}


def _lexical(e: dict, terms: set[str]) -> float:
    if not terms:
        return 0.0
    hay = fold(" ".join([a["middel"] or "" for a in e["apps"]] + [e["remarks"]]))
    words = hay.split()
    return sum(1 for t in terms if t in hay or (len(t) >= 5 and any(w.startswith(t[:5]) for w in words))) / len(terms)


class LogbookIndex:
    def __init__(self, entries: list[dict], embedder=None, query_prefix: str = ""):
        self.entries = entries
        self.embedder = embedder
        self.query_prefix = query_prefix
        self._emb: np.ndarray | None = None

    def _embeddings(self) -> np.ndarray | None:
        if self.embedder is None:
            return None
        if self._emb is None:
            self._emb = self.embedder.encode([entry_text(e) for e in self.entries], convert_to_numpy=True,
                                             normalize_embeddings=True, batch_size=32, show_progress_bar=False)
        return self._emb

    def search(self, query: str, k: int = 6) -> tuple[list[dict], dict]:
        hints = time_hints(query)
        has_hint = bool(hints["years"] or hints["months"] or hints["dates"])
        pool = [i for i, e in enumerate(self.entries) if _matches_time(e, hints)] if has_hint else list(range(len(self.entries)))
        filtered = bool(has_hint and pool)
        if has_hint and not pool:
            pool = list(range(len(self.entries)))  # nothing in that period: let the model see the nearest rows and say so
        terms = _terms(query)
        emb = self._embeddings()
        dense = np.zeros(len(self.entries))
        if emb is not None:
            q = self.embedder.encode([self.query_prefix + query], convert_to_numpy=True, normalize_embeddings=True)[0]
            dense = emb @ q
        scored = sorted(((float(dense[i]) + 1.0 * _lexical(self.entries[i], terms), i) for i in pool), reverse=True)
        limit = max(k, 8) if hints["dates"] or hints["months"] else k
        hits = [{**self.entries[i], "score": s} for s, i in scored[:limit]]
        return hits, {"hints": {name: sorted(v) for name, v in hints.items()}, "time_filtered": filtered, "terms": sorted(terms)}


def format_logbook(hits: list[dict]) -> str:
    if not hits:
        return "(geen logboekregels gevonden)"
    lines = []
    for h in hits:
        flag = " [onzeker gelezen handschrift]" if h["uncertain"] else (" [nog niet geverifieerd]" if not h["verified"] else "")
        rem = f" Opmerkingen: {h['remarks']}" if h["remarks"] else ""
        lines.append(f"[Logboek {nl_date(h['date'])}]{flag} Middelen: {apps_text(h['apps'])}.{rem}")
    return "\n".join(lines)


def format_sources(hits: list[dict]) -> list[str]:
    return [f"eigen logboek, {nl_date(d)}" for d in sorted({h["date"] for h in hits})]


def is_personal_history_question(query: str) -> bool:
    """Questions about what the teler himself did earlier ("wat heb ik ... gespoten", "mijn logboek", "vorig jaar",
    a concrete date): these must be answered from the logbook, so it is searched up front instead of hoping the model
    decides to call the tool."""
    q = fold(query)
    if re.search(r"\b(heb ik|had ik|deed ik|gebruikte ik|spoot ik|mijn logboek|eigen logboek|vorig jaar|vorige keer|"
                 r"vorige seizoen|eerder gebruikt|vorige maand)\b", q):
        return True
    hints = time_hints(query)
    return bool(hints["dates"] or (hints["years"] and hints["months"]))


_INDEX: LogbookIndex | None = None


def load_logbook_index(embedder=None, query_prefix: str = "", db_path: Path | None = None) -> LogbookIndex | None:
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    if not logbook_enabled(db_path):
        return None
    if db_path is None:
        from core.paths import AgentPaths
        db_path = AgentPaths.orchard().logbooks_dir / "orchard_logbook.db"
    _INDEX = LogbookIndex(load_entries(db_path), embedder, query_prefix)
    return _INDEX


# ── evaluation (synthetic, from the logbook itself) ─────────────────────────────────────

def synthetic_items(entries: list[dict]) -> list[dict]:
    """Questions a grower asks about his own log, with the entries that must come back:
    a day ("Wat heb ik op 11 mei 2013 gespoten?" -> every entry of that date), a month, and a target
    ("...tegen kersenluis" -> the entry whose remark says so)."""
    items = []
    by_date: dict[str, list[int]] = {}
    for e in entries:
        by_date.setdefault(e["date"], []).append(e["id"])
    for d, ids in by_date.items():
        items.append({"kind": "day", "question": f"Wat heb ik op {nl_date(d)} gespoten of gestrooid?", "expected": ids})
    months: dict[str, list[int]] = {}
    for e in entries:
        months.setdefault(e["date"][:7], []).append(e["id"])
    for ym, ids in months.items():
        if 2 <= len(ids) <= 8:
            y, m = ym.split("-")
            items.append({"kind": "month", "question": f"Welke middelen heb ik in {MONTHS[int(m) - 1]} {y} gebruikt?", "expected": ids})
    for e in entries:
        m = re.search(r"\b[Tt]egen ([A-Za-z][A-Za-z\- ]{2,30}?)(?:[.,;]|$)", e["remarks"])
        if m:
            items.append({"kind": "target", "question": f"Wat heb ik in {e['date'][:4]} gebruikt tegen {m.group(1).strip()}?",
                          "expected": [e["id"]]})
    return items


def evaluate(index: LogbookIndex, items: list[dict], k: int = 6) -> dict:
    """Per kind: share of questions for which ALL expected entries are in the top-``k`` (full recall) and the mean recall."""
    stats: dict[str, dict] = {}
    for it in items:
        hits, _ = index.search(it["question"], k=k)
        got = {h["id"] for h in hits[:max(k, len(it["expected"]))]}
        recall = len(set(it["expected"]) & got) / len(it["expected"])
        s = stats.setdefault(it["kind"], {"n": 0, "full": 0, "recall_sum": 0.0})
        s["n"] += 1
        s["full"] += recall == 1.0
        s["recall_sum"] += recall
    return {kind: {"n": s["n"], "full_recall": s["full"] / s["n"], "mean_recall": s["recall_sum"] / s["n"]}
            for kind, s in stats.items()}
