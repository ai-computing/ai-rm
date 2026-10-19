"""One timed request against an OpenAI-compatible endpoint: streaming chat completions, or
non-streaming completions for servers that only offer /v1/completions."""
from __future__ import annotations

import json
import os
import time

import requests

from .results import RequestRecord

CHAT_PATH = "/v1/chat/completions"
COMPLETIONS_PATH = "/v1/completions"


def chat_url(gateway: str) -> str:
    """Accept either a gateway base URL or a full chat-completions URL."""
    gateway = gateway.rstrip("/")
    return gateway if gateway.endswith(CHAT_PATH) else gateway + CHAT_PATH


def completions_url(gateway: str) -> str:
    """Accept either a gateway base URL or a full URL ending in /completions (e.g. behind a
    route that rewrites its own prefix to /v1)."""
    gateway = gateway.rstrip("/")
    return gateway if gateway.endswith("/completions") else gateway + COMPLETIONS_PATH


def headers() -> dict[str, str]:
    # The key, if any, comes from the environment only (PROTOCOL.md §7).
    return {"Authorization": "Bearer " + os.environ.get("LLMD_API_KEY", "dummy"),
            "Content-Type": "application/json"}


def discover_model(gateway: str, timeout_s: float = 10.0) -> str:
    """First model id served at <gateway>/v1/models."""
    base = gateway.rstrip("/")
    for suffix in (CHAT_PATH, COMPLETIONS_PATH):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    resp = requests.get(base + "/v1/models", headers=headers(), timeout=timeout_s)
    resp.raise_for_status()
    data = resp.json().get("data") or []
    if not data:
        raise RuntimeError("gateway /v1/models returned no models; pass --model")
    return data[0]["id"]


def make_prompt(num_tokens: int) -> str:
    return " ".join(["word"] * max(1, int(num_tokens)))


def stream_chat(url: str, model: str, prompt_tokens: int, max_tokens: int, timeout_s: float,
                scheduled_at: float | None = None, prompt: str | None = None) -> RequestRecord:
    """Send one streaming request; TTFT is the first non-empty content chunk.

    TTFT and e2e are measured from `scheduled_at` (a `time.perf_counter()` value) when given, so
    time spent queued behind the client's concurrency limit counts, as it would for a user.
    `timeout_s` bounds the whole request. A request counts as ok only if it streams content and
    ends with `[DONE]`. Output tokens come from the final `usage` chunk when the server sends one,
    otherwise from the number of content chunks. TPOT = (e2e - ttft) / (out_tokens - 1).
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt or make_prompt(prompt_tokens)}],
        "max_tokens": max(1, int(max_tokens)),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    t0 = time.perf_counter() if scheduled_at is None else scheduled_at
    deadline = time.perf_counter() + timeout_s
    ttft_ms: float | None = None
    chunks = 0
    usage_tokens: int | None = None
    ok = False
    try:
        with requests.post(url, headers=headers(), json=payload, stream=True, timeout=timeout_s) as resp:
            if resp.status_code < 400:
                for raw in resp.iter_lines(decode_unicode=True):
                    if time.perf_counter() > deadline:
                        break
                    line = (raw or "").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        ok = True
                        break
                    try:
                        obj = json.loads(data)
                    except ValueError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    usage = obj.get("usage")
                    if isinstance(usage, dict) and isinstance(usage.get("completion_tokens"), int):
                        usage_tokens = usage["completion_tokens"]
                    for choice in obj.get("choices") or []:
                        delta = choice.get("delta") if isinstance(choice, dict) else None
                        if isinstance(delta, dict) and delta.get("content"):
                            chunks += 1
                            if ttft_ms is None:
                                ttft_ms = (time.perf_counter() - t0) * 1000.0
    except Exception:  # noqa: BLE001 -- any transport/protocol error fails the request, not the run
        ok = False
    e2e_ms = (time.perf_counter() - t0) * 1000.0
    out_tokens = usage_tokens if usage_tokens is not None else chunks
    ok = ok and ttft_ms is not None
    tpot_ms = None
    if ok and out_tokens > 1:
        tpot_ms = max(0.0, (e2e_ms - ttft_ms) / (out_tokens - 1))
    return RequestRecord(ok=ok, e2e_ms=e2e_ms, ttft_ms=ttft_ms, tpot_ms=tpot_ms, out_tokens=out_tokens if ok else 0)


def complete(url: str, model: str, prompt_tokens: int, max_tokens: int, timeout_s: float,
             scheduled_at: float | None = None, prompt: str | None = None) -> RequestRecord:
    """Send one non-streaming /v1/completions request.

    Without a stream the client cannot see the first token. When the response carries the
    server's own timing (`pd.ttft_ms` and `pd.wall_ms`, as rngd-pd's gateway reports), TTFT is the
    server's TTFT plus the time the client spent outside the server (queueing, network):
    (e2e - wall_ms) + ttft_ms. Otherwise TTFT is e2e, an upper bound. Output tokens come from
    `usage.completion_tokens`; TPOT = (e2e - ttft) / (out_tokens - 1).
    """
    payload = {"model": model, "prompt": prompt or make_prompt(prompt_tokens),
               "max_tokens": max(1, int(max_tokens)), "stream": False}
    t0 = time.perf_counter() if scheduled_at is None else scheduled_at
    obj = None
    try:
        resp = requests.post(url, headers=headers(), json=payload, timeout=timeout_s)
        if resp.status_code < 400:
            obj = resp.json()
    except Exception:  # noqa: BLE001 -- any transport/protocol error fails the request, not the run
        obj = None
    e2e_ms = (time.perf_counter() - t0) * 1000.0
    choices = obj.get("choices") if isinstance(obj, dict) else None
    ok = bool(choices) and isinstance(choices[0], dict) and isinstance(choices[0].get("text"), str)
    if not ok:
        return RequestRecord(ok=False, e2e_ms=e2e_ms)
    usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
    out_tokens = usage.get("completion_tokens")
    if not isinstance(out_tokens, int):
        out_tokens = max(1, len(choices[0]["text"].split()))
    pd = obj.get("pd") if isinstance(obj.get("pd"), dict) else {}
    server_ttft, server_wall = pd.get("ttft_ms"), pd.get("wall_ms")
    if isinstance(server_ttft, (int, float)) and isinstance(server_wall, (int, float)):
        ttft_ms = min(e2e_ms, max(0.0, e2e_ms - server_wall) + server_ttft)
    else:
        ttft_ms = e2e_ms
    tpot_ms = max(0.0, (e2e_ms - ttft_ms) / (out_tokens - 1)) if out_tokens > 1 else None
    return RequestRecord(ok=True, e2e_ms=e2e_ms, ttft_ms=ttft_ms, tpot_ms=tpot_ms, out_tokens=out_tokens)
