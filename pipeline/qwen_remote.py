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


def generate_remote(
    messages: list[dict], domain: str = "Orchard", weights: str = "W0_base",
    max_new_tokens: int = 400, enable_thinking: bool = False,
    base_url: str = DEFAULT_URL, timeout_s: float = 90.0,
) -> str:
    """POST a chat-style `messages` list to the Qwen inference server and return the
    generated text. Raises ConnectionError (with an actionable hint) if the server/tunnel
    isn't reachable, rather than hanging or returning a confusing low-level socket error."""
    payload = json.dumps({
        "domain": domain, "weights": weights, "messages": messages,
        "max_new_tokens": max_new_tokens, "enable_thinking": enable_thinking,
    }).encode("utf-8")
    req = urllib.request.Request(f"{base_url}/generate", data=payload, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return json.loads(resp.read())["text"]
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read()).get("error", str(e))
        raise RuntimeError(f"Qwen inference server returned an error: {detail}") from e
    except urllib.error.URLError as e:
        raise ConnectionError(
            f"Could not reach the Qwen inference server at {base_url} -- if running "
            "locally (not on the pod itself), is the SSH tunnel open? "
            "(ssh -N -L 8811:127.0.0.1:8811 -i <key> ubuntu@<pod-ip>)"
        ) from e


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
    """GET /status -- {"gpu": {...}, "loaded_models": [...]}. Returns None (never raises)
    if the server is unreachable, so a UI status panel can show "unavailable" instead of
    crashing."""
    try:
        with urllib.request.urlopen(f"{base_url}/status", timeout=timeout_s) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError):
        return None
