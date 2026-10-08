"""Unit tests for pipeline.orchard_chats -- saved ChatGPT-style chat sessions."""
from __future__ import annotations

from core.paths import AgentPaths
from pipeline.orchard_chats import (
    ChatSession,
    ChatTurn,
    delete_chat,
    derive_title,
    list_chats,
    load_chat,
    new_chat_id,
    new_chat_session,
    save_chat,
)


# ── derive_title ───────────────────────────────────────────────────────────────────────────
def test_derive_title_short_question_unchanged():
    assert derive_title("Is er vorstrisico?") == "Is er vorstrisico?"


def test_derive_title_truncates_long_question():
    long_q = "Wat is het verschil tussen " + "x" * 80
    title = derive_title(long_q, max_chars=20)
    assert len(title) == 20
    assert title.endswith("…")


def test_derive_title_collapses_whitespace():
    assert derive_title("Is er   vorstrisico  \n deze week?") == "Is er vorstrisico deze week?"


def test_derive_title_empty_question_falls_back():
    assert derive_title("") == "Nieuwe chat"
    assert derive_title("   ") == "Nieuwe chat"


# ── new_chat_id / new_chat_session ────────────────────────────────────────────────────────
def test_new_chat_id_unique():
    assert new_chat_id() != new_chat_id()


def test_new_chat_session_with_question_sets_title():
    session = new_chat_session("Is er vorstrisico?")
    assert session.title == "Is er vorstrisico?"
    assert session.turns == []
    assert session.id


def test_new_chat_session_without_question_generic_title():
    session = new_chat_session()
    assert session.title == "Nieuwe chat"


# ── save_chat / load_chat / list_chats / delete_chat (file I/O, tmp_path-isolated) ─────────
def test_save_and_load_chat_roundtrip(tmp_path):
    paths = AgentPaths.orchard(workspace=tmp_path)
    session = new_chat_session("Is er vorstrisico?")
    session.turns.append(ChatTurn(role="user", content="Is er vorstrisico?", meta={}))
    session.turns.append(ChatTurn(role="assistant", content="Nee.", meta={"grounding": "green"}))

    path = save_chat(session, paths=paths)
    assert path.exists()

    loaded = load_chat(session.id, paths=paths)
    assert loaded is not None
    assert loaded.title == "Is er vorstrisico?"
    assert len(loaded.turns) == 2
    assert loaded.turns[1].meta == {"grounding": "green"}


def test_load_chat_returns_none_for_unknown_id(tmp_path):
    paths = AgentPaths.orchard(workspace=tmp_path)
    assert load_chat("does-not-exist", paths=paths) is None


def test_list_chats_sorted_most_recent_first(tmp_path):
    paths = AgentPaths.orchard(workspace=tmp_path)
    s1 = ChatSession(id="a", title="Oud", created_at="2026-01-01T00:00:00+00:00",
                      updated_at="2026-01-01T00:00:00+00:00", turns=[])
    s2 = ChatSession(id="b", title="Nieuw", created_at="2026-02-01T00:00:00+00:00",
                      updated_at="2026-02-01T00:00:00+00:00", turns=[])
    save_chat(s1, paths=paths)
    save_chat(s2, paths=paths)
    chats = list_chats(paths=paths)
    assert [c["id"] for c in chats] == ["b", "a"]


def test_list_chats_empty_when_no_chats_dir(tmp_path):
    paths = AgentPaths.orchard(workspace=tmp_path)
    assert list_chats(paths=paths) == []


def test_delete_chat_removes_file_and_returns_true(tmp_path):
    paths = AgentPaths.orchard(workspace=tmp_path)
    session = new_chat_session("Vraag")
    save_chat(session, paths=paths)
    assert delete_chat(session.id, paths=paths) is True
    assert load_chat(session.id, paths=paths) is None


def test_delete_chat_returns_false_for_unknown_id(tmp_path):
    paths = AgentPaths.orchard(workspace=tmp_path)
    assert delete_chat("does-not-exist", paths=paths) is False
