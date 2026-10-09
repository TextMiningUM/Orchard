"""Qwen3-8B cloud inference server for the Cherry Orchard Advisor.

Direct port of Auto Pilot's `cloud/qwen_inference_server.py` -- see that file's docstring
for the full rationale. Simplified here since Orchard currently has a single domain (no
VHF/OOW/Captain/ChiefEngineer-style multi-domain dispatch needed yet); `domain` is kept as
a parameter anyway so a second orchard crop (apples, pears, ...) could reuse this
unchanged later, per the project's "never fork a second copy" convention.

CLOUD-ONLY. Binds to 127.0.0.1 ONLY (never 0.0.0.0) -- this process must never be
directly reachable from the public internet, unlike the public read-only Streamlit
dashboard (which proxies through nginx on a different port). Access it either from the
SAME pod (the public Streamlit app calls http://127.0.0.1:8811 directly) or from a local
laptop via an SSH tunnel:
    ssh -N -L 8811:127.0.0.1:8811 -i <key> ubuntu@<pod-ip>

No authentication is implemented because localhost-only binding (+ the SSH tunnel for
remote access) IS the access control -- do not change this to bind 0.0.0.0 without adding
real authentication first.

Run (inside tmux or as a systemd service, so it survives SSH disconnects):
    .venv/bin/python -u cloud/qwen_inference_server.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import torch

from core.paths import AgentPaths
from core.qwen_loader import load_qwen

HOST, PORT = "127.0.0.1", 8811

_DOMAIN_FACTORY = {"Orchard": AgentPaths.orchard}

_model_cache: dict[tuple[str, str], tuple] = {}
_last_used: dict[tuple[str, str], float] = {}
_active_key: tuple[str, str] | None = None
_cache_lock = threading.Lock()
_gen_lock = threading.Lock()  # one generation at a time -- a single GPU can't usefully parallelise anyway

IDLE_UNLOAD_S = 180.0  # evict an idle cached model after this many seconds with no /generate traffic


def _get_model(domain: str, weights: str):
    key = (domain, weights)
    with _cache_lock:
        if key not in _model_cache:
            print(f"Loading {domain}/{weights} ...", flush=True)
            factory = _DOMAIN_FACTORY.get(domain)
            if factory is None:
                raise ValueError(f"Unknown domain {domain!r} -- known: {sorted(_DOMAIN_FACTORY)}")
            _model_cache[key] = load_qwen(weights, factory())
            print(f"Loaded {domain}/{weights}.", flush=True)
        _last_used[key] = time.time()
        return _model_cache[key]


def _unload_models(domain: str | None, weights: str | None) -> list[dict]:
    import gc
    removed = []
    with _cache_lock:
        for key in list(_model_cache):
            d, w = key
            if (domain is None or d == domain) and (weights is None or w == weights):
                del _model_cache[key]
                _last_used.pop(key, None)
                removed.append({"domain": d, "weights": w})
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return removed


def _idle_unload_loop() -> None:
    poll_s = max(5.0, min(IDLE_UNLOAD_S / 4, 15.0))
    while True:
        time.sleep(poll_s)
        now = time.time()
        stale = []
        with _cache_lock:
            for key in list(_model_cache):
                if key == _active_key:
                    continue
                if now - _last_used.get(key, now) > IDLE_UNLOAD_S:
                    stale.append(key)
        for domain, weights in stale:
            removed = _unload_models(domain, weights)
            if removed:
                print(f"[idle-unload] evicted {domain}/{weights} (idle > {IDLE_UNLOAD_S:.0f}s)", flush=True)


def _gpu_status() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        used, total, util = (int(x.strip()) for x in out.split(","))
        return {"memory_used_mib": used, "memory_total_mib": total, "utilization_pct": util}
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        return {"error": str(e)}


@torch.inference_mode()
def _generate(tok, mdl, messages: list[dict], max_new_tokens: int, enable_thinking: bool) -> str:
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                   enable_thinking=enable_thinking)
    inp = tok(text, return_tensors="pt", truncation=True, max_length=4096).to(mdl.device)
    with _gen_lock:
        out = mdl.generate(**inp, max_new_tokens=max_new_tokens, do_sample=False,
                           pad_token_id=tok.eos_token_id, repetition_penalty=1.15)
    return tok.decode(out[0][inp["input_ids"].shape[1]:], skip_special_tokens=True).strip()


class Handler(BaseHTTPRequestHandler):
    def _write_json(self, status: int, payload: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/generate":
                global _active_key
                domain = body.get("domain", "Orchard")
                weights = body.get("weights", "W0_base")
                messages = body["messages"]
                max_new_tokens = int(body.get("max_new_tokens", 400))
                enable_thinking = bool(body.get("enable_thinking", False))
                key = (domain, weights)
                tok, mdl = _get_model(domain, weights)
                _active_key = key
                try:
                    text = _generate(tok, mdl, messages, max_new_tokens, enable_thinking)
                finally:
                    _last_used[key] = time.time()
                    _active_key = None
                self._write_json(200, {"text": text})
            elif self.path == "/load":
                domain = body.get("domain", "Orchard")
                weights = body.get("weights", "W0_base")
                _get_model(domain, weights)
                self._write_json(200, {"loaded": {"domain": domain, "weights": weights}})
            elif self.path == "/unload":
                removed = _unload_models(body.get("domain"), body.get("weights"))
                self._write_json(200, {"unloaded": removed})
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:  # noqa: BLE001 -- always report the real error back to the client
            self._write_json(500, {"error": str(e)})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._write_json(200, {"status": "ok"})
        elif path == "/status":
            now = time.time()
            with _cache_lock:
                loaded = [
                    {"domain": d, "weights": w, "idle_s": round(now - _last_used.get((d, w), now), 1)}
                    for d, w in _model_cache
                ]
            self._write_json(200, {"gpu": _gpu_status(), "loaded_models": loaded, "idle_unload_s": IDLE_UNLOAD_S})
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        print("[server]", fmt % args, flush=True)


if __name__ == "__main__":
    print(f"Serving on {HOST}:{PORT} (models load lazily per domain/weights on first request)", flush=True)
    print(f"Idle auto-unload enabled: evicts a cached model after {IDLE_UNLOAD_S:.0f}s with no requests.", flush=True)
    threading.Thread(target=_idle_unload_loop, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
