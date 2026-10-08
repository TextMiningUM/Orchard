"""Unit tests for pipeline.orchard_middelen -- canonicalization/categorization registry +
period-aggregation logic. Synthetic data only."""
from __future__ import annotations

from datetime import date

from pipeline.orchard_patterns import LogEntry
from pipeline.orchard_middelen import (
    CATEGORY_LABELS,
    ToepassingRecord,
    _ONZEKER_OVERIG,
    _PRODUCT_REGISTRY,
    aggregate_middelen,
    build_toepassing_records,
    canonicalize_middel,
    period_key,
)


# ── canonicalize_middel ────────────────────────────────────────────────────────────────────
def test_canonicalize_exact_canonical_name():
    name, cat = canonicalize_middel("Ureum")
    assert name == "Ureum"
    assert cat == "meststof"


def test_canonicalize_known_alias_case_insensitive():
    name, cat = canonicalize_middel("ZINC")
    assert name == "Zink"
    assert cat == "meststof"


def test_canonicalize_strips_ocr_uncertainty_marker():
    name, cat = canonicalize_middel("Folicur [?]")
    assert name == "Folicur"
    assert cat == "fungicide_bactericide"


def test_canonicalize_rovral_ocr_variant():
    name, cat = canonicalize_middel("Roval (BASF)")
    assert name == "Rovral"
    assert cat == "fungicide_bactericide"


def test_canonicalize_unknown_product_goes_to_overig():
    name, cat = canonicalize_middel("Een Compleet Onbekend Product XYZ")
    assert cat == "overig"
    assert name == "Een Compleet Onbekend Product XYZ"


def test_canonicalize_deliberately_uncertain_names_stay_in_overig():
    # Regression test: names the registry explicitly flagged as too uncertain to classify
    # (see _ONZEKER_OVERIG) must never silently resolve to a confident category.
    for raw in _ONZEKER_OVERIG:
        _name, cat = canonicalize_middel(raw)
        assert cat == "overig", f"{raw!r} should stay 'overig', got {cat!r}"


def test_canonicalize_bijen_is_pollination_not_a_product():
    name, cat = canonicalize_middel("2 kasten bijen")
    assert cat == "bestuiving"


def test_category_labels_cover_every_registry_category():
    used_categories = {cat for cat, _aliases in _PRODUCT_REGISTRY.values()}
    assert used_categories <= set(CATEGORY_LABELS)


# ── build_toepassing_records ───────────────────────────────────────────────────────────────
def _entry(id_, iso_date, toepassingen):
    e = LogEntry(id=id_, jaar=iso_date[:4], datum_iso=iso_date, opmerkingen="")
    e.toepassingen = toepassingen
    return e


def test_build_toepassing_records_basic():
    entries = [_entry(1, "2023-05-01", [("Ureum", "1 kg"), ("Calypso", "50 ml")])]
    records = build_toepassing_records(entries)
    assert len(records) == 2
    ureum = next(r for r in records if r.canonical_middel == "Ureum")
    assert ureum.value == 1000.0 and ureum.unit == "g"
    calypso = next(r for r in records if r.canonical_middel == "Calypso")
    assert calypso.value == 50.0 and calypso.unit == "ml"


def test_build_toepassing_records_skips_entries_without_date():
    e = LogEntry(id=1, jaar="2023", datum_iso=None, opmerkingen="")
    e.toepassingen = [("Ureum", "1 kg")]
    assert build_toepassing_records([e]) == []


def test_build_toepassing_records_handles_unparseable_quantity():
    entries = [_entry(1, "2023-05-01", [("Ureum", "onleesbaar")])]
    records = build_toepassing_records(entries)
    assert records[0].value is None
    assert records[0].unit is None


# ── period_key ─────────────────────────────────────────────────────────────────────────────
def test_period_key_week():
    assert period_key(date(2024, 6, 3), "week") == "2024-W23"


def test_period_key_maand():
    assert period_key(date(2024, 6, 3), "maand") == "2024-06"


def test_period_key_kwartaal():
    assert period_key(date(2024, 6, 3), "kwartaal") == "2024-Q2"
    assert period_key(date(2024, 1, 1), "kwartaal") == "2024-Q1"
    assert period_key(date(2024, 12, 31), "kwartaal") == "2024-Q4"


def test_period_key_jaar():
    assert period_key(date(2024, 6, 3), "jaar") == "2024"


def test_period_key_unknown_granularity_raises():
    import pytest
    with pytest.raises(ValueError):
        period_key(date(2024, 1, 1), "decennium")


# ── aggregate_middelen ─────────────────────────────────────────────────────────────────────
def _record(entry_id, iso_date, middel, category, value, unit):
    return ToepassingRecord(
        entry_id=entry_id, date_iso=iso_date, canonical_middel=middel, category=category,
        raw_middel=middel, raw_hoeveelheid="", value=value, unit=unit,
    )


def test_aggregate_middelen_sums_within_same_unit_only():
    records = [
        _record(1, "2024-05-01", "Ureum", "meststof", 1000.0, "g"),
        _record(2, "2024-05-15", "Ureum", "meststof", 500.0, "g"),
        _record(3, "2024-05-20", "Calypso", "insecticide_acaricide", 50.0, "ml"),
    ]
    rows = aggregate_middelen(records, "maand")
    ureum_row = next(r for r in rows if r["middel"] == "Ureum")
    assert ureum_row["periode"] == "2024-05"
    assert ureum_row["aantal"] == 2
    assert ureum_row["totaal_g"] == 1500.0
    assert ureum_row["totaal_ml"] == 0.0


def test_aggregate_middelen_never_mixes_ml_and_g():
    records = [
        _record(1, "2024-05-01", "X", "overig", 100.0, "ml"),
        _record(2, "2024-05-02", "X", "overig", 200.0, "g"),
    ]
    rows = aggregate_middelen(records, "maand")
    assert len(rows) == 1
    assert rows[0]["totaal_ml"] == 100.0
    assert rows[0]["totaal_g"] == 200.0


def test_aggregate_middelen_separates_different_periods():
    records = [
        _record(1, "2024-05-01", "Ureum", "meststof", 1000.0, "g"),
        _record(2, "2024-06-01", "Ureum", "meststof", 500.0, "g"),
    ]
    rows = aggregate_middelen(records, "maand")
    periods = {r["periode"] for r in rows}
    assert periods == {"2024-05", "2024-06"}


def test_aggregate_middelen_counts_unparseable_quantities_without_crashing():
    records = [_record(1, "2024-05-01", "Ureum", "meststof", None, None)]
    rows = aggregate_middelen(records, "jaar")
    assert rows[0]["aantal"] == 1
    assert rows[0]["totaal_g"] == 0.0
