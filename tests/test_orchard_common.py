"""Unit tests for app.orchard_common -- only the pure helpers (no Streamlit/network calls)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from orchard_common import PATHS, resolve_logbook_image_path  # noqa: E402


def test_resolve_logbook_image_path_strips_foreign_windows_prefix():
    raw = r"C:\Users\jcsch\Documents\Python\Orchard\Data\Orchard\OrchardLogbooks\_raw_page_images\jaar_2013\page_01.png"
    resolved = resolve_logbook_image_path(raw)
    expected = PATHS.logbooks_dir / "_raw_page_images" / "jaar_2013" / "page_01.png"
    assert resolved == expected


def test_resolve_logbook_image_path_handles_posix_style_stored_path():
    raw = "C:/Users/jcsch/Documents/Python/Orchard/Data/Orchard/OrchardLogbooks/_raw_page_images/jaar_2013/page_01.png"
    resolved = resolve_logbook_image_path(raw)
    expected = PATHS.logbooks_dir / "_raw_page_images" / "jaar_2013" / "page_01.png"
    assert resolved == expected


def test_resolve_logbook_image_path_works_regardless_of_original_machine_root():
    # Simulates a path baked in from a COMPLETELY different machine/root than this one --
    # must still resolve correctly since only the part from "_raw_page_images" onward matters.
    raw = "/home/someoneelse/orchard-checkout/Data/Orchard/OrchardLogbooks/_raw_page_images/jaar_2020/page_05.png"
    resolved = resolve_logbook_image_path(raw)
    expected = PATHS.logbooks_dir / "_raw_page_images" / "jaar_2020" / "page_05.png"
    assert resolved == expected


def test_resolve_logbook_image_path_none_for_empty_or_missing_input():
    assert resolve_logbook_image_path(None) is None
    assert resolve_logbook_image_path("") is None


def test_resolve_logbook_image_path_none_when_marker_absent():
    assert resolve_logbook_image_path(r"C:\Users\jcsch\some\other\path.png") is None
