"""Unit tests for pipeline.orchard_patterns -- synthetic data only (no dependency on the real,
proprietary logbook database), consistent with this project's testing discipline."""
from __future__ import annotations

import sqlite3

import pytest

from pipeline.orchard_patterns import (
    LogEntry,
    detect_dosage_trend_patterns,
    detect_frequency_trend_patterns,
    detect_monthly_calendar_pattern,
    detect_patterns,
    detect_seasonal_timing_patterns,
    load_entries,
    match_categories,
    parse_hoeveelheid,
)


# ── match_categories ──────────────────────────────────────────────────────────────────────
def test_match_categories_single_keyword():
    assert match_categories("Tegen vruchtrot.") == {"vruchtrot"}


def test_match_categories_multiple_hits():
    cats = match_categories("Tegen luis + suzukii vlieg.")
    assert cats == {"luis", "fruitvliegen"}


def test_match_categories_case_insensitive():
    assert match_categories("TEGEN BLADVLEKKENZIEKTE") == {"bladvlekkenziekte"}


def test_match_categories_no_match():
    assert match_categories("Windstil, 18 graden.") == set()


def test_match_categories_empty_string():
    assert match_categories("") == set()


# ── parse_hoeveelheid ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("1 kg", (1000.0, "g")),
    ("0,6 liter", (600.0, "ml")),
    ("50 ml", (50.0, "ml")),
    ("200 cc", (200.0, "ml")),
    ("300 gram", (300.0, "g")),
    ("0,150 liter", (150.0, "ml")),
    ("15 kg op 200 liter water", (15000.0, "g")),
    ("0,25 ml op 5 liter water", (0.25, "ml")),
])
def test_parse_hoeveelheid_formats(text, expected):
    value, unit = parse_hoeveelheid(text)
    assert value == pytest.approx(expected[0])
    assert unit == expected[1]


def test_parse_hoeveelheid_no_quantity_returns_none():
    assert parse_hoeveelheid("onleesbaar") is None


def test_parse_hoeveelheid_empty_returns_none():
    assert parse_hoeveelheid("") is None
    assert parse_hoeveelheid(None) is None


# ── detect_seasonal_timing_patterns ───────────────────────────────────────────────────────
def _entry(id_, jaar, datum_iso, opmerkingen):
    return LogEntry(id=id_, jaar=jaar, datum_iso=datum_iso, opmerkingen=opmerkingen)


def test_detect_seasonal_timing_finds_earlier_shift():
    # 'tegen fruitvlieg' moves from day ~180 in 2018 to day ~150 in 2022 -> clear "earlier" slope.
    entries = [
        _entry(1, "2018", "2018-06-29", "Tegen kersenvlieg."),  # doy ~180
        _entry(2, "2019", "2018-06-22", "Tegen kersenvlieg."),
        _entry(3, "2020", "2018-06-15", "Tegen kersenvlieg."),
        _entry(4, "2021", "2018-06-08", "Tegen kersenvlieg."),
        _entry(5, "2022", "2018-06-01", "Tegen kersenvlieg."),
    ]
    # fix years properly (datum_iso year must match intended sequence)
    entries = [
        _entry(1, "2018", "2018-06-29", "Tegen kersenvlieg."),
        _entry(2, "2019", "2019-06-22", "Tegen kersenvlieg."),
        _entry(3, "2020", "2020-06-15", "Tegen kersenvlieg."),
        _entry(4, "2021", "2021-06-08", "Tegen kersenvlieg."),
        _entry(5, "2022", "2022-06-01", "Tegen kersenvlieg."),
    ]
    patterns = detect_seasonal_timing_patterns(entries)
    assert len(patterns) == 1
    p = patterns[0]
    assert p.kind == "seizoenstiming"
    assert "vroeger" in p.title
    assert p.importance > 0
    assert set(p.entry_ids) == {1, 2, 3, 4, 5}


def test_detect_seasonal_timing_skips_too_few_years():
    entries = [
        _entry(1, "2021", "2021-06-01", "Tegen kersenvlieg."),
        _entry(2, "2022", "2022-06-01", "Tegen kersenvlieg."),
    ]
    assert detect_seasonal_timing_patterns(entries) == []


def test_detect_seasonal_timing_ignores_entries_without_date():
    entries = [_entry(1, "2021", None, "Tegen kersenvlieg.")]
    assert detect_seasonal_timing_patterns(entries) == []


# ── detect_frequency_trend_patterns ───────────────────────────────────────────────────────
def test_detect_frequency_trend_finds_increasing_pressure():
    entries = []
    eid = 1
    # 1 mention in 2019, growing to 5 mentions in 2023 -> clear rising frequency.
    for year, n in [(2019, 1), (2020, 2), (2021, 3), (2022, 4), (2023, 5)]:
        for i in range(n):
            entries.append(_entry(eid, str(year), f"{year}-06-{10 + i:02d}", "Tegen suzukii fruitvlieg."))
            eid += 1
    patterns = detect_frequency_trend_patterns(entries)
    assert len(patterns) == 1
    assert patterns[0].kind == "frequentie"
    assert "toe" in patterns[0].title


def test_detect_frequency_trend_requires_minimum_years():
    entries = [_entry(1, "2022", "2022-06-01", "Tegen luis.")]
    assert detect_frequency_trend_patterns(entries) == []


# ── detect_dosage_trend_patterns ──────────────────────────────────────────────────────────
def test_detect_dosage_trend_finds_rising_dose():
    entries = []
    eid = 1
    for year, dose_ml in [(2018, 50), (2019, 60), (2020, 80), (2021, 100), (2022, 130)]:
        e = _entry(eid, str(year), f"{year}-05-01", "Voedingssupplement.")
        e.toepassingen.append(("Calypso", f"{dose_ml} ml"))
        entries.append(e)
        eid += 1
    patterns = detect_dosage_trend_patterns(entries)
    assert len(patterns) == 1
    assert patterns[0].kind == "dosering"
    assert "toenemende" in patterns[0].title
    assert "Calypso" in patterns[0].title


def test_detect_dosage_trend_ignores_unparseable_quantities():
    entries = []
    for year in (2018, 2019, 2020, 2021):
        e = _entry(year, str(year), f"{year}-05-01", "")
        e.toepassingen.append(("Mysterystuff", "onleesbaar"))
        entries.append(e)
    assert detect_dosage_trend_patterns(entries) == []


def test_detect_dosage_trend_ignores_flat_dosage():
    entries = []
    for year in (2018, 2019, 2020, 2021, 2022):
        e = _entry(year, str(year), f"{year}-05-01", "")
        e.toepassingen.append(("Ureum", "1 kg"))
        entries.append(e)
    assert detect_dosage_trend_patterns(entries) == []


# ── detect_monthly_calendar_pattern ───────────────────────────────────────────────────────
def test_detect_monthly_calendar_aggregates_by_month():
    entries = [
        _entry(1, "2020", "2020-04-15", "Tegen bladvlekkenziekte."),
        _entry(2, "2021", "2021-04-20", "Tegen bladvlekkenziekte."),
        _entry(3, "2020", "2020-07-10", "Tegen vruchtrot."),
    ]
    pattern = detect_monthly_calendar_pattern(entries)
    assert pattern is not None
    assert pattern.kind == "kalender"
    april_idx = 3  # 0-based index for April
    bladvlek_row = pattern.chart["y"].index("Bladvlekkenziekte")
    assert pattern.chart["z"][bladvlek_row][april_idx] == 2


def test_detect_monthly_calendar_returns_none_when_no_data():
    assert detect_monthly_calendar_pattern([_entry(1, "2020", None, "")]) is None


# ── load_entries (real sqlite schema, in-memory) ──────────────────────────────────────────
def test_load_entries_from_sqlite():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE pages (id INTEGER PRIMARY KEY, jaar TEXT, bestand TEXT, pagina INTEGER);
        CREATE TABLE entries (
            id INTEGER PRIMARY KEY, page_id INTEGER, datum_iso TEXT, opmerkingen TEXT
        );
        CREATE TABLE toepassingen (
            id INTEGER PRIMARY KEY, entry_id INTEGER, volgorde INTEGER, middel TEXT, hoeveelheid TEXT
        );
        INSERT INTO pages VALUES (1, '2020', 'jaar 2020.pdf', 1);
        INSERT INTO entries VALUES (1, 1, '2020-05-01', 'Tegen vruchtrot.');
        INSERT INTO toepassingen VALUES (1, 1, 0, 'Rovral', '300 ml');
        INSERT INTO toepassingen VALUES (2, 1, 1, 'Ureum', '1 kg');
    """)
    entries = load_entries(conn)
    assert len(entries) == 1
    e = entries[0]
    assert e.jaar == "2020"
    assert e.datum_iso == "2020-05-01"
    assert e.toepassingen == [("Rovral", "300 ml"), ("Ureum", "1 kg")]


# ── detect_patterns (top-level orchestration) ─────────────────────────────────────────────
def test_detect_patterns_returns_ranked_list_and_pinned_calendar():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE pages (id INTEGER PRIMARY KEY, jaar TEXT, bestand TEXT, pagina INTEGER);
        CREATE TABLE entries (
            id INTEGER PRIMARY KEY, page_id INTEGER, datum_iso TEXT, opmerkingen TEXT
        );
        CREATE TABLE toepassingen (
            id INTEGER PRIMARY KEY, entry_id INTEGER, volgorde INTEGER, middel TEXT, hoeveelheid TEXT
        );
    """)
    eid = 1
    for year, doy_offset in [(2018, 0), (2019, -5), (2020, -10), (2021, -15), (2022, -20)]:
        conn.execute("INSERT INTO pages VALUES (?, ?, 'x.pdf', 1)", (year, str(year)))
        month_day = f"{year}-06-{max(1, 15 + doy_offset):02d}"
        conn.execute(
            "INSERT INTO entries VALUES (?, ?, ?, ?)",
            (eid, year, month_day, "Tegen kersenvlieg."),
        )
        eid += 1
    conn.commit()
    ranked, calendar = detect_patterns(conn, top_n=3)
    assert len(ranked) >= 1
    assert all(ranked[i].importance >= ranked[i + 1].importance for i in range(len(ranked) - 1))
    assert calendar is not None
    assert calendar.kind == "kalender"
