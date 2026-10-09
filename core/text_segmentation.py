"""Shared text-cleanup helpers for document ingestion (mirrors Auto Pilot's own
``core/text_segmentation.py`` -- same module name/location on purpose, see
``.github/copilot-instructions.md``).
"""
from __future__ import annotations

import re

# A word PDF line-wrapping broke across a line boundary ("contin-\nued" -> "continued").
# Call this BEFORE collapsing newlines to spaces -- a hyphen-broken word can otherwise end up
# permanently split into two separate "words".
_HYPHEN_LINEBREAK_RE = re.compile(r"(\w)-\n(?=[a-z])")


def join_hyphenated_linebreaks(text: str) -> str:
    """Join a word that a PDF's own line-wrapping broke across a line/page boundary
    ("contin-\\nued" -> "continued"). Call this BEFORE any heading/sentence-boundary
    detection, and before collapsing newlines to spaces -- a hyphen-broken word can
    otherwise defeat both."""
    return _HYPHEN_LINEBREAK_RE.sub(r"\1", text)
