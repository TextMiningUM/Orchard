"""Unit tests for pipeline.orchard_tools -- only the pure/offline parts (no live network
calls in the automated suite, consistent with the rest of this project's test discipline).
Live API behaviour (Open-Meteo forecast/historical/geocoding, Buienradar) is smoke-tested
manually -- see the session's own verification transcript, not re-run on every `pytest`.
"""
from __future__ import annotations

from pipeline.orchard_tools import _degrees_to_compass, latest_available_archive_date


def test_degrees_to_compass_cardinal_points():
    assert _degrees_to_compass(0) == "N"
    assert _degrees_to_compass(90) == "O"
    assert _degrees_to_compass(180) == "Z"
    assert _degrees_to_compass(270) == "W"


def test_degrees_to_compass_wraps_around_360():
    assert _degrees_to_compass(359) == "N"
    assert _degrees_to_compass(360) == "N"


def test_latest_available_archive_date_is_yesterday():
    from datetime import date, timedelta
    assert latest_available_archive_date() == date.today() - timedelta(days=1)


def test_degrees_to_compass_none_passthrough():
    assert _degrees_to_compass(None) is None
