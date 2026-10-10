"""Thin HTTP client for cloud/qwen_inference_server.py.

Direct port of Auto Pilot's `pipeline/qwen_remote.py` -- lets the Streamlit app get real
generated text from the cloud GPU without loading/running Qwen3-8B locally. Two usage
modes:

- **Running ON the pod** (the public read-only Streamlit deployment): the server is
  reachable directly at ``http://127.0.0.1:8811``, no tunnel needed -- this is the default.
- **Running locally** (laptop dev, no GPU): reach it via an SSH tunnel first:
      ssh -N -L 8811:127.0.0.1:8811 -i <key> ubuntu@<pod-ip>
  `reconnect_tunnel()` can launch this automatically from `.env` (`ORCHARD_CLOUD_SSH_HOST`/
  `ORCHARD_CLOUD_SSH_KEY`/`ORCHARD_CLOUD_SSH_USER`), mirroring Auto Pilot's own convention.

Pure stdlib HTTP client -- no torch/model loading happens in this module, safe to import
anywhere locally (including the Windows laptop, no GPU needed).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8811"
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


# Sampling-parameter overrides accepted by both generate_remote()/stream_remote() and the
# server's /generate(_stream) endpoints -- see cloud/qwen_inference_server.py's
# `_SAMPLING_DEFAULTS` for Qwen's own recommended thinking/non-thinking values, used whenever
# a parameter isn't explicitly overridden here.
_SAMPLING_KEYS = ("temperature", "top_p", "top_k", "repetition_penalty", "presence_penalty")


def _build_payload(messages: list[dict], domain: str, weights: str, max_new_tokens: int,
                   enable_thinking: bool, sampling: dict) -> bytes:
    body = {
        "domain": domain, "weights": weights, "messages": messages,
        "max_new_tokens": max_new_tokens, "enable_thinking": enable_thinking,
    }
    body.update({k: v for k, v in sampling.items() if k in _SAMPLING_KEYS and v is not None})
    return json.dumps(body).encode("utf-8")


def _connection_error(base_url: str, e: Exception) -> ConnectionError:
    return ConnectionError(
        f"Could not reach the Qwen inference server at {base_url} -- if running "
        "locally (not on the pod itself), is the SSH tunnel open? "
        "(ssh -N -L 8811:127.0.0.1:8811 -i <key> ubuntu@<pod-ip>)"
    )


def generate_remote(
    messages: list[dict], domain: str = "Orchard", weights: str = "W0_base",
    max_new_tokens: int = 400, enable_thinking: bool = False,
    base_url: str = DEFAULT_URL, timeout_s: float = 300.0, **sampling,
) -> str:
    """POST a chat-style `messages` list to the Qwen inference server and return the
    generated text (non-streaming -- used for ReACT tool-call hops, where the full text is
    needed immediately to detect a tool-call JSON vs. a final answer; see `stream_remote()`
    for the user-facing final-answer path). Raises ConnectionError (with an actionable hint)
    if the server/tunnel isn't reachable, rather than hanging or returning a confusing
    low-level socket error. `**sampling` optionally overrides any of `_SAMPLING_KEYS` (e.g.
    `temperature=0.6`) -- otherwise the server applies Qwen's own recommended defaults."""
    payload = _build_payload(messages, domain, weights, max_new_tokens, enable_thinking, sampling)
    req = urllib.request.Request(f"{base_url}/generate", data=payload, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return json.loads(resp.read())["text"]
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read()).get("error", str(e))
        raise RuntimeError(f"Qwen inference server returned an error: {detail}") from e
    except urllib.error.URLError as e:
        raise _connection_error(base_url, e) from e


def stream_remote(
    messages: list[dict], domain: str = "Orchard", weights: str = "W0_base",
    max_new_tokens: int = 400, enable_thinking: bool = False,
    base_url: str = DEFAULT_URL, timeout_s: float = 300.0, **sampling,
):
    """Generator twin of `generate_remote()` -- POSTs to `/generate_stream` and yields
    incremental text deltas as they're generated (newline-delimited JSON over a
    close-delimited HTTP response, see the server's `_handle_generate_stream()`), for
    `st.write_stream()`-style live display. Only yields the `"delta"` lines; the final
    `{"done": true, "text": ...}` line is consumed but not re-yielded (callers that need the
    full assembled text should accumulate the deltas themselves, e.g. via
    `"".join(stream_remote(...))`). Raises the same ConnectionError/RuntimeError as
    `generate_remote()` -- note these only surface once the generator is actually iterated,
    not at call time, since nothing runs until the first `next()`."""
    payload = _build_payload(messages, domain, weights, max_new_tokens, enable_thinking, sampling)
    req = urllib.request.Request(f"{base_url}/generate_stream", data=payload, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                obj = json.loads(line)
                if "error" in obj:
                    raise RuntimeError(f"Qwen inference server returned an error: {obj['error']}")
                if "delta" in obj:
                    yield obj["delta"]
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read()).get("error", str(e))
        raise RuntimeError(f"Qwen inference server returned an error: {detail}") from e
    except urllib.error.URLError as e:
        raise _connection_error(base_url, e) from e


def is_remote_server_up(base_url: str = DEFAULT_URL, timeout_s: float = 3.0) -> bool:
    """Quick /health check -- used by a UI toggle to decide whether the remote option is
    actually usable right now, instead of letting a slow request silently time out."""
    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=timeout_s) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def reconnect_tunnel(base_url: str = DEFAULT_URL, timeout_s: float = 8.0) -> tuple[bool, str]:
    """Launches the local SSH port-forward as a detached background process, reading
    ORCHARD_CLOUD_SSH_HOST/_USER/_KEY from .env. No-ops (returns True immediately) if the
    server already responds -- useful when running ON the pod itself, where no tunnel is
    needed at all. Returns (success, message)."""
    if is_remote_server_up(base_url):
        return True, "Already connected."
    from core.io import load_env
    load_env(_ENV_FILE)
    host = os.environ.get("ORCHARD_CLOUD_SSH_HOST")
    key = os.environ.get("ORCHARD_CLOUD_SSH_KEY")
    user = os.environ.get("ORCHARD_CLOUD_SSH_USER", "ubuntu")
    if not host or not key:
        return False, ("Missing ORCHARD_CLOUD_SSH_HOST/ORCHARD_CLOUD_SSH_KEY in .env -- "
                      "set these to the cloud pod's IP and SSH private key path.")
    cmd = ["ssh", "-N", "-L", "8811:127.0.0.1:8811", "-i", key,
          "-o", "StrictHostKeyChecking=accept-new", "-o", "ExitOnForwardFailure=yes",
          "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=4",  # a tunnel that silently dies mid-run was the cause of an eval with 228 connection errors
          f"{user}@{host}"]
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=creationflags)
    except OSError as e:
        return False, f"Could not launch ssh: {e}"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(1.0)
        if is_remote_server_up(base_url):
            return True, "Tunnel reconnected."
    return False, ("ssh launched but the server still isn't reachable -- check the cloud pod "
                   "itself is running (a dead tunnel is fixed by this, a dead/rebooted pod is not).")


def get_status(base_url: str = DEFAULT_URL, timeout_s: float = 5.0) -> dict | None:
    """GET /status -- {"gpu": {...}, "loaded_models": [...], "loading": [...], "typical_load_s": n}. Returns None (never
    raises) if the server is unreachable, so a UI status panel can show "unavailable" instead of crashing."""
    try:
        with urllib.request.urlopen(f"{base_url}/status", timeout=timeout_s) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError):
        return None


DEFAULT_LOAD_S = 80
TYPICAL_ANSWER_S = (5, 30)


def model_state(status: dict | None, weights: str = "W0_base", domain: str = "Orchard") -> dict:
    """Pure: what the user has to wait for, from a ``/status`` payload.

    ``state``: ``unreachable`` (no server), ``ready`` (the requested weights are loaded), ``loading`` (a load is running
    right now; ``remaining_s`` is the estimate for the rest of it) or ``unloaded`` (the first request will trigger a load,
    which also replaces whatever other model is resident -- the pod holds only one). ``eta_s`` is the typical load time
    measured by the server."""
    if status is None:
        return {"state": "unreachable", "eta_s": None, "remaining_s": None}
    eta = int(status.get("typical_load_s") or DEFAULT_LOAD_S)
    for m in status.get("loaded_models", []):
        if m.get("domain") == domain and m.get("weights") == weights:
            return {"state": "ready", "eta_s": eta, "remaining_s": 0}
    for m in status.get("loading", []):
        if m.get("domain") == domain and m.get("weights") == weights:
            return {"state": "loading", "eta_s": eta, "remaining_s": max(5, round(eta - m.get("elapsed_s", 0)))}
    return {"state": "unloaded", "eta_s": eta, "remaining_s": eta}


def round_up_s(seconds: int, step: int = 10) -> int:
    return int(-(-seconds // step) * step)


def wait_notice(state: dict) -> str:
    """The Dutch message shown while the advisor works. ALWAYS says an answer can take a while; when the model first has
    to be loaded it says so and for how long (about, rounded)."""
    lo, hi = TYPICAL_ANSWER_S
    answer = f"Het antwoord zelf duurt daarna meestal {lo}-{hi} seconden"
    if state["state"] == "unloaded":
        return (f"Het taalmodel (Qwen3-8B) staat nog niet in het geheugen van de server en wordt nu geladen: dat duurt "
                f"ongeveer {round_up_s(state['eta_s'])} seconden. {answer}. Even geduld.")
    if state["state"] == "loading":
        return (f"Het taalmodel (Qwen3-8B) wordt op dit moment geladen: nog ongeveer {round_up_s(state['remaining_s'])} "
                f"seconden. {answer}. Even geduld.")
    return (f"De adviseur denkt na... Een antwoord kan even duren ({lo}-{hi} seconden, soms langer bij een lange of "
            "ingewikkelde vraag): het model raadpleegt eerst de kennisbank en het antwoord verschijnt zodra het "
            "klaar is met redeneren.")
