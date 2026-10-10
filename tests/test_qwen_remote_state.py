"""Model-state / wait-notice logic of the Qwen client (pure functions over the server's /status payload)."""
from __future__ import annotations

from pipeline.qwen_remote import model_state, round_up_s, wait_notice

READY = {"loaded_models": [{"domain": "Orchard", "weights": "W0_base", "idle_s": 3}], "loading": [], "typical_load_s": 78}
UNLOADED = {"loaded_models": [], "loading": [], "typical_load_s": 78}
OTHER_RESIDENT = {"loaded_models": [{"domain": "Orchard", "weights": "sft_cards_v1", "idle_s": 1}], "loading": [], "typical_load_s": 78}
LOADING = {"loaded_models": [], "loading": [{"domain": "Orchard", "weights": "W0_base", "elapsed_s": 30.0}], "typical_load_s": 78}


def test_state_ready_loading_unloaded_unreachable():
    assert model_state(READY)["state"] == "ready"
    assert model_state(UNLOADED)["state"] == "unloaded"
    assert model_state(LOADING)["state"] == "loading" and model_state(LOADING)["remaining_s"] == 48
    assert model_state(None)["state"] == "unreachable"


def test_a_different_resident_model_does_not_count_as_ready():
    assert model_state(OTHER_RESIDENT, "W0_base")["state"] == "unloaded"
    assert model_state(OTHER_RESIDENT, "sft_cards_v1")["state"] == "ready"


def test_load_estimate_defaults_when_the_server_has_no_measurement():
    assert model_state({"loaded_models": [], "loading": []})["eta_s"] == 80


def test_the_remaining_time_never_shows_zero_while_loading():
    late = {"loaded_models": [], "loading": [{"domain": "Orchard", "weights": "W0_base", "elapsed_s": 500}], "typical_load_s": 78}
    assert model_state(late)["remaining_s"] == 5


def test_round_up_to_ten_seconds():
    assert [round_up_s(s) for s in (78, 80, 81, 5)] == [80, 80, 90, 10]


def test_notice_when_the_model_must_load_names_the_duration_and_the_answer_time():
    text = wait_notice(model_state(UNLOADED))
    assert "wordt nu geladen" in text and "ongeveer 80 seconden" in text and "5-30 seconden" in text


def test_notice_while_loading_gives_the_remaining_time():
    text = wait_notice(model_state(LOADING))
    assert "wordt op dit moment geladen" in text and "nog ongeveer 50 seconden" in text


def test_notice_when_ready_still_says_an_answer_can_take_a_while():
    text = wait_notice(model_state(READY))
    assert "kan even duren" in text and "geladen" not in text.replace("klaar", "")


def test_unreachable_server_falls_back_to_the_normal_notice():
    assert "kan even duren" in wait_notice(model_state(None))
