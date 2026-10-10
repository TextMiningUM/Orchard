"""Tests of the Ctgb lookup (open MST public API), the model-safe facts / verbatim card split, and the middel_opzoeken combination (no network)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from tests.ctgb_fakes import CHERRY_TREE, CRESS_TREE, FRUIT_TREE, NURSERY_TREE, FakeApi, detail, use

from pipeline.orchard_ctgb import (CtgbClient, CtgbUnavailable, _date, applies_to_cherry, crop_names, detect_product_names, format_card, format_model_facts, lookup,
                                   parse_use, use_rows)

TODAY = date(2026, 10, 10)


def _api():
    syllit = detail("1", "Syllit 544 SC", [use(), use("WG 4", "Bloembol- en bloemknolgewassen", crops=CRESS_TREE, dose=1.0),
                                           use("WG 9", "Boomkwekerijgewassen", crops=NURSERY_TREE, dose=2.0)])
    old = detail("2", "SYLLIT OUD", [use("WG 1", "Kers", dose=1.5, per_season=3.0, interval=21, phi=7)], reg=99)
    veg = detail("3", "Syllit (vrijstelling sla)", [use("WG 7", "Sla", crops=CRESS_TREE)], reg=55)
    return FakeApi([("1", "Syllit 544 SC", "2029-06-29T22:00:00.000Z", syllit), ("2", "SYLLIT OUD", "2024-04-29T22:00:00.000Z", old),
                    ("3", "Syllit (vrijstelling sla)", "2026-09-27T22:00:00.000Z", veg)])


def _client(api, tmp_path, ttl=7, now=None):
    return CtgbClient(fetch=api.fetch, cache_dir=tmp_path, ttl_days=ttl, now=now)


def test_dates_are_rounded_to_the_dutch_calendar_day():
    assert _date("2029-06-29T22:00:00.000Z") == date(2029, 6, 30)        # summer: midnight CEST
    assert _date("2029-12-31T23:00:00Z") == date(2030, 1, 1)             # winter: midnight CET
    assert _date(None) is None and _date("rommel") is None


def test_garden_cress_is_not_cherry_and_groups_are_expanded():
    assert not applies_to_cherry(crop_names(CRESS_TREE))
    assert applies_to_cherry(crop_names(CHERRY_TREE)) and applies_to_cherry(crop_names(FRUIT_TREE))


def test_parse_use_reads_the_regulatory_fields_verbatim():
    u = parse_use(use(per_season=None, per_use=3.0, interval=None, phi=None, months=None, bbch=None, restrictions=["Niet bij wind > 3 Bft"]))
    assert u.cherry and u.explicit_cherry and u.dose == 1.25 and u.dose_unit == "L/ha"
    assert u.per_season is None and u.per_use == 3.0 and u.min_interval_days is None and u.phi_days is None and u.month_from is None
    assert u.restrictions == ("Niet bij wind > 3 Bft",) and u.organisms and "Kersenbladvlekkenziekte" in u.organisms[0]


def test_tree_nursery_use_is_not_a_cherry_production_use_but_fruit_trees_are():
    assert not parse_use(use("WG 9", "Boomkwekerijgewassen", crops=NURSERY_TREE)).cherry
    assert parse_use(use("WG 6", "Vruchtbomen en -struiken", crops=FRUIT_TREE)).cherry


def test_lookup_shows_valid_products_first_and_hides_expired_without_cherry_use(tmp_path):
    lk = lookup("Syllit", _client(_api(), tmp_path), TODAY)
    assert lk.products[0].name == "Syllit 544 SC" and lk.hidden_expired == 1 and {p.name for p in lk.products} == {"Syllit 544 SC", "SYLLIT OUD"}
    main = next(p for p in lk.products if p.name == "Syllit 544 SC")
    assert not main.expired and main.expiration == date(2029, 6, 30) and [u.name for u in main.cherry_uses] == ["WG 3"]
    assert next(p for p in lk.products if p.name == "SYLLIT OUD").expired
    assert lk.valid_cherry_uses and all(not p.expired for p in lk.valid_products)


def test_card_has_the_numbers_verbatim_and_links_and_the_disclaimer(tmp_path):
    card = format_card(lookup("Syllit", _client(_api(), tmp_path), TODAY))
    for needle in ("1,25 L/ha", "2 per teeltseizoen", "60 dagen", "14 dagen", "maart t/m september", "BBCH 71-97", "https://docs.example/1_PW1.pdf",
                   "https://docs.example/1_BESL.pdf", "geldig tot 30 juni 2029", "verlopen op 30 april 2024", "gebruiksaanwijzing/het etiket", "dodine 544 gram per liter"):
        assert needle in card, needle
    assert "Tuinkers" not in card and "1 verlopen toelating(en) zonder kers-voorschrift" in card


def test_model_facts_never_contain_doses_or_limits(tmp_path):
    facts = format_model_facts(lookup("Syllit", _client(_api(), tmp_path), TODAY))
    assert facts.startswith("COMPLIANCE-GUARDRAIL") and "kaart" in facts and "Syllit 544 SC" in facts
    for secret in ("1,25", "L/ha", "60 dagen", "14 dagen", "2 per", "BBCH", "maart"):
        assert secret not in facts, secret


def test_unknown_product_and_only_hidden_matches_are_reported_honestly(tmp_path):
    none = lookup("Ureum", _client(_api(), tmp_path), TODAY)
    assert none.products == [] and "meststof" in format_card(none) and "Geen product gevonden" in format_model_facts(none)
    only_veg = lookup("vrijstelling", _client(_api(), tmp_path), TODAY)
    assert only_veg.products == [] and only_veg.total_matches == 1 and "geen geldige toelating" in format_card(only_veg)


def test_use_rows_for_the_table(tmp_path):
    rows = use_rows(lookup("Syllit", _client(_api(), tmp_path), TODAY))
    main = next(r for r in rows if r["Middel"] == "Syllit 544 SC")
    assert main["Status"] == "geldig" and main["Max. dosis"] == "1,25 L/ha" and main["Min. interval (d)"] == 60 and main["Veiligheidstermijn (d)"] == 14


def test_second_lookup_comes_from_the_disk_cache(tmp_path):
    api = _api()
    lookup("Syllit", _client(api, tmp_path), TODAY)
    first = len(api.calls)
    lookup("Syllit", _client(api, tmp_path), TODAY)
    assert len(api.calls) == first


def test_stale_cache_is_used_with_a_note_when_the_api_is_down(tmp_path):
    api = _api()
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    lookup("Syllit", _client(api, tmp_path, now=lambda: t0), TODAY)

    def down(url):
        raise ConnectionError("offline")
    later = CtgbClient(fetch=down, cache_dir=tmp_path, ttl_days=7, now=lambda: t0 + timedelta(days=30))
    lk = lookup("Syllit", later, TODAY)
    assert lk.products and any("30 dagen oud" in n for n in lk.notes) and "30 dagen oud" in format_card(lk)


def test_no_api_and_no_cache_raises_instead_of_inventing(tmp_path):
    def down(url):
        raise ConnectionError("offline")
    with pytest.raises(CtgbUnavailable):
        lookup("Syllit", CtgbClient(fetch=down, cache_dir=tmp_path), TODAY)


def test_a_corrupt_cache_file_is_ignored(tmp_path):
    api = _api()
    c = _client(api, tmp_path)
    lookup("Syllit", c, TODAY)
    for f in tmp_path.glob("*.json"):
        f.write_text("{kapot", encoding="utf-8")
    assert lookup("Syllit", _client(api, tmp_path), TODAY).products


def test_one_malformed_detail_does_not_hide_the_others(tmp_path):
    api = _api()
    api.items[0] = ("1", "Syllit 544 SC", "2029-06-29T22:00:00.000Z", {"data": {"id": "1", "uses": "kapot"}})
    client = _client(api, tmp_path)
    lk = lookup("Syllit", client, TODAY)
    assert {p.name for p in lk.products} == {"SYLLIT OUD"} and any("kon niet worden gelezen" in n for n in lk.notes)


def test_detect_product_names():
    known = {"syllit", "movento"}
    assert detect_product_names("Wat is de dosering van Syllit tegen bladvlekken?", known) == ["Syllit"]
    assert detect_product_names("mag ik movento nog gebruiken?", known) == ["movento"]
    assert detect_product_names("Welk middel tegen luis?", known) == []
    assert detect_product_names("Is Teppeki toegelaten voor kers?", known) == ["Teppeki"]


def test_cache_file_content_is_plain_json(tmp_path):
    lookup("Syllit", _client(_api(), tmp_path), TODAY)
    files = list(tmp_path.glob("*.json"))
    assert files and all({"url", "fetched_at", "payload"} <= set(json.loads(f.read_text(encoding="utf-8"))) for f in files)
