"""Verzamelt duim-omhoog/omlaag-feedback op chatbot-antwoorden als ruwe voorkeurssignalen voor
een toekomstige DPO-trainingsronde (design doc Sec B.7/G.6, roadmapstap 7 in Deel E).

Elke klik wordt als ÉÉN kant van een voorkeurspaar weggeschreven naar
``orchard_dpo_feedback.jsonl`` -- een duim-omhoog markeert het getoonde antwoord als
"chosen", een duim-omlaag als "rejected" (het antwoord zelf blijft zichtbaar, er wordt niets
opnieuw gegenereerd). Dit bestand is zelf nog GEEN trainingsklare DPO-dataset: een losse klik
geeft maar één kant van een paar. Een toekomstige dataset-builder (nog te schrijven, zie design
doc Deel F #11) groepeert deze records per (vergelijkbare) vraag en vormt daar pas echte
(chosen, rejected)-paren uit. Dit bestand is dus een VERZAMELMECHANISME, geen trainingsstap op
zich -- zelfde "nooit een halve waarheid als compleet voorstellen"-discipline als de rest van
dit project.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.paths import AgentPaths

FEEDBACK_FILENAME = "orchard_dpo_feedback.jsonl"
VALID_PREFERENCES = ("chosen", "rejected")


@dataclass
class FeedbackRecord:
    timestamp: str
    question: str
    answer: str
    reasoning: str
    sources: list[str]
    tool_calls: list[str]
    grounding: str
    preference: str  # "chosen" (duim omhoog) | "rejected" (duim omlaag)


def feedback_file_path(paths: AgentPaths | None = None) -> Path:
    paths = paths or AgentPaths.orchard()
    return paths.cache_dir / FEEDBACK_FILENAME


def build_feedback_record(
    question: str, answer: str, reasoning: str, sources: list[str], tool_calls: list[str],
    grounding: str, preference: str, timestamp: str | None = None,
) -> FeedbackRecord:
    """Pure: assembles a FeedbackRecord -- split out from save_feedback() so the record shape
    itself is unit-testable without touching the filesystem. Raises ValueError on an invalid
    `preference` rather than silently writing an unusable training row."""
    if preference not in VALID_PREFERENCES:
        raise ValueError(f"preference must be one of {VALID_PREFERENCES}, got {preference!r}")
    return FeedbackRecord(
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        question=question, answer=answer, reasoning=reasoning,
        sources=list(sources), tool_calls=list(tool_calls), grounding=grounding,
        preference=preference,
    )


def save_feedback(record: FeedbackRecord, paths: AgentPaths | None = None) -> Path:
    """Appends `record` as one JSON line to the feedback file (created on first use). Returns
    the path written to, so a caller can show/log exactly where it went."""
    path = feedback_file_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
    return path


def load_feedback(paths: AgentPaths | None = None) -> list[FeedbackRecord]:
    """Reads every stored record back -- used by the Help page's "hoeveel feedback is er al
    verzameld"-teller and by any future dataset-builder. Returns [] if the file doesn't exist
    yet (never raises just because no feedback has been given)."""
    path = feedback_file_path(paths)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(FeedbackRecord(**json.loads(line)))
    return records
