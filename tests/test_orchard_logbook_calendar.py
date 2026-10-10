"""Tests of the logbook calendar ("wat deed ik rond deze tijd?"): pure functions on synthetic entries, a temporary SQLite database, the tool and the page."""
from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from streamlit.testing.v1 import AppTest  # noqa: E402

from pipeline.orchard_logbook_calendar import (CAVEAT, build_calendar, calendar_facts, dedupe_entries, format_calendar,  # noqa: E402
                                               load_calendar_data, parse_calendar_arg, purposes_of)
from pipeline.orchard_patterns import LogEntry  # noqa: E402

_ID = iter(range(1, 10_000))


def _e(iso, apps, remarks=""):
    return LogEntry(id=next(_ID), jaar=iso[:4], datum_iso=iso, opmerkingen=remarks, toepassingen=[(m, h) for m, h in apps])


def _history(years=range(2015, 2021), extra_year_entries=8):
    """Every year: copper + zinc twice in November (the second 7 days after the first), plus filler so the year counts as covered."""
    out = []
    for y in years:
        out += [_e(f"{y}-11-05", [("Koper", "1 ltr"), ("Zinc", "1 kg")], "Tegen pseudomonas en bladval."),
                _e(f"{y}-11-12", [("Koper", "1 ltr")], "Tegen pseudomonas.")]
        out += [_e(f"{y}-05-{d:02d}", [("Ureum", "1 kg")]) for d in range(1, extra_year_entries)]
    return out


def test_purposes_skip_weather_and_leading_tegen():
    assert purposes_of("Tegen pseudomonas en bladval.") == ["pseudomonas", "bladval"]
    assert purposes_of("Tegen hagelschot en tegen rupsen. Geen wind.") == ["hagelschot", "rupsen"]
    assert purposes_of("Tegen pseudomonas, een beetje wind.") == ["pseudomonas"]
    assert purposes_of("") == []


def test_duplicates_on_other_pages_count_once_but_same_page_twice_stays():
    a = _e("2020-03-16", [("Koper", "1 ltr")])
    b = _e("2020-03-16", [("koper", "1 LTR")])     # same application from a second scan
    c = _e("2020-03-17", [("Koper", "1 ltr")])
    d = _e("2020-03-17", [("Koper", "1 ltr")])     # genuinely twice on the same page
    kept, removed = dedupe_entries([a, b, c, d], page_ids={a.id: 1, b.id: 2, c.id: 1, d.id: 1})
    assert removed == 1 and {e.id for e in kept} == {a.id, c.id, d.id}
    assert dedupe_entries([a, c])[1] == 0


def test_calendar_counts_years_intervals_and_purposes():
    rep = build_calendar(_history(), date(2026, 11, 10), 15)
    assert rep.history_years == tuple(range(2015, 2021))
    koper = next(p for p in rep.products if p.middel == "Koper")
    assert len(koper.years) == 6 and koper.applications == 12 and koper.median_interval_days == 7
    assert dict(koper.purposes) == {"bladval": 6, "pseudomonas": 6}
    assert next(p for p in rep.products if p.middel == "Zink").middel == "Zink"      # "Zinc" is normalised
    assert all(p.middel != "Ureum" for p in rep.products)                          # May is outside the window


def test_this_year_comparison_flags_what_is_usual_but_missing():
    entries = _history() + [_e(f"2026-05-{d:02d}", [("Ureum", "1 kg")]) for d in range(1, 10)]   # 2026 has logbook lines, but no copper yet
    rep = build_calendar(entries, date(2026, 11, 10), 15)
    assert rep.this_year_comparable and [p.middel for p in rep.missing_this_year][:1] == ["Koper"]
    assert "dit jaar nog niet in het logboek" in format_calendar(rep)
    done = build_calendar(entries + [_e("2026-11-03", [("Koper", "1 ltr")])], date(2026, 11, 10), 15)
    assert done.missing_this_year == [] or all(p.middel != "Koper" for p in done.missing_this_year)


def test_an_empty_current_year_is_not_reported_as_missing_everything():
    rep = build_calendar(_history(), date(2026, 11, 10), 15)
    assert not rep.this_year_comparable and rep.missing_this_year == []
    assert "te weinig om te zeggen wat er nog ontbreekt" in format_calendar(rep)


def test_a_year_with_almost_no_lines_is_not_a_logbook_year():
    entries = _history() + [_e("2024-11-05", [("Koper", "1 ltr")])]
    entries = [e for e in entries if e.date.year != 2018] + [_e("2018-11-05", [("Koper", "1 ltr")])]
    rep = build_calendar(entries, date(2026, 11, 10), 15)
    assert 2018 not in rep.history_years and 2024 not in rep.history_years


def test_output_never_contains_quantities_and_always_the_caveat():
    text = format_calendar(build_calendar(_history(), date(2026, 11, 10), 15))
    assert "ltr" not in text and "1 kg" not in text and CAVEAT in text
    assert "in 6 van 6 jaar" in text


def test_feb_29_reference_date_does_not_crash():
    assert build_calendar(_history(), date(2024, 2, 29), 10).ref == date(2024, 2, 29)


def test_not_enough_history_says_so():
    assert "te weinig jaren" in format_calendar(build_calendar([], date(2026, 11, 10)))


def test_parse_calendar_arg():
    today = date(2026, 10, 10)
    assert parse_calendar_arg(None, today) == (today, 14)
    assert parse_calendar_arg("november", today) == (date(2026, 11, 15), 15)
    assert parse_calendar_arg("wat doe ik in maart?", today) == (date(2026, 3, 15), 15)
    assert parse_calendar_arg("2026-12-01", today) == (date(2026, 12, 1), 14)
    assert parse_calendar_arg("blabla", today) == (today, 14)


def _make_db(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript("""
        create table pages(id integer primary key, jaar text, bestand text, pagina integer);
        create table entries(id integer primary key, page_id integer, datum_iso text, opmerkingen text, onzeker integer default 0, geverifieerd integer default 0);
        create table toepassingen(id integer primary key, entry_id integer, volgorde integer, middel text, hoeveelheid text);
    """)
    eid = 0
    for page, (jaar, bestand) in enumerate([(y, f"jaar {y}.pdf") for y in range(2015, 2021)], start=1):
        con.execute("insert into pages values (?,?,?,1)", (page, str(jaar), bestand))
        for e in [x for x in _history(years=[jaar]) ]:
            eid += 1
            con.execute("insert into entries(id, page_id, datum_iso, opmerkingen) values (?,?,?,?)", (eid, page, e.datum_iso, e.opmerkingen))
            for i, (m, h) in enumerate(e.toepassingen):
                con.execute("insert into toepassingen(entry_id, volgorde, middel, hoeveelheid) values (?,?,?,?)", (eid, i, m, h))
    # 2020 scanned twice: a second page with copies of the same lines
    con.execute("insert into pages values (99, '2020', 'jaar 2020-2.pdf', 1)")
    for e in _history(years=[2020]):
        eid += 1
        con.execute("insert into entries(id, page_id, datum_iso, opmerkingen) values (?,?,?,?)", (eid, 99, e.datum_iso, e.opmerkingen))
        for i, (m, h) in enumerate(e.toepassingen):
            con.execute("insert into toepassingen(entry_id, volgorde, middel, hoeveelheid) values (?,?,?,?)", (eid, i, m, h))
    con.commit()
    con.close()
    return path


@pytest.fixture()
def db(tmp_path):
    return _make_db(tmp_path / "orchard_logbook.db")


def test_load_calendar_data_removes_the_double_scan(db):
    data = load_calendar_data(db)
    assert data.removed_duplicates == 9 + 0 and data.total == len(data.entries) + data.removed_duplicates and data.verified == 0


def test_calendar_facts_from_a_database(db):
    text = calendar_facts("november", db, today=date(2026, 10, 10))
    assert "Koper" in text and "in 6 van 6 jaar" in text and "0 van" in text and "9 dubbel ingescande" in text


def test_tool_is_only_offered_when_the_logbook_is_enabled(monkeypatch):
    from pipeline.orchard_tool_catalog import build_tool_catalog
    monkeypatch.delenv("ORCHARD_LOGBOOK_RAG", raising=False)
    assert "logboek_kalender" not in build_tool_catalog(None, None, None)


def test_tool_is_offered_with_the_logbook_flag(monkeypatch, db):
    from pipeline import orchard_logbook_rag as rag
    from pipeline import orchard_logbook_calendar as cal
    from pipeline.orchard_tool_catalog import build_tool_catalog
    monkeypatch.setenv("ORCHARD_LOGBOOK_RAG", "1")
    monkeypatch.setattr(rag, "logbook_enabled", lambda *a, **k: True)
    monkeypatch.setattr(rag, "load_logbook_index", lambda *a, **k: object())
    monkeypatch.setattr(cal, "default_db_path", lambda: db)
    tool = build_tool_catalog(None, None, None)["logboek_kalender"]
    result = tool.fn("november")
    assert "Koper" in result.facts and result.sources


def _page(db_path: str):
    from datetime import date as _d
    from pathlib import Path as _P
    from logbook_calendar_view import render_logbook_calendar
    render_logbook_calendar(_P(db_path), today=_d(2026, 11, 10))


def test_page_section_renders_the_table_and_the_caveat(db):
    import streamlit as st
    st.cache_data.clear()
    at = AppTest.from_function(_page, args=(str(db),), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Wat deed ik rond deze tijd?" in " ".join(s.value for s in at.subheader)
    df = at.dataframe[0].value
    assert "Koper" in set(df["Middel"]) and df.loc[df["Middel"] == "Koper", "Jaren"].iloc[0] == "6 van 6"
    assert any("geen advies" in c.value for c in at.caption)
