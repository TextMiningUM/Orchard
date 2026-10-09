"""Smoke test for app/pages/3_Vraag_de_Adviseur.py -- confirms the page loads without
crashing after the 2026-10-09 streaming migration (vLLM backend, `ask_orchard_advisor_stream`).
Only checks page LOAD (no chat_input submitted): submitting a prompt would exercise either
`_try_deterministic_route()` (live Open-Meteo network call) or the real Qwen3-8B cloud
server, neither appropriate for the automated suite -- same "no live model/network call"
convention as `tests/test_orchard_agent.py`. `is_remote_server_up`/`reconnect_tunnel` are
monkeypatched purely to avoid a real (if short-timeout) network probe during the test, not
because the page would otherwise fail -- both already degrade gracefully when unreachable."""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

PAGE_PATH = str(Path(__file__).resolve().parent.parent / "app" / "pages" / "3_Vraag_de_Adviseur.py")


def test_page_loads_without_exception(monkeypatch):
    monkeypatch.setattr("pipeline.qwen_remote.is_remote_server_up", lambda *a, **k: False)
    monkeypatch.setattr("pipeline.qwen_remote.reconnect_tunnel", lambda *a, **k: (False, "skipped in test"))

    at = AppTest.from_file(PAGE_PATH)
    at.run(timeout=30)

    assert not at.exception
    assert any("Vraag de Adviseur" in t.value for t in at.title)


def test_chat_input_widget_is_present(monkeypatch):
    monkeypatch.setattr("pipeline.qwen_remote.is_remote_server_up", lambda *a, **k: False)
    monkeypatch.setattr("pipeline.qwen_remote.reconnect_tunnel", lambda *a, **k: (False, "skipped in test"))

    at = AppTest.from_file(PAGE_PATH)
    at.run(timeout=30)

    assert not at.exception
    assert len(at.chat_input) == 1
