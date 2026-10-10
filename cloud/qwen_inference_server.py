"""Qwen3-8B cloud inference server for the Cherry Orchard Advisor -- vLLM backend.

Direct port of Auto Pilot's `cloud/qwen_inference_server.py` in spirit, but the generation
backend was migrated 2026-10-09 from `transformers.generate()` (bitsandbytes NF4) to
**vLLM** (AWQ 4-bit) for continuous batching, automatic prefix caching (the system prompt +
tool catalogue are identical every turn) and real token streaming -- see
`design_cherry_orchard_advisor.md` Sec G.21 for the full story and measured numbers.

RUNTIME NOTE -- separate Python 3.12 venv, not the project's normal Python 3.13 `.venv`:
vLLM only gained Python 3.13 support in v0.20.0, but that SAME release switched its default
PyPI wheel to CUDA 13.0 binaries, which this pod's NVIDIA driver (570.133.07, max CUDA 12.8)
cannot initialise ("driver is too old") -- confirmed by direct testing, not a packaging bug:
even with the CUDA-13 shared libraries made importable, `torch.cuda` itself refuses to
initialise. NVIDIA's own Ubuntu-20.04 repo only offers driver 575.57.08 (still CUDA-12.x per
NVIDIA's own release notes, not enough either), and driver 580 would require a manual
out-of-repo .run installer on an EOL distro -- rejected as too risky for this pod. The
practical fix, agreed with the user: keep this ONE service on a dedicated `.venv-vllm`
(Python 3.12, `vllm==0.19.0`, last release before the CUDA-13 default switch) while the rest
of the project (app, tests, training pipeline) stays on Python 3.13 in the normal `.venv`.
Rebuild it with:
    ~/.local/bin/uv venv --python 3.12 .venv-vllm
    ~/.local/bin/uv pip install --python .venv-vllm/bin/python vllm==0.19.0
(A real driver/GPU upgrade -- e.g. LeafCloud's RTX 6000 Blackwell, which ships a modern
enough driver for vLLM's CUDA-13 default out of the box -- was considered and explicitly
deferred: ~3x the hourly cost and a full redeploy, including a NEW public IP/domain since
the current deployment's hostname IS this pod's IP. Revisit if/when the training stack
needs the bigger GPU anyway.)

CLOUD-ONLY. Binds to 127.0.0.1 ONLY (never 0.0.0.0) -- this process must never be directly
reachable from the public internet, unlike the public read-only Streamlit dashboard (which
proxies through nginx on a different port). Access it either from the SAME pod (the public
Streamlit app calls http://127.0.0.1:8811 directly) or from a local laptop via an SSH tunnel:
    ssh -N -L 8811:127.0.0.1:8811 -i <key> ubuntu@<pod-ip>

No authentication is implemented because localhost-only binding (+ the SSH tunnel for
remote access) IS the access control -- do not change this to bind 0.0.0.0 without adding
real authentication first.

Run (inside tmux or as a systemd service, so it survives SSH disconnects):
    .venv-vllm/bin/python -u cloud/qwen_inference_server.py
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from transformers import AutoTokenizer
from vllm import SamplingParams
from vllm.engine.arg_utils import AsyncEngineArgs
from vllm.lora.request import LoRARequest
from vllm.v1.engine.async_llm import AsyncLLM

from core.paths import AgentPaths

HOST, PORT = "127.0.0.1", 8811

_DOMAIN_FACTORY = {"Orchard": AgentPaths.orchard}

AWQ_MODEL_ID = "Qwen/Qwen3-8B-AWQ"  # official Qwen AWQ 4-bit quant -- fits the A30 with room
                                    # to spare for KV cache (bitsandbytes NF4 needed the old
                                    # transformers path; vLLM's fast AWQ/Marlin kernels replace it)
MAX_MODEL_LEN = 16384  # generous headroom for RAG context + tool-call history; Qwen3 supports
                        # up to 32768 natively, this is a deliberate budget vs. KV-cache memory
GPU_MEMORY_UTILIZATION = 0.85

# Qwen's own recommended sampling (see https://huggingface.co/Qwen/Qwen3-8B -- greedy decoding
# is explicitly NOT recommended for Qwen3, it can make the <think> block degenerate/repeat;
# this is also why the old transformers path had hacked in repetition_penalty=1.15 as a
# band-aid for greedy decoding. Proper sampling removes the need for that hack entirely).
_SAMPLING_DEFAULTS = {
    True: dict(temperature=0.6, top_p=0.95, top_k=20, repetition_penalty=1.0),   # enable_thinking=True
    False: dict(temperature=0.7, top_p=0.8, top_k=20, repetition_penalty=1.0),   # enable_thinking=False
}

IDLE_UNLOAD_S = float(os.environ.get("ORCHARD_QWEN_IDLE_UNLOAD_S", "300"))
# Default 300s (5 min) -- deliberately much longer than the old transformers path's 180s.
# vLLM's AWQ weights + KV cache comfortably fit the A30 (24 GB) alongside everything else
# this pod runs, so there's no real VRAM-pressure reason to evict quickly; a 5-minute floor
# just keeps the GPU free during genuinely idle stretches (overnight, etc.) while avoiding a
# cold-start penalty on the next request for any back-and-forth within a normal chat session.
# Set ORCHARD_QWEN_IDLE_UNLOAD_S=0 to disable entirely, or any other value to override.


class _EngineLoop:
    """Owns one dedicated asyncio event loop in a background thread -- vLLM's `AsyncLLM` is
    asyncio-native, but the HTTP server here is the stdlib synchronous `http.server`. This
    bridges the two: `run()` schedules a coroutine onto the loop and blocks the calling
    (synchronous) handler thread until it completes; `stream()` does the same but yields
    items as they arrive via a thread-safe queue, for the `/generate_stream` endpoint."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def stream(self, async_gen_factory):
        """`async_gen_factory()` returns an async generator; yields its items synchronously
        (blocking the calling thread per item) by running the generator's iteration on the
        event-loop thread and handing results back through a plain `queue.Queue`."""
        import queue
        q: queue.Queue = queue.Queue()
        _SENTINEL = object()

        async def _pump():
            try:
                async for item in async_gen_factory():
                    q.put(item)
            except Exception as e:  # noqa: BLE001 -- surface the error to the stream consumer
                q.put(e)
            finally:
                q.put(_SENTINEL)

        asyncio.run_coroutine_threadsafe(_pump(), self._loop)
        while True:
            item = q.get()
            if item is _SENTINEL:
                return
            if isinstance(item, Exception):
                raise item
            yield item


_engine_loop = _EngineLoop()
_engine_cache: dict[tuple[str, str], tuple] = {}  # (domain, weights) -> (AsyncLLM, tokenizer, lora_request|None)
_last_used: dict[tuple[str, str], float] = {}
_cache_lock = threading.Lock()  # serialises loading / eviction (held for the whole ~80 s of a load)

# Only ONE engine can live on the A30: each vLLM engine reserves GPU_MEMORY_UTILIZATION (85%) of the card, so a second one
# (e.g. a LoRA adapter next to the base model) cannot initialise -- the failure was "Engine core initialization failed" for
# whichever model was requested second. Loading a model therefore replaces the resident one, after its running requests end.
_loading: dict[tuple[str, str], float] = {}  # key -> start time, readable by /status WITHOUT taking _cache_lock
_inflight: dict[tuple[str, str], int] = {}
_inflight_cv = threading.Condition()
_load_seconds: list[float] = []  # measured durations of real loads (the UI quotes the median)
DEFAULT_LOAD_S = 80.0  # measured on the pod: 63 s engine init + weights
EVICT_WAIT_S = 120.0


async def _shutdown_engine(engine) -> None:
    """vLLM's ``AsyncLLM.shutdown()`` is a plain method in the installed version (it used to be a coroutine): handle both,
    otherwise the teardown raised 'A coroutine object is required' and left the engine behind."""
    result = engine.shutdown()
    if inspect.isawaitable(result):
        await result


def _resolve_model_source(weights: str, paths: AgentPaths) -> tuple[str, "LoRARequest | None"]:
    """Mirrors `core/qwen_loader.py::load_qwen()`'s `weights` contract (see that module's
    docstring) as closely as vLLM allows:
    - `"W0_base"` -> the official AWQ-quantized base model, no adapter.
    - `"MERGED:<dir>"` -> a standalone, already-merged model directory under
      `paths.domain_models_dir`, used directly as the base (no adapter).
    - anything else -> a SINGLE LoRA adapter directory name, applied on top of the AWQ base
      via vLLM's native LoRA support (`enable_lora=True` + `LoRARequest`).

    Deliberately simplified vs. the PEFT-based loader: vLLM's LoRA support serves one active
    adapter per request, not a sequential merge-and-stack CHAIN of several adapters the way
    `core/qwen_loader.py` supports for training-time composition. No adapters have been
    trained yet (SFT/DPO -- design doc Deel E steps 5/7 -- are both still "not started"), so
    a `"+"`-joined multi-adapter chain is rejected with a clear error rather than silently
    doing something different from what was asked; revisit once a real adapter exists."""
    if weights == "W0_base":
        return AWQ_MODEL_ID, None
    if weights.startswith("MERGED:"):
        merged_dir = paths.domain_models_dir / weights[len("MERGED:"):]
        if not merged_dir.exists():
            raise FileNotFoundError(f"No merged model directory at {merged_dir} for weights={weights!r}")
        return str(merged_dir), None
    if "+" in weights:
        raise NotImplementedError(
            f"weights={weights!r}: vLLM serves one LoRA adapter per request, not a PEFT-style "
            "sequential merge-chain of several adapters. Train/apply a single merged adapter, "
            "or extend this loader once multi-adapter composition is actually needed."
        )
    adapter_dir = paths.domain_models_dir / weights
    if not adapter_dir.exists():
        raise FileNotFoundError(f"No adapter directory at {adapter_dir} for weights={weights!r}")
    lora = LoRARequest(lora_name=weights, lora_int_id=abs(hash(weights)) % 1_000_000 + 1, lora_path=str(adapter_dir))
    return AWQ_MODEL_ID, lora


async def _build_engine(domain: str, weights: str):
    factory = _DOMAIN_FACTORY.get(domain)
    if factory is None:
        raise ValueError(f"Unknown domain {domain!r} -- known: {sorted(_DOMAIN_FACTORY)}")
    model_source, lora = _resolve_model_source(weights, factory())
    tok = AutoTokenizer.from_pretrained(model_source)
    engine_args = AsyncEngineArgs(
        model=model_source,
        max_model_len=MAX_MODEL_LEN,
        gpu_memory_utilization=GPU_MEMORY_UTILIZATION,
        dtype="auto",
        enable_prefix_caching=True,  # system prompt + tool catalogue repeat every turn
        enable_lora=lora is not None,
    )
    engine = AsyncLLM.from_engine_args(engine_args)
    return engine, tok, lora


def _wait_idle(key: tuple[str, str], timeout_s: float) -> None:
    """Blocks until no request is running on ``key`` (or the timeout passes)."""
    deadline = time.time() + timeout_s
    with _inflight_cv:
        while _inflight.get(key, 0) > 0 and time.time() < deadline:
            _inflight_cv.wait(timeout=1.0)


def _drop_engine(key: tuple[str, str]) -> None:
    """Shuts one cached engine down (caller holds ``_cache_lock``)."""
    engine, _tok, _lora = _engine_cache.pop(key)
    _last_used.pop(key, None)
    try:
        _engine_loop.run(_shutdown_engine(engine))
    except Exception as e:  # noqa: BLE001 -- best-effort teardown
        print(f"[unload] shutdown error for {key[0]}/{key[1]}: {e}", flush=True)


def _get_engine(domain: str, weights: str):
    key = (domain, weights)
    with _cache_lock:
        if key not in _engine_cache:
            for other in [k for k in _engine_cache if k != key]:
                print(f"Evicting {other[0]}/{other[1]} to make room for {domain}/{weights} (one engine fits the GPU).", flush=True)
                _wait_idle(other, EVICT_WAIT_S)
                _drop_engine(other)
            print(f"Loading {domain}/{weights} ...", flush=True)
            started = time.time()
            _loading[key] = started
            try:
                _engine_cache[key] = _engine_loop.run(_build_engine(domain, weights))
            finally:
                _loading.pop(key, None)
            _load_seconds.append(time.time() - started)
            del _load_seconds[:-5]
            print(f"Loaded {domain}/{weights} in {time.time() - started:.0f}s.", flush=True)
        _last_used[key] = time.time()
        return _engine_cache[key]


class _use_engine:
    """``with _use_engine(domain, weights) as (engine, tok, lora):`` -- loads if needed and marks the engine busy so an
    eviction for another model waits for this request instead of killing it mid-generation."""

    def __init__(self, domain: str, weights: str) -> None:
        self.key = (domain, weights)

    def __enter__(self):
        while True:
            engine = _get_engine(*self.key)
            with _inflight_cv:
                if self.key in _engine_cache:  # could have been evicted between the two steps
                    _inflight[self.key] = _inflight.get(self.key, 0) + 1
                    return engine

    def __exit__(self, *exc) -> None:
        with _inflight_cv:
            _inflight[self.key] = max(0, _inflight.get(self.key, 1) - 1)
            _inflight_cv.notify_all()
        _last_used[self.key] = time.time()


def _unload_engines(domain: str | None, weights: str | None) -> list[dict]:
    removed = []
    with _cache_lock:
        for key in list(_engine_cache):
            d, w = key
            if (domain is None or d == domain) and (weights is None or w == weights):
                _wait_idle(key, EVICT_WAIT_S)
                _drop_engine(key)
                removed.append({"domain": d, "weights": w})
    return removed


def _idle_unload_loop() -> None:
    if IDLE_UNLOAD_S <= 0:
        return  # disabled -- see IDLE_UNLOAD_S docstring above
    poll_s = max(5.0, min(IDLE_UNLOAD_S / 4, 15.0))
    while True:
        time.sleep(poll_s)
        now = time.time()
        stale = [key for key, last in list(_last_used.items()) if now - last > IDLE_UNLOAD_S]
        for domain, weights in stale:
            removed = _unload_engines(domain, weights)
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


def _sampling_params(body: dict) -> SamplingParams:
    """Builds SamplingParams from Qwen's recommended thinking/non-thinking defaults
    (`_SAMPLING_DEFAULTS`), with any of temperature/top_p/top_k/repetition_penalty/
    presence_penalty overridable per-request (e.g. for future quality-tuning experiments --
    design doc Deel E step 9's gouden eval-set -- without a server redeploy)."""
    enable_thinking = bool(body.get("enable_thinking", False))
    params = dict(_SAMPLING_DEFAULTS[enable_thinking])
    for key in ("temperature", "top_p", "top_k", "repetition_penalty", "presence_penalty"):
        if key in body:
            params[key] = body[key]
    return SamplingParams(max_tokens=int(body.get("max_new_tokens", 400)), **params)


def _render_prompt(tok, messages: list[dict], enable_thinking: bool) -> str:
    return tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                   enable_thinking=enable_thinking)


async def _agenerate_full(engine, lora, prompt: str, sp: SamplingParams) -> str:
    text = ""
    async for out in engine.generate(prompt=prompt, sampling_params=sp, request_id=uuid.uuid4().hex,
                                     lora_request=lora):
        text = out.outputs[0].text
    return text.strip()


def _stream_deltas(engine, lora, prompt: str, sp: SamplingParams):
    """Synchronous generator (see `_EngineLoop.stream`) yielding incremental text deltas --
    vLLM's `RequestOutput.outputs[0].text` is the CUMULATIVE text so far, not a delta, so this
    tracks the previously-seen length itself."""
    request_id = uuid.uuid4().hex
    state = {"last_len": 0}

    async def _gen():
        async for out in engine.generate(prompt=prompt, sampling_params=sp, request_id=request_id,
                                         lora_request=lora):
            cur = out.outputs[0].text
            delta = cur[state["last_len"]:]
            state["last_len"] = len(cur)
            if delta:
                yield delta

    yield from _engine_loop.stream(_gen)


def status_payload() -> dict:
    """What ``GET /status`` returns. Never takes ``_cache_lock`` (it is held for the whole of a model load), so the status
    stays answerable WHILE a model loads -- that is exactly when the UI asks for it."""
    now = time.time()
    loaded = [{"domain": d, "weights": w, "idle_s": round(now - _last_used.get((d, w), now), 1)}
              for d, w in list(_engine_cache)]
    loading = [{"domain": d, "weights": w, "elapsed_s": round(now - t, 1)} for (d, w), t in list(_loading.items())]
    typical = sorted(_load_seconds)[len(_load_seconds) // 2] if _load_seconds else DEFAULT_LOAD_S
    return {"gpu": _gpu_status(), "loaded_models": loaded, "loading": loading, "typical_load_s": round(typical),
            "idle_unload_s": IDLE_UNLOAD_S, "backend": "vllm"}


class Handler(BaseHTTPRequestHandler):
    def _write_json(self, status: int, payload: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_POST(self) -> None:
        try:
            body = self._read_body()
            if self.path == "/generate":
                self._handle_generate(body)
            elif self.path == "/generate_stream":
                self._handle_generate_stream(body)
            elif self.path == "/load":
                domain = body.get("domain", "Orchard")
                weights = body.get("weights", "W0_base")
                _get_engine(domain, weights)
                self._write_json(200, {"loaded": {"domain": domain, "weights": weights}})
            elif self.path == "/unload":
                removed = _unload_engines(body.get("domain"), body.get("weights"))
                self._write_json(200, {"unloaded": removed})
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:  # noqa: BLE001 -- always report the real error back to the client
            self._write_json(500, {"error": str(e)})

    def _handle_generate(self, body: dict) -> None:
        domain = body.get("domain", "Orchard")
        weights = body.get("weights", "W0_base")
        enable_thinking = bool(body.get("enable_thinking", False))
        with _use_engine(domain, weights) as (engine, tok, lora):
            prompt = _render_prompt(tok, body["messages"], enable_thinking)
            sp = _sampling_params(body)
            text = _engine_loop.run(_agenerate_full(engine, lora, prompt, sp))
        self._write_json(200, {"text": text})

    def _handle_generate_stream(self, body: dict) -> None:
        domain = body.get("domain", "Orchard")
        weights = body.get("weights", "W0_base")
        enable_thinking = bool(body.get("enable_thinking", False))
        with _use_engine(domain, weights) as (engine, tok, lora):
            prompt = _render_prompt(tok, body["messages"], enable_thinking)
            sp = _sampling_params(body)

            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            full_text = ""
            try:
                for delta in _stream_deltas(engine, lora, prompt, sp):
                    full_text += delta
                    self.wfile.write((json.dumps({"delta": delta}) + "\n").encode("utf-8"))
                    self.wfile.flush()
            except Exception as e:  # noqa: BLE001 -- report inline, the 200 header is already sent
                self.wfile.write((json.dumps({"error": str(e)}) + "\n").encode("utf-8"))
                self.wfile.flush()
                return
        self.wfile.write((json.dumps({"done": True, "text": full_text.strip()}) + "\n").encode("utf-8"))
        self.wfile.flush()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._write_json(200, {"status": "ok"})
        elif path == "/status":
            self._write_json(200, status_payload())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        print("[server]", fmt % args, flush=True)


if __name__ == "__main__":
    print(f"Serving on {HOST}:{PORT} (vLLM backend, models load lazily per domain/weights on first request)",
         flush=True)
    if IDLE_UNLOAD_S > 0:
        print(f"Idle auto-unload enabled: evicts a cached model after {IDLE_UNLOAD_S:.0f}s with no requests.",
             flush=True)
        threading.Thread(target=_idle_unload_loop, daemon=True).start()
    else:
        print("Idle auto-unload disabled (ORCHARD_QWEN_IDLE_UNLOAD_S=0) -- model stays resident.", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
