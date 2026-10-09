"""Unit tests for the structure logic of the document -> JSON stage (no PDFs, models or network)."""
from __future__ import annotations

from pipeline.ingest import orchard_structure as st
from pipeline.ingest.orchard_structure import (
    MAX_SECTION_WORDS, build_sections, configure_hyphenation, define_chunks, find_repeating_furniture,
    is_furniture, looks_like_caps_heading, make_block, merge_continuations, normalize_text,
)


def para(text, page=1, **extra):
    return make_block("paragraph", text, page, **extra)


def heading(text, level=2, page=1, **extra):
    return make_block("heading", text, page, level=level, **extra)


def build(blocks, title="Doc"):
    doc = {"doc_id": "d", "title": title}
    sections = build_sections(merge_continuations(blocks), "d", title)
    return doc, sections


# ── text normalisation ──────────────────────────────────────────────────────────────────

def test_normalize_joins_hyphenated_line_break_and_drops_zero_width_and_soft_hyphens():
    configure_hyphenation("nl")
    assert normalize_text("contin-\nued werk\u200b") == "continued werk"
    assert normalize_text("onder\u00ad\nstam") == "onderstam"


def test_english_hyphenation_keeps_a_real_compound():
    configure_hyphenation("en")
    try:
        assert normalize_text("shipping long-\ndistance and contin-\nued") == "shipping long-distance and continued"
    finally:
        configure_hyphenation("nl")


# ── continuation across column / page breaks ────────────────────────────────────────────

def test_paragraph_split_over_a_page_break_is_one_paragraph():
    blocks = merge_continuations([para("De schimmel overwintert in", page=1), para("verdroogde vruchten.", page=2)])
    assert len(blocks) == 1
    assert blocks[0]["text"] == "De schimmel overwintert in verdroogde vruchten."
    assert blocks[0]["pages"] == [1, 2]


def test_hyphen_at_the_break_joins_without_space():
    blocks = merge_continuations([para("de beregen-", page=1), para("ing start", page=2)])
    assert blocks[0]["text"] == "de beregening start"


def test_footnote_between_the_two_halves_does_not_break_the_sentence():
    blocks = merge_continuations([
        para("Het is logisch om voor"), make_block("footnote", "Deceased.", 1), para("westelijke teelt te schrijven."),
    ])
    prose = [b for b in blocks if b["kind"] == "paragraph"]
    assert [b["text"] for b in prose] == ["Het is logisch om voor westelijke teelt te schrijven."]


def test_lowercase_paragraph_attaches_to_the_open_paragraph_across_a_caption_and_a_paragraph():
    blocks = merge_continuations([
        para("In areas where trees freeze"),
        make_block("caption", "FIGURE 5.--Overgrowth.", 1),
        para("Dit is een losse, afgesloten zin."),
        para("before hardening is complete, replace the trunk."),
    ])
    texts = [b["text"] for b in blocks if b["kind"] == "paragraph"]
    assert texts[0].endswith("before hardening is complete, replace the trunk.")


def test_a_heading_stops_the_lookback():
    blocks = merge_continuations([para("Een open zin zonder einde"), heading("Nieuw hoofdstuk"),
                                  para("kleine letter begin.")])
    assert [b["text"] for b in blocks if b["kind"] == "paragraph"] == ["Een open zin zonder einde", "kleine letter begin."]


# ── sections and chunks ─────────────────────────────────────────────────────────────────

LONG = " ".join(["Dit is een volledige zin over kersen."] * 8)  # 48 words


def test_sections_follow_the_heading_tree_and_chunks_are_structural_units():
    doc, sections = build([heading("Ziekten", 1), heading("Monilia", 2), para(LONG), heading("Hagelschot", 2), para(LONG)])
    chunks = define_chunks(doc, sections)
    assert [c["title"] for c in chunks] == ["Monilia", "Hagelschot"]
    assert chunks[0]["heading_path"] == ["Ziekten", "Monilia"]
    assert chunks[0]["pages"] == [1]


def test_stub_section_is_merged_into_its_sibling_with_its_heading_kept():
    doc, sections = build([heading("Ziekten", 1), heading("Kort", 2), para("Een korte zin."),
                           heading("Lang", 2), para(LONG)])
    chunks = define_chunks(doc, sections)
    assert len(chunks) == 1 and chunks[0]["merged_stubs"]
    assert "Lang" in chunks[0]["text"] and "Een korte zin." in chunks[0]["text"]


def test_standalone_cards_are_never_merged_or_split():
    blocks = [heading("Kaarten", 2)]
    for n in (1, 2):
        blocks += [heading(f"{n}. Titel", 3, section_type="probleem"), para("Korte kaart.")]
    doc, sections = build(blocks)
    chunks = define_chunks(doc, sections)
    assert [c["type"] for c in chunks] == ["probleem", "probleem"]


def test_oversized_section_is_split_on_paragraph_boundaries_by_default():
    big = [heading("Groot", 2)] + [para(" ".join(["Zin nummer komt hier voor."] * 30)) for _ in range(6)]
    doc, sections = build(big)
    chunks = define_chunks(doc, sections)
    assert len(chunks) >= 2
    assert all(c["word_count"] <= MAX_SECTION_WORDS + 160 for c in chunks)
    assert chunks[0]["title"].endswith(f"(deel 1/{len(chunks)})")


def test_a_supplied_topic_splitter_decides_the_boundaries():
    big = [heading("Groot", 2)] + [para(" ".join(["Zin nummer komt hier voor."] * 30)) for _ in range(6)]
    doc, sections = build(big)
    chunks = define_chunks(doc, sections, split_fn=lambda units: [3])
    assert len(chunks) == 2 and all(c["semantic_split"] for c in chunks)


def test_topic_splitter_never_leaves_a_stub_chunk():
    units = [" ".join(["Zin nummer komt hier voor."] * 30) for _ in range(3)] + ["Kort slot."]
    doc, sections = build([heading("Groot", 2)] + [para(u) for u in units] * 2)
    chunks = define_chunks(doc, sections, split_fn=lambda us: [3, 7])
    assert all(c["word_count"] >= st.MIN_SECTION_WORDS for c in chunks)


def test_tables_and_figures_never_enter_chunk_text_but_are_referenced():
    table = make_block("table", "Ras | Bloei\nKordia | laat", 1, rows=[["Ras", "Bloei"]], table_id="d_t1")
    doc, sections = build([heading("Rassen", 2), para(LONG), table, make_block("figure", "", 1, figure_id="d_f1")])
    chunk = define_chunks(doc, sections)[0]
    assert "Kordia" not in chunk["text"]
    assert chunk["table_ids"] == ["d_t1"] and chunk["figure_ids"] == ["d_f1"]


def test_context_prefix_carries_source_and_section_path():
    doc, sections = build([heading("Ziekten", 1), heading("Monilia", 2), para(LONG)], title="Gids")
    chunk = define_chunks(doc, sections)[0]
    assert chunk["text_with_context"].startswith("Bron: Gids\nSectie: Ziekten > Monilia")


# ── furniture and headings ──────────────────────────────────────────────────────────────

def test_running_header_with_changing_page_number_and_ocr_noise_is_furniture():
    pages = [[f"{n} AGRICULTURE HANDBOOK NO. 442, U.S. DEPT. OF AGRICULTURE"] for n in range(2, 12)]
    pages[3] = ["5 AGRICULTURF HANDBOOK NO. 442, U.S. DEPT. OF AGRICULTURE"]
    keys = find_repeating_furniture(pages)
    assert is_furniture("14 AGRICULTURE HANDBOOK NO. 442, U.S. DEPT. OF AGRICULTURE", keys)
    assert not is_furniture("Monilia overwintert in mummies.", keys)
    assert is_furniture("42", set())


def test_caps_heading_heuristic_rejects_bibliography_entries_and_ocr_garbage():
    assert looks_like_caps_heading("BOTANICAL CLASSIFICATION")
    assert not looks_like_caps_heading("1955. FRESH-FRUIT AND CANNING QUALITIES OF")
    assert not looks_like_caps_heading("INSECTS AND MITES ^^")
    assert not looks_like_caps_heading("LAYER FORMATION IN CHERRY FRUITS DUR-")
    assert not looks_like_caps_heading("This is a normal sentence.")


def test_boilerplate_detector_catches_funding_and_cookie_text():
    assert st.is_boilerplate_paragraph("Dit project is gefinancierd door Horizon 2020 onder subsidieovereenkomst 862850.")
    assert not st.is_boilerplate_paragraph("Monilia overwintert in mummies.")
