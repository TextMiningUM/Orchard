"""Unit tests for pipeline.qwen_remote -- only the pure payload-building helper (no live
HTTP/network call in the automated suite; `generate_remote()`/`stream_remote()` themselves
are smoke-tested manually against the real cloud inference server, same convention as
pipeline/orchard_agent.py's own test file)."""
from __future__ import annotations

import json

from pipeline.qwen_remote import _build_payload


def test_build_payload_includes_core_fields():
    payload = json.loads(_build_payload(
        messages=[{"role": "user", "content": "hoi"}], domain="Orchard", weights="W0_base",
        max_new_tokens=300, enable_thinking=True, sampling={},
    ))
    assert payload == {
        "domain": "Orchard", "weights": "W0_base", "messages": [{"role": "user", "content": "hoi"}],
        "max_new_tokens": 300, "enable_thinking": True,
    }


def test_build_payload_includes_known_sampling_overrides():
    payload = json.loads(_build_payload(
        messages=[], domain="Orchard", weights="W0_base", max_new_tokens=300, enable_thinking=False,
        sampling={"temperature": 0.6, "top_p": 0.95, "top_k": 20, "repetition_penalty": 1.0},
    ))
    assert payload["temperature"] == 0.6
    assert payload["top_p"] == 0.95
    assert payload["top_k"] == 20
    assert payload["repetition_penalty"] == 1.0


def test_build_payload_drops_none_and_unknown_sampling_keys():
    payload = json.loads(_build_payload(
        messages=[], domain="Orchard", weights="W0_base", max_new_tokens=300, enable_thinking=False,
        sampling={"temperature": None, "not_a_real_param": 123},
    ))
    assert "temperature" not in payload
    assert "not_a_real_param" not in payload
