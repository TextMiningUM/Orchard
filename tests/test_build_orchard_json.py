"""Unit tests for the extractor helpers in pipeline.ingest.build_orchard_json (synthetic blocks/lines,
tiny temp files; no real PDFs and no models)."""
from __future__ import annotations

from pipeline.ingest import build_orchard_json as bj
from pipeline.ingest.orchard_structure import make_block


def line(text, x0, y0, x1, y1, size=10.0, bold=False):
    return {"text": text, "size": size, "bold": bold, "bbox": (x0, y0, x1, y1),
            "spans": [{"text": text, "size": size, "bold": bold}]}


def raw_block(x0, y0, x1, y1, text="x"):
    return {"bbox": (x0, y0, x1, y1), "lines": [line(text, x0, y0, x1, y1)], "edge": False}


def test_visual_lines_merge_only_when_the_later_piece_continues_to_the_right():
    same_line = bj._merge_visual_lines([line("Oplossing", 43, 256, 98, 268), line("is hier", 99, 257, 160, 268)])
    assert len(same_line) == 1 and same_line[0]["text"] == "Oplossing is hier"
    # overlapping OCR boxes of two stacked lines (second starts at the left margin again) stay separate
    stacked = bj._merge_visual_lines([line("P. ser-", 31, 457, 261, 472), line("rulata Lindl.", 31, 464, 262, 485)])
    assert len(stacked) == 2


def test_drop_cap_is_glued_to_the_next_line():
    lines = bj._merge_drop_caps([line("T", 54, 245, 78, 299, size=44), line("he distribution", 80, 250, 300, 262)])
    assert len(lines) == 1 and lines[0]["text"] == "The distribution"


def test_inline_block_fragment_is_reattached_to_its_line():
    first = {"bbox": (43, 270, 183, 282), "lines": [line("Zwarte kersenluis kan indirect", 43, 270, 183, 282)], "edge": False}
    frag = {"bbox": (183, 270, 327, 282), "lines": [line("\uf0b7 en direct worden bestreden.", 183, 270, 327, 282)], "edge": False}
    merged = bj._merge_inline_blocks([first, frag])
    assert len(merged) == 1
    assert merged[0]["lines"][0]["text"] == "Zwarte kersenluis kan indirect en direct worden bestreden."


def test_two_column_page_is_read_left_column_first_then_right():
    width = 530
    blocks = [raw_block(31, 50, 260, 100, "L1"), raw_block(31, 110, 260, 160, "L2"), raw_block(31, 530, 260, 600, "L3"),
              raw_block(276, 50, 505, 100, "R1"), raw_block(276, 110, 505, 160, "R2"),
              raw_block(176, 240, 372, 260, "HEADING-ACROSS"), raw_block(276, 530, 505, 600, "R3")]
    order = [b["lines"][0]["text"] for b in bj._order_by_columns(blocks, width)]
    # the straddling heading splits the page into two bands; in each band the left column comes first
    assert order == ["L1", "L2", "R1", "R2", "HEADING-ACROSS", "L3", "R3"]


def test_single_column_page_keeps_the_engine_order():
    blocks = [raw_block(50, 50, 480, 90, "A"), raw_block(50, 100, 480, 140, "B"), raw_block(50, 150, 480, 190, "C")]
    assert [b["lines"][0]["text"] for b in bj._order_by_columns(blocks, 530)] == ["A", "B", "C"]


def test_caption_continuation_blocks_are_folded_into_the_caption():
    cap = make_block("caption", "FIGURE 5.--Overgrowth of the interstock by the scion", 1, x=276, y=351, y1=364)
    c1 = make_block("paragraph", "variety. Such overgrowth is found where sweet cherry", 1, x=284, y=362, y1=374)
    c2 = make_block("paragraph", "is topworked high on mahaleb rootstocks. Note the arrow.", 1, x=284, y=367, y1=405)
    body = make_block("paragraph", "before hardening is complete, substitution may be desirable.", 1, x=276, y=438, y1=503)
    out = bj._fold_caption_continuations([cap, c1, c2, body])
    assert [b["kind"] for b in out] == ["caption", "paragraph"]
    assert "Note the arrow." in out[0]["text"]


def test_table_zone_swallows_header_fragments_rows_and_footnotes_but_not_prose():
    prose = "Rain during harvest may cause cracking of the fruits when the weather stays warm and wet afterwards."
    blocks = [
        make_block("caption", "TABLE 1.--Percent of total U.S. production, by", 8),
        make_block("paragraph", "States and years", 8),
        make_block("paragraph", "Percent of total trees", 8),
        make_block("table", "Calif 30 34 27 26", 8, rows=[["Calif"]], source="heuristic"),
        make_block("paragraph", "^From Crop Production, Annual Summaries (CR-FR-2-1).", 8),
        make_block("paragraph", prose, 9),
    ]
    out = bj._group_table_zones(blocks)
    kinds = [b["kind"] for b in out]
    assert kinds == ["caption", "table", "paragraph"]
    assert "Percent of total trees" in out[1]["text"] and out[2]["text"] == prose


def test_ocr_cleanup_fixes_cultivar_quotes_and_photo_ids_but_not_numbers():
    assert bj._clean_ocr_quotes("*Corum' resembles ^SPALDING\\ closely, PN-3067 see 1971") == \
        "'Corum' resembles 'SPALDING' closely, see 1971"


def test_ocr_junk_blocks_are_recognised():
    assert bj._is_ocr_junk("> u td O o")
    assert not bj._is_ocr_junk("In 1950 prices rose.")


def test_missing_full_stop_is_added_only_to_closing_sentences():
    blocks = [make_block("paragraph", "Dit is een afgeronde zin zonder punt", 1),
              make_block("paragraph", "Volgende alinea begint hier.", 1),
              make_block("paragraph", "kort stuk", 1)]
    out = bj._close_unpunctuated(blocks)
    assert out[0]["text"].endswith("zonder punt.") and out[0]["period_added"]
    assert out[2]["text"] == "kort stuk"  # fewer than 6 words: left alone


def test_markdown_cards_become_standalone_sections(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("# Titel\n\n## Groep\n\n" + "".join(
        f"**{n}. Probleem {n}**\n\n- Observatie: iets.\n- Actie: doe iets.\n\n* Bronnen: [Bron](https://x.nl/{n})\n\n"
        for n in (1, 2, 3)), encoding="utf-8")
    ex = bj.extract_markdown(md, "d")
    cards = [b for b in ex.blocks if b["kind"] == "heading" and b.get("section_type") == "probleem"]
    assert [c["text"] for c in cards] == ["1. Probleem 1", "2. Probleem 2", "3. Probleem 3"]
    assert any(b.get("urls") == ["https://x.nl/1"] for b in ex.blocks)


def test_html_chrome_is_removed_and_structure_kept(tmp_path):
    html = tmp_path / "p.html"
    html.write_text(
        "<html><body><nav><ul><li><a href='/a'>Home</a></li><li><a href='/b'>Teelt</a></li><li><a href='/c'>Contact</a></li></ul></nav>"
        "<main><h1>Monilia</h1><p>Monilia overwintert in verdroogde vruchten aan de boom.</p>"
        "<h2>Bestrijding</h2><ul><li>Verwijder alle mummies in de winter.</li></ul>"
        "<table><tr><th>Ras</th><th>Bloei</th></tr><tr><td>Kordia</td><td>laat</td></tr></table>"
        "<p>Lees meer</p></main><footer>© 2026</footer></body></html>", encoding="utf-8")
    ex = bj.extract_html(html, "d")
    kinds = [(b["kind"], b["text"][:20]) for b in ex.blocks]
    assert ("heading", "Monilia") in kinds and ("heading", "Bestrijding") in kinds
    assert any(k == "table" for k, _ in kinds)
    assert not any("Home" in t or "Contact" in t or "Lees meer" in t for _, t in kinds)


def test_manifest_path_is_re_rooted_on_this_machine(tmp_path):
    entry = {"category": "wur", "file_path": "C:\\Users\\someone\\X\\Data\\Orchard\\OrchardKnowledge\\wur\\a.pdf"}
    assert bj.resolve_source_path(entry, tmp_path) == tmp_path / "wur" / "a.pdf"


def test_build_document_end_to_end_without_models():
    ex = bj.Extraction([
        make_block("heading", "Monilia", 1, level=1),
        make_block("paragraph", "Monilia overwintert in verdroogde vruchten aan de boom en in dode twijgen. " * 3, 1),
        make_block("paragraph", "Terug", 1),
    ])
    entry = {"id": "d", "title": "Gids", "category": "x", "language": "nl", "file_path": "a.html"}
    doc = bj.build_document(entry, ex, "html")
    assert doc["chunks"] and "Terug" not in doc["chunks"][0]["text"]
    assert doc["chapters"][0]["title"] == "Monilia"
    assert doc["quality"]["n_chunks"] == len(doc["chunks"])
