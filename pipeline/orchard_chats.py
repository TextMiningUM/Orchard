"""Opgeslagen chatsessies voor "Vraag de Adviseur" (design doc Sec A.6/B.9, 2026-10-09) --
ChatGPT-stijl: elke chat wordt automatisch bewaard, een "Nieuwe chat"-knop start een verse
sessie, en eerdere chats staan in de zijbalk om te hervatten.

Eén JSON-bestand per chat in ``Data/Orchard/OrchardChats/<chat_id>.json`` (gitignored --
bevat mogelijk echte vragen over de eigen boomgaard). Puur bestand-gebaseerd (geen database
nodig op deze schaal) -- dezelfde eenvoud-eerst-keuze als `orchard_settings.json`.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.paths import AgentPaths

MAX_TITLE_CHARS = 60


@dataclass
class ChatTurn:
    role: str  # "user" | "assistant"
    content: str
    meta: dict = field(default_factory=dict)


@dataclass
class ChatSession:
    id: str
    title: str
    created_at: str
    updated_at: str
    turns: list[ChatTurn] = field(default_factory=list)


def _chats_dir(paths: AgentPaths | None = None) -> Path:
    paths = paths or AgentPaths.orchard()
    return paths.chats_dir


def new_chat_id() -> str:
    """A sortable-ish, collision-safe id: timestamp prefix (for free chronological listing
    even without reading file contents) + a short random suffix."""
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"


def derive_title(first_question: str, max_chars: int = MAX_TITLE_CHARS) -> str:
    """Pure: turns the first user question into a short chat title -- collapses whitespace,
    truncates with an ellipsis, falls back to a generic label for an empty/whitespace-only
    question rather than showing a blank title in the sidebar."""
    cleaned = re.sub(r"\s+", " ", (first_question or "").strip())
    if not cleaned:
        return "Nieuwe chat"
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def new_chat_session(first_question: str | None = None) -> ChatSession:
    """Pure: builds a fresh, empty ChatSession (not yet saved to disk -- call save_chat() for
    that once it has at least one turn)."""
    now = datetime.now(timezone.utc).isoformat()
    title = derive_title(first_question) if first_question else "Nieuwe chat"
    return ChatSession(id=new_chat_id(), title=title, created_at=now, updated_at=now, turns=[])


def save_chat(session: ChatSession, paths: AgentPaths | None = None) -> Path:
    """Writes `session` to its own JSON file (overwrites if it already exists -- a chat is
    re-saved in full after every new turn, not appended-to, since turns can also gain
    feedback/grounding updates after the fact)."""
    chats_dir = _chats_dir(paths)
    chats_dir.mkdir(parents=True, exist_ok=True)
    path = chats_dir / f"{session.id}.json"
    payload = {
        "id": session.id, "title": session.title, "created_at": session.created_at,
        "updated_at": session.updated_at,
        "turns": [{"role": t.role, "content": t.content, "meta": t.meta} for t in session.turns],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_chat(chat_id: str, paths: AgentPaths | None = None) -> ChatSession | None:
    """Returns None (never raises) if `chat_id` doesn't exist -- a caller can fall back to a
    new chat instead of crashing on a stale/deleted id."""
    path = _chats_dir(paths) / f"{chat_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    turns = [ChatTurn(role=t["role"], content=t["content"], meta=t.get("meta", {})) for t in data["turns"]]
    return ChatSession(
        id=data["id"], title=data["title"], created_at=data["created_at"],
        updated_at=data["updated_at"], turns=turns,
    )


def list_chats(paths: AgentPaths | None = None) -> list[dict]:
    """Returns [{"id", "title", "created_at", "updated_at", "n_turns"}, ...] for every saved
    chat, most-recently-updated first -- cheap metadata-only listing for the sidebar (doesn't
    load each chat's full turn history)."""
    chats_dir = _chats_dir(paths)
    if not chats_dir.exists():
        return []
    rows = []
    for p in chats_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        rows.append({
            "id": data.get("id", p.stem), "title": data.get("title", "Chat"),
            "created_at": data.get("created_at", ""), "updated_at": data.get("updated_at", ""),
            "n_turns": len(data.get("turns", [])),
        })
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    return rows


def delete_chat(chat_id: str, paths: AgentPaths | None = None) -> bool:
    """Removes a chat's JSON file. Returns False (no-op) if it didn't exist -- never raises on
    a double-delete/already-gone chat."""
    path = _chats_dir(paths) / f"{chat_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True
