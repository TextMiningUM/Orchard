"""Unit tests for pipeline.ingest.orchard_qc (pure signals; no language model, no network)."""
from __future__ import annotations

from spellchecker import SpellChecker

from pipeline.ingest.orchard_qc import (
    chunk_signals, chunks_to_docs, decide, hyphen_artifacts, indexable, repeated_page_residue, run_qc,
    sentence_issues, sentence_ratio, _compound_known,
)

GOOD = ("Monilia overwintert in verdroogde vruchten aan de boom. Verwijder die mummies in de winter. "
        "Spuit pas als het nat is en de bloei begint.")


def _chunk(text, **extra):
    return {"chunk_id": extra.pop("chunk_id", "c"), "chunk_index": 0, "title": "T", "heading_path": ["T"],
            "type": "prose", "pages": [1], "text": text, **extra}


def _doc(*chunks, language="nl"):
    return {"doc_id": "d", "title": "D", "language": language, "chunks": list(chunks)}


def test_complete_sentences_have_no_issues():
    issues = sentence_issues(GOOD)
    assert issues["n_incomplete"] == 0
    assert sentence_ratio(GOOD) > 0.9


def test_chunk_that_starts_and_ends_mid_sentence_is_flagged_at_both_edges():
    issues = sentence_issues("en direct worden bestreden. Dit is een goede zin. Vermijd na de bloei, indien")
    assert issues["first_incomplete"] and issues["last_incomplete"]
    assert issues["n_incomplete"] == 2


def test_markdown_heading_line_is_not_a_sentence():
    assert sentence_issues("**1. Perceel ligt in een vorstgat**\n\n- Observatie: Bloesem bevriest elk jaar.")["n_incomplete"] == 0


def test_table_like_text_has_low_sentence_ratio():
    assert sentence_ratio("Oktavia 1 3 L 1, 3 4 2 Kordia 4 1 ML 3, 6 5 2 Regina 3 3 L 2 4 4") < 0.1


def test_hyphen_artifacts_ignore_ellipsis_compounds():
    assert len(hyphen_artifacts("regen- kappen en ont- staan")) == 2
    assert hyphen_artifacts("onder- en bovengronds toepasbaar") == []


def test_repeated_header_across_chunks_is_page_residue():
    header = "AGRICULTURE HANDBOOK NO 442 U S DEPT OF AGRICULTURE"
    chunks = [_chunk(f"{header} Zin nummer {i} is hier compleet.") for i in range(5)]
    assert repeated_page_residue(chunks)


def test_dutch_compound_is_known_but_garbage_is_not():
    dic = SpellChecker(language="nl").word_frequency.dictionary
    assert _compound_known("bladmonsters", dic)
    assert not _compound_known("xqzvkjw", dic)


def test_run_qc_fails_incomplete_and_passes_clean_chunks():
    docs = [_doc(_chunk(GOOD, chunk_id="good"), _chunk("begint midden in een zin. Daarna volgt een zin.", chunk_id="bad"))]
    summary = run_qc(docs)
    by_id = {c["chunk_id"]: c["qc"] for c in docs[0]["chunks"]}
    assert by_id["good"]["verdict"] in ("ok", "warn")
    assert by_id["bad"]["verdict"] == "fail" and "page_break" in by_id["bad"]["issues"]
    assert summary["n_chunks"] == 2
    assert indexable(docs[0]["chunks"][0]) and not indexable(docs[0]["chunks"][1])


def test_override_by_chunk_id_changes_verdict():
    docs = [_doc(_chunk("begint midden in een zin. Daarna volgt een zin.", chunk_id="bad"))]
    run_qc(docs, overrides={"bad": "ok"})
    assert docs[0]["chunks"][0]["qc"]["verdict"] == "ok"


def test_bibliography_chunk_is_not_indexed():
    refs = " ".join(f"STOUT, G. L. {1940 + i}. CHERRY BARK. Calif. Dept. Agr. Bul. {i}: 257-260." for i in range(6))
    docs = [_doc(_chunk(refs, chunk_id="refs", title="LITERATURE CITED"))]
    run_qc(docs)
    assert docs[0]["chunks"][0]["qc"]["verdict"] == "references"
    assert not indexable(docs[0]["chunks"][0])


def test_chunks_to_docs_accepts_legacy_index_layout():
    legacy = [{"chunk_id": "x", "doc_id": "a", "language": "en", "section_titles": ["BARK"], "types": ["prose"],
               "text": "Some text.", "pages": [3]}]
    docs = chunks_to_docs(legacy)
    assert docs[0]["language"] == "en"
    assert docs[0]["chunks"][0]["title"] == "BARK" and docs[0]["chunks"][0]["type"] == "prose"
    assert "type" not in legacy[0] and "title" not in legacy[0]  # input untouched


def test_chunk_signals_report_oov_for_garbled_words():
    spell = SpellChecker(language="en")
    s = chunk_signals(_chunk("The flesh of the cherry was \u00f1eshed and bulletm xqzvk wrongly. It was fine."), "en", spell, set())
    assert s["oov_ratio"] > 0.1
    assert decide(_chunk("x"), {**s, "words": 30}, None)[0] in ("fail", "warn")


# ── sentence splitting, repair and OCR-damage detection ─────────────────────────────────

from pipeline.ingest.orchard_qc import (  # noqa: E402
    find_garbled_tokens, qc_sentences, repair_chunk, reset_repairs,
)


def test_qc_sentences_do_not_cut_after_abbreviations_initials_units_or_figure_references():
    assert qc_sentences("Monilinia spp. kunnen vruchtrot veroorzaken. Spuit tijdig.") == [
        "Monilinia spp. kunnen vruchtrot veroorzaken.", "Spuit tijdig."]
    assert len(qc_sentences("De schimmel M. laxa en C. Boutry werken samen. Klaar.")) == 2
    assert len(qc_sentences("Gebruik 5 lb. per boom (fig. 3). Daarna spuiten.")) == 2
    assert len(qc_sentences("Zie de verdeling (table 1, A). Dat is alles.")) == 2
    assert len(qc_sentences("Rehder (Poit. and Turp.) arise from the cross. Klaar.")) == 2


def test_a_lowercase_start_after_a_full_stop_is_still_reported_as_a_broken_sentence():
    issues = sentence_issues("Dit is een complete zin over kersen. en direct worden bestreden.")
    assert issues["n_incomplete"] == 1


def test_repair_drops_edge_fragments_and_stray_labels_without_rewriting():
    chunk = _chunk("en direct worden bestreden. Dit is een goede zin over monilia. Terug. "
                   "Nog een goede zin over bloesem. En dan breekt hij af zonder einde")
    removed = repair_chunk(chunk)
    assert chunk["text"] == "Dit is een goede zin over monilia. Nog een goede zin over bloesem."
    assert "en direct worden bestreden." in removed and "Terug." in removed
    assert chunk["text_raw"].startswith("en direct") and chunk["repairs"] == removed


def test_repair_is_undone_by_reset_so_qc_is_idempotent():
    chunk = _chunk("en direct worden bestreden. Dit is een goede zin over monilia.")
    original = chunk["text"]
    repair_chunk(chunk)
    reset_repairs(chunk)
    assert chunk["text"] == original and "repairs" not in chunk and "text_raw" not in chunk


def test_a_mostly_broken_chunk_is_not_salvaged():
    chunk = _chunk("kapot begin. nog meer kapot. weer iets stuk. Een goede zin over monilia.")
    repair_chunk(chunk)
    assert "kapot begin." in chunk["text"] or chunk["text"].startswith("Een goede")  # only the leading edge goes


def test_bullet_items_of_four_words_without_full_stop_survive_repair():
    chunk = _chunk("- Gemakkelijk te gebruiken en veilig\n- Geen chemische residuen op het fruit")
    assert repair_chunk(chunk) == []


def test_garbled_tokens_are_symbol_damage_or_impossible_letters_but_not_legitimate_rare_words():
    docs = [_doc(_chunk("The tree developn^ent was f(irtilized and \u00f1eshed. Reniform nematodes are rare here."), language="en")]
    spell = {"en": SpellChecker(language="en")}
    garbled = find_garbled_tokens(docs, spell, set())["en"]
    assert "developn^ent" in garbled and "\u00f1eshed" in garbled
    assert not any("reniform" in g.lower() for g in garbled)


def test_missing_period_on_a_chunk_that_is_otherwise_complete_does_not_fail_when_it_is_a_list():
    docs = [_doc(_chunk(GOOD + "\n\n- Gemakkelijk te gebruiken en veilig", chunk_id="x"))]
    run_qc(docs)
    assert docs[0]["chunks"][0]["qc"]["verdict"] in ("ok", "warn")
