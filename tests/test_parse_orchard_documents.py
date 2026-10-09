"""Unit tests for pipeline.ingest.parse_orchard_documents -- specifically the markdown
numbered-item structural split (design doc Deel F #18/G.18: "1 chunk per probleem", not a
word-count-based split, so a problem's own sources can never drift onto a neighbour)."""
from __future__ import annotations

from pipeline.ingest.parse_orchard_documents import _parse_markdown, _split_numbered_items


def _write_md(tmp_path, text: str):
    p = tmp_path / "test.md"
    p.write_text(text, encoding="utf-8")
    return p


_NUMBERED_SAMPLE = """## Leeswijzer

Een korte inleiding zonder genummerde items.

## 1. Groep A (1-3)

**1. Eerste probleem**

- Observatie: iets.
- Actie: iets anders.

* Bronnen (bevestigd): [Bron A](https://example.com/a).

**2. Tweede probleem**

- Observatie: nog iets.
- Actie: nog iets anders.

* Bronnen (bevestigd): [Bron B](https://example.com/b).

**3. Derde probleem**

- Observatie: weer iets.
- Actie: weer iets anders.

* Bronnen (bevestigd): [Bron C](https://example.com/c).
"""


def test_split_numbered_items_returns_none_below_minimum():
    assert _split_numbered_items("**1. Alleen een item**\n\ntekst") is None


def test_split_numbered_items_finds_a_genuine_run():
    items = _split_numbered_items(
        "**1. Een**\n\ntekst een.\n\n**2. Twee**\n\ntekst twee.\n\n**3. Drie**\n\ntekst drie."
    )
    assert items is not None
    assert len(items) == 3
    assert all(i["type"] == "probleem" for i in items)
    assert items[0]["title"] == "1. Een"
    assert "tekst een." in items[0]["text"]
    assert "tekst twee" not in items[0]["text"]  # never bleeds into the next item


def test_parse_markdown_splits_h2_groups_and_numbered_items(tmp_path):
    path = _write_md(tmp_path, _NUMBERED_SAMPLE)
    sections = _parse_markdown(path)
    # 1 prose (Leeswijzer) + 3 standalone "probleem" sections.
    assert len(sections) == 4
    assert sections[0]["type"] == "prose"
    assert sections[0]["title"] == "Leeswijzer"
    probleem_sections = [s for s in sections if s["type"] == "probleem"]
    assert len(probleem_sections) == 3
    assert [s["title"] for s in probleem_sections] == ["1. Eerste probleem", "2. Tweede probleem", "3. Derde probleem"]


def test_parse_markdown_keeps_each_problems_sources_attached_to_the_right_problem(tmp_path):
    path = _write_md(tmp_path, _NUMBERED_SAMPLE)
    sections = _parse_markdown(path)
    probleem_sections = [s for s in sections if s["type"] == "probleem"]
    assert "Bron A" in probleem_sections[0]["text"]
    assert "Bron B" not in probleem_sections[0]["text"]
    assert "Bron B" in probleem_sections[1]["text"]
    assert "Bron C" not in probleem_sections[1]["text"]
    assert "Bron C" in probleem_sections[2]["text"]


def test_parse_markdown_falls_back_to_single_prose_section_without_h2_headings(tmp_path):
    path = _write_md(tmp_path, "Gewoon een stukje tekst zonder koppen of genummerde items.")
    sections = _parse_markdown(path)
    assert len(sections) == 1
    assert sections[0]["type"] == "prose"


def test_parse_markdown_keeps_a_group_with_too_few_numbered_items_as_prose(tmp_path):
    path = _write_md(tmp_path, "## Groep\n\n**1. Enig item**\n\ntekst.\n")
    sections = _parse_markdown(path)
    assert len(sections) == 1
    assert sections[0]["type"] == "prose"
