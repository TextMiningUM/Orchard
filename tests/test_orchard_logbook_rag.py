"""Logbook RAG: time filter, lexical match, local-only gating."""
from __future__ import annotations

import sqlite3

from pipeline.orchard_logbook_rag import (ENV_FLAG, LogbookIndex, evaluate, format_logbook, format_sources,
                                          load_entries, logbook_enabled, synthetic_items, time_hints)


def e(i, day, apps, remarks="", uncertain=False, verified=False):
    return {"id": i, "date": day, "time": None, "remarks": remarks, "uncertain": uncertain, "verified": verified,
            "apps": [{"middel": a, "hoeveelheid": "1 kg"} for a in apps]}


ENTRIES = [e(1, "2013-05-11", ["Albatros"], "Rij 1 heeft het middel niet gehad."), e(2, "2013-05-22", ["Zwavel", "Ureum"]),
           e(3, "2014-05-02", ["Syllit"], "Tegen bladvalziekte."), e(4, "2014-07-19", ["Ureum"], "30 graden", uncertain=True),
           e(5, "2014-07-19", ["Koper"])]


def test_time_hints_parse_dates_months_and_years():
    h = time_hints("Wat heb ik op 11 mei 2013 gespoten?")
    assert h["dates"] == {"2013-05-11"} and h["years"] == {2013} and h["months"] == {5}
    assert time_hints("middelen in juli 2014")["months"] == {7}
    assert time_hints("wat heb ik gebruikt")["years"] == set()


def test_exact_date_returns_every_entry_of_that_day_and_nothing_else():
    hits, trace = LogbookIndex(ENTRIES).search("Wat heb ik op 19 juli 2014 gespoten?")
    assert {h["id"] for h in hits} == {4, 5} and trace["time_filtered"]


def test_month_filter_and_product_word_scoring():
    index = LogbookIndex(ENTRIES)
    assert {h["id"] for h in index.search("Welke middelen heb ik in mei 2013 gebruikt?")[0]} == {1, 2}
    assert index.search("Wanneer heb ik Syllit gebruikt?")[0][0]["id"] == 3
    assert index.search("Wat heb ik tegen bladvalziekte gedaan?")[0][0]["id"] == 3


def test_when_the_period_has_no_entries_the_filter_is_dropped_and_flagged():
    hits, trace = LogbookIndex(ENTRIES).search("Wat heb ik op 3 maart 2016 gespoten?")
    assert hits and not trace["time_filtered"]


def test_format_flags_uncertain_and_unverified_rows_and_lists_sources():
    text = format_logbook([ENTRIES[3], {**ENTRIES[0], "verified": True}])
    assert "[onzeker gelezen handschrift]" in text and "19 juli 2014" in text
    assert text.count("[nog niet geverifieerd]") == 0 and "Albatros (1 kg)" in text
    assert format_sources(ENTRIES[:2]) == ["eigen logboek, 11 mei 2013", "eigen logboek, 22 mei 2013"]
    assert format_logbook([]) == "(geen logboekregels gevonden)"


def test_local_only_gate_needs_env_flag_and_database(tmp_path, monkeypatch):
    db = tmp_path / "l.db"
    db.write_bytes(b"")
    monkeypatch.delenv(ENV_FLAG, raising=False)
    assert not logbook_enabled(db)
    monkeypatch.setenv(ENV_FLAG, "1")
    assert logbook_enabled(db) and not logbook_enabled(tmp_path / "missing.db")


def test_tool_is_absent_from_the_catalog_unless_enabled(monkeypatch):
    from pipeline.orchard_tool_catalog import build_tool_catalog
    monkeypatch.delenv(ENV_FLAG, raising=False)
    assert "logboek_zoeken" not in build_tool_catalog(None, None, None)


def test_personal_history_questions_are_recognised():
    from pipeline.orchard_logbook_rag import is_personal_history_question as q
    assert q("Wat heb ik op 31 juli 2014 gespoten?") and q("Wat deed ik vorig jaar tegen de kersenvlieg?")
    assert q("Welke middelen heb ik in mei 2014 gebruikt?") and q("Wat staat er in mijn logboek over Syllit?")
    assert not q("Hoe bestrijd ik de kersenvlieg?") and not q("Wat is hagelschot?")


def test_load_entries_reads_the_schema(tmp_path):
    db = tmp_path / "l.db"
    con = sqlite3.connect(db)
    con.executescript("""
        create table entries (id integer primary key, page_id int, datum_ruw text, datum_iso text, tijd text,
                              opmerkingen text, onzeker int, raw_transcript text, geverifieerd int, geverifieerd_op text);
        create table toepassingen (id integer primary key, entry_id int, volgorde int, middel text, hoeveelheid text);
        insert into entries values (1,1,'8 mei','2013-05-08','10.30u','16C',1,'raw',0,null);
        insert into entries values (2,1,'x',null,null,null,0,'raw',0,null);
        insert into toepassingen values (1,1,0,'Ureum','1 kg');
    """)
    con.commit()
    con.close()
    rows = load_entries(db)
    assert len(rows) == 1 and rows[0]["uncertain"] and rows[0]["apps"][0]["middel"] == "Ureum"


def test_synthetic_items_and_evaluation_on_the_toy_log():
    items = synthetic_items(ENTRIES)
    kinds = {i["kind"] for i in items}
    assert kinds == {"day", "month", "target"}
    res = evaluate(LogbookIndex(ENTRIES), items)
    assert res["day"]["full_recall"] == 1.0 and res["month"]["full_recall"] == 1.0
