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


def _ask(monkeypatch, tmp_path, question):
    """Runs the chat page with a stubbed Ctgb API / weather snapshot / chat store (no network, nothing written to Data/)."""
    import sys

    from pipeline import orchard_ctgb
    from tests.ctgb_fakes import standard_api

    sys.path.insert(0, str(Path(PAGE_PATH).resolve().parent.parent))
    import orchard_common

    api = standard_api()
    monkeypatch.setattr("pipeline.qwen_remote.is_remote_server_up", lambda *a, **k: False)
    monkeypatch.setattr("pipeline.qwen_remote.reconnect_tunnel", lambda *a, **k: (False, "skipped in test"))
    monkeypatch.setattr("pipeline.orchard_chats.save_chat", lambda session: None)
    monkeypatch.setattr("pipeline.orchard_chats.list_chats", lambda *a, **k: [])
    monkeypatch.setattr(orchard_common, "compute_season_snapshot", lambda ctx: {})
    real_lookup = orchard_ctgb.lookup
    monkeypatch.setattr(orchard_ctgb, "lookup", lambda q, client=None, today=None: real_lookup(
        q, orchard_ctgb.CtgbClient(fetch=api.fetch, cache_dir=tmp_path), __import__("datetime").date(2026, 10, 10)))
    at = AppTest.from_file(PAGE_PATH, default_timeout=60).run()
    at.chat_input[0].set_value(question).run()
    return at


def test_a_brand_dosage_question_shows_the_verbatim_ctgb_card_not_model_text(monkeypatch, tmp_path):
    at = _ask(monkeypatch, tmp_path, "Wat is de dosering van Syllit tegen bladvlekkenziekte?")
    assert not at.exception, [e.value for e in at.exception]
    assert any("Officiële gegevens" in e.label for e in at.expander)
    assert any("1,25 L/ha" in m.value and "Syllit 544 SC" in m.value for m in at.markdown)
    assert any("niet door het taalmodel geschreven" in m.value for m in at.markdown)


def test_a_dosage_question_without_a_brand_asks_for_the_brand_and_shows_no_numbers(monkeypatch, tmp_path):
    at = _ask(monkeypatch, tmp_path, "Welk middel moet ik gebruiken tegen luis?")
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    assert "merknaam" in text and "L/ha" not in text and not any("Officiële gegevens" in e.label for e in at.expander)
