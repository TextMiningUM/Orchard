"""Tests of the middel_opzoeken combination (Ctgb rules + own logbook + practice check), the tools, the agent's card channel and the page section."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from pipeline import orchard_ctgb
from pipeline.orchard_ctgb import CtgbClient, lookup
from pipeline.orchard_logbook_calendar import product_history
from pipeline.orchard_middel_lookup import build_advies, format_facts, format_full_card, middel_opzoeken, practice_flags
from tests.ctgb_fakes import FakeApi, detail, log_entries, standard_api, use

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

TODAY = date(2026, 10, 10)


def _client(api, tmp_path):
    return CtgbClient(fetch=api.fetch, cache_dir=tmp_path)


def test_product_history_counts_gaps_purposes_and_season_overlap():
    h = product_history(log_entries(), "Syllit 544 SC", ref=date(2026, 5, 10))
    assert h.applications == 16 and dict(h.per_year) == {2016: 4, 2017: 4, 2018: 4, 2019: 4}
    assert h.names == ("Syllit",) and h.first == date(2016, 4, 2) and h.last == date(2019, 8, 20) and h.covered_years == 4
    assert 7 in h.gaps_days and dict(h.purposes)["bladvlekkenziekte"] == 4
    assert h.near_ref_years == 4                      # 5 and 12 May are within 15 days of 10 May every year
    assert product_history(log_entries(), "Onbekend") is None and product_history(log_entries(), "  ") is None


def test_flags_compare_with_the_most_lenient_limit_and_hide_the_numbers_from_the_model(tmp_path):
    lk = lookup("Syllit", _client(standard_api(), tmp_path), TODAY)
    a = build_advies(log_entries(), "Syllit", TODAY, lk, None)
    kinds = {f.kind for f in a.flags}
    assert kinds == {"aantal", "interval", "periode"}                     # 4 per year > 2, 7 days < 60, April is outside May-September
    count = next(f for f in a.flags if f.kind == "aantal")
    assert "maximaal 2 per teeltseizoen" in count.text and "In 4 van 4 jaren" in count.text and "2016: 4×" in count.text
    assert all("maximaal" not in f.model and "dagen" not in f.model and "mei" not in f.model for f in a.flags)
    facts = format_facts(a)
    for secret in ("maximaal 2", "60 dagen", "1,25", "L/ha", "mei t/m september"):
        assert secret not in facts, secret
    assert "Details staan op de kaart" in facts


def test_a_more_lenient_second_use_removes_the_false_accusation(tmp_path):
    api = FakeApi([("1", "Syllit 544 SC", "2029-06-29T22:00:00.000Z", detail("1", "Syllit 544 SC", [use(per_season=2.0, interval=1, months=(3, 9)), use("WG 2", per_season=5.0, interval=1, months=(3, 9))]))])
    lk = lookup("Syllit", _client(api, tmp_path), TODAY)
    assert build_advies(log_entries(), "Syllit", TODAY, lk, None).flags == []      # cap 5 >= 4 per year, intervals >= 1 day, all months allowed


def test_unknown_limits_are_not_compared(tmp_path):
    api = FakeApi([("1", "Syllit 544 SC", "2029-06-29T22:00:00.000Z", detail("1", "Syllit 544 SC", [use(per_season=None, per_use=3.0, interval=None, months=None)]))])
    lk = lookup("Syllit", _client(api, tmp_path), TODAY)
    assert practice_flags(product_history(log_entries(), "Syllit"), lk.valid_cherry_uses) == []


def test_expired_product_explains_why_there_is_no_comparison(tmp_path):
    lk = lookup("SYLLIT OUD", _client(standard_api(), tmp_path), TODAY)
    a = build_advies(log_entries(), "Syllit", TODAY, lk, None)
    assert a.flags == [] and "geen geldig kers-voorschrift" in a.compare_note
    assert "verlopen" in format_full_card(a) and "niet vergeleken" in format_facts(a)


def test_when_ctgb_is_down_the_own_history_is_still_shown(tmp_path):
    def down(url):
        raise ConnectionError("offline")
    a = middel_opzoeken(log_entries(), "Syllit", client=CtgbClient(fetch=down, cache_dir=tmp_path), today=TODAY)
    assert a.ctgb_error and a.lookup is None and a.history
    assert "niet te bereiken" in format_facts(a) and "Je eigen gebruik" in format_full_card(a) and "niet vergeleken" in a.compare_note


def test_without_a_logbook_only_ctgb_is_reported(tmp_path):
    a = middel_opzoeken(None, "Syllit", client=_client(standard_api(), tmp_path), today=TODAY)
    assert a.history is None and a.lookup.products and "geen toepassingen" in format_facts(a)


def test_full_card_contains_ctgb_numbers_and_own_history(tmp_path):
    a = middel_opzoeken(log_entries(), "Syllit", client=_client(standard_api(), tmp_path), today=TODAY)
    card = format_full_card(a)
    for needle in ("1,25 L/ha", "Je eigen gebruik van 'Syllit'", "16 toepassingen", "Let op: eigen praktijk tegenover het Ctgb-voorschrift", "In 4 van 4 jaren"):
        assert needle in card, needle


# ── tools ─────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def fake_lookup(monkeypatch, tmp_path):
    api = standard_api()
    monkeypatch.setattr(orchard_ctgb, "lookup", lambda q, client=None, today=None: lookup(q, _client(api, tmp_path), TODAY))
    return api


def test_ctgb_toelating_tool_gives_the_card_to_the_user_and_only_status_to_the_model(fake_lookup):
    from pipeline.orchard_tool_catalog import build_tool_catalog
    result = build_tool_catalog(None, None, None)["ctgb_toelating"].fn("Syllit")
    assert "GUARDRAIL" in result.facts and "1,25" not in result.facts and "kaart" in result.facts
    assert "1,25 L/ha" in result.card and result.sources == [orchard_ctgb.SOURCE]


def test_ctgb_toelating_tool_without_name_or_api(monkeypatch):
    from pipeline.orchard_tool_catalog import build_tool_catalog
    tool = build_tool_catalog(None, None, None)["ctgb_toelating"]
    assert "merknaam" in tool.fn(None).facts and not tool.fn("  ").card

    def down(*a, **k):
        raise orchard_ctgb.CtgbUnavailable("offline")
    monkeypatch.setattr(orchard_ctgb, "lookup", down)
    result = tool.fn("Decis")
    assert "GUARDRAIL" in result.facts and "Decis" in result.facts and "niet te bereiken" in result.facts and result.card == ""


def test_check_ctgb_toelating_returns_a_structured_answer(fake_lookup):
    from pipeline.orchard_tools import check_ctgb_toelating
    out = check_ctgb_toelating("Syllit")
    assert out["products"][0]["name"] == "Syllit 544 SC" and out["products"][0]["cherry_uses"] == ["WG 3"] and "1,25 L/ha" in out["card"]
    with pytest.raises(ValueError):
        check_ctgb_toelating("Syllit", gewas="appel")


def test_middel_opzoeken_tool_only_exists_with_the_logbook_flag_and_returns_a_card(monkeypatch, fake_lookup):
    from pipeline import orchard_logbook_calendar as cal, orchard_logbook_rag as rag
    from pipeline.orchard_tool_catalog import build_tool_catalog
    monkeypatch.delenv("ORCHARD_LOGBOOK_RAG", raising=False)
    assert "middel_opzoeken" not in build_tool_catalog(None, None, None)
    monkeypatch.setattr(rag, "logbook_enabled", lambda *a, **k: True)
    monkeypatch.setattr(rag, "load_logbook_index", lambda *a, **k: object())
    monkeypatch.setattr(cal, "load_calendar_data", lambda *a, **k: cal.CalendarData(log_entries(), 0, 0, 0))
    tool = build_tool_catalog(None, None, None)["middel_opzoeken"]
    result = tool.fn("Syllit")
    assert "Eigen logboek: 16 toepassingen" in result.facts and "1,25" not in result.facts
    assert "1,25 L/ha" in result.card and "Je eigen gebruik" in result.card and len(result.sources) == 2
    assert "Geen merknaam" in tool.fn("").facts


# ── the agent hands tool cards to the UI, not to the model ──────────────────────────────────────────
def test_agent_collects_tool_cards_and_the_model_never_sees_them(monkeypatch, fake_lookup):
    from pipeline import orchard_agent
    seen_prompts = []
    replies = iter(['{"call_tool": "ctgb_toelating", "args": "Syllit"}', "Zie de kaart voor de voorwaarden en het etiket. Bronnen: Ctgb."])

    def fake_generate(messages=None, **kwargs):
        seen_prompts.append(messages[-1]["content"])
        return next(replies)
    monkeypatch.setattr(orchard_agent, "generate_remote", fake_generate)
    resp = orchard_agent.ask_orchard_advisor("Wat mag ik met Syllit?", ctx=None)
    assert resp.tool_calls == ["ctgb_toelating"] and len(resp.cards) == 1 and "1,25 L/ha" in resp.cards[0]
    assert "Tool-resultaat (ctgb_toelating)" in seen_prompts[-1] and "1,25" not in seen_prompts[-1] and "L/ha" not in seen_prompts[-1]


# ── page section ──────────────────────────────────────────────────────────────────────────────────
def _page():
    from tests.ctgb_fakes import log_entries as entries
    from datetime import date as _d
    from ctgb_lookup_view import render_ctgb_lookup
    render_ctgb_lookup(entries(), today=_d(2026, 10, 10))


@pytest.fixture()
def page_env(monkeypatch, tmp_path):
    import streamlit as st
    import ctgb_lookup_view
    st.cache_data.clear()
    api = standard_api()
    monkeypatch.setattr(ctgb_lookup_view, "lookup", lambda q: lookup(q, _client(api, tmp_path), TODAY))
    yield api
    st.cache_data.clear()


def test_page_lists_own_products_and_stays_quiet_until_you_search(page_env):
    at = AppTest.from_function(_page, default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Syllit" in at.selectbox(key="ctgb_pick").options and "Ureum" not in at.selectbox(key="ctgb_pick").options     # fertiliser is not a Ctgb product
    assert not at.dataframe and not page_env.calls


def test_page_search_shows_ctgb_table_card_history_and_practice_warning(page_env):
    at = AppTest.from_function(_page, default_timeout=60).run()
    at.text_input(key="ctgb_typed").set_value("Syllit")
    at = at.run()
    at.button(key="ctgb_go").click()
    at = at.run()
    assert not at.exception, [e.value for e in at.exception]
    row = at.dataframe[0].value.iloc[0]
    assert row["Middel"] == "Syllit 544 SC" and row["Max. dosis"] == "1,25 L/ha" and row["Min. interval (d)"] == 60
    assert any("Eigen praktijk tegenover het Ctgb-voorschrift" in w.value and "maximaal 2 per teeltseizoen" in w.value for w in at.warning)
    assert [m.label for m in at.metric][:2] == ["Toepassingen", "Jaren gebruikt"] and at.metric[0].value == "16"
    assert any("1,25 L/ha" in m.value for m in at.markdown)


def test_page_shows_an_error_and_no_numbers_when_ctgb_is_down(monkeypatch):
    import streamlit as st
    import ctgb_lookup_view

    def down(q):
        raise orchard_ctgb.CtgbUnavailable("offline")
    st.cache_data.clear()
    monkeypatch.setattr(ctgb_lookup_view, "lookup", down)
    at = AppTest.from_function(_page, default_timeout=60).run()
    at.text_input(key="ctgb_typed").set_value("Syllit")
    at = at.run()
    at.button(key="ctgb_go").click()
    at = at.run()
    assert any("niet te bereiken" in e.value for e in at.error) and not at.dataframe
    st.cache_data.clear()
