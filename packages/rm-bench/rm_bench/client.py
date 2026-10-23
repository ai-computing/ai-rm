"""One timed request against an OpenAI-compatible endpoint: streaming chat completions, or
non-streaming completions for servers that only offer /v1/completions."""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from contextlib import contextmanager

import requests
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, LocationParseError, NewConnectionError
from urllib3.util.connection import allowed_gai_family

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


@contextmanager
def _post(url: str, payload: dict, timeout_s: float):
    """Own the response and interrupt socket I/O at the wall deadline; DNS is OS-bounded."""
    deadline = time.perf_counter() + timeout_s
    sockets = []
    lock = threading.Lock()
    expired = threading.Event()

    def interrupt():
        with lock:
            expired.set()
            for sock in sockets:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    class WatchedConnection:
        def _new_conn(self):
            # Follow urllib3's create_connection, sharing one budget across DNS addresses.
            host = self._dns_host.strip("[]")
            try:
                host.encode("idna")
            except UnicodeError:
                raise LocationParseError(f"'{host}', label empty or too long") from None
            try:
                addresses = socket.getaddrinfo(host, self.port, allowed_gai_family(), socket.SOCK_STREAM)
                error = None
                for family, kind, protocol, _, address in addresses:
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0:
                        raise socket.timeout("request deadline exceeded")
                    sock = None
                    try:
                        sock = socket.socket(family, kind, protocol)
                        for option in self.socket_options or ():
                            sock.setsockopt(*option)
                        sock.settimeout(min(self.timeout, remaining) if self.timeout is not None else remaining)
                        if self.source_address:
                            sock.bind(self.source_address)
                        sock.connect(address)
                        with lock:
                            if expired.is_set():
                                raise socket.timeout("request deadline exceeded")
                            # The duplicate survives TLS wrapping and interrupts blocked reads.
                            sockets.append(sock.dup())
                        sys.audit("http.client.connect", self, self.host, self.port)
                        return sock
                    except OSError as exc:
                        if sock is not None:
                            sock.close()
                        error = exc
                raise error or OSError("getaddrinfo returns an empty list")
            except socket.timeout as exc:
                raise ConnectTimeoutError(self, "request deadline exceeded") from exc
            except OSError as exc:
                raise NewConnectionError(self, f"Failed to establish a new connection: {exc}") from exc

    class HTTPPool(HTTPConnectionPool):
        class ConnectionCls(WatchedConnection, HTTPConnection):
            pass

    class HTTPSPool(HTTPSConnectionPool):
        class ConnectionCls(WatchedConnection, HTTPSConnection):
            pass

    pools = {"http": HTTPPool, "https": HTTPSPool}

    class Adapter(requests.adapters.HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            super().init_poolmanager(*args, **kwargs)
            self.poolmanager.pool_classes_by_scheme = pools

        def proxy_manager_for(self, *args, **kwargs):
            manager = super().proxy_manager_for(*args, **kwargs)
            manager.pool_classes_by_scheme = pools
            return manager

    timer = threading.Timer(max(0.0, deadline - time.perf_counter()), interrupt)
    timer.daemon = True
    timer.start()
    try:
        with requests.Session() as session:
            adapter = Adapter()
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            with session.post(url, headers=headers(), json=payload, stream=True, timeout=timeout_s) as resp:
                yield resp
                if expired.is_set():
                    raise requests.Timeout("request deadline exceeded")
    finally:
        timer.cancel()
        timer.join()
        for sock in sockets:
            sock.close()


def _sse_lines(resp):
    """Lines of an event stream as they arrive.

    `iter_lines` is fine for chunked responses (urllib3 yields per HTTP chunk), but on a
    close-delimited or Content-Length stream it blocks until its read size fills, which would push
    TTFT late. There `read1` returns whatever the socket has.
    """
    raw = resp.raw
    if getattr(raw, "chunked", False) or not hasattr(raw, "read1"):
        for line in resp.iter_lines():
            yield line.decode("utf-8", "replace") if isinstance(line, bytes) else line
        return
    buf = b""
    while True:
        data = raw.read1(65536)
        if not data:
            break
        buf += data
        *lines, buf = buf.split(b"\n")
        for line in lines:
            yield line.rstrip(b"\r").decode("utf-8", "replace")
    if buf:
        yield buf.decode("utf-8", "replace")


def _chunk_text(choice) -> str:
    """Generated text in one streamed choice: `delta.content`, a reasoning model's
    `delta.reasoning_content`/`reasoning`, or `text` (completions-style chunks)."""
    if not isinstance(choice, dict):
        return ""
    delta = choice.get("delta")
    if isinstance(delta, dict):
        for key in ("content", "reasoning_content", "reasoning"):
            if isinstance(delta.get(key), str) and delta[key]:
                return delta[key]
    return choice["text"] if isinstance(choice.get("text"), str) else ""


def _record(ttft_ms: float | None, last_ms: float | None, e2e_ms: float,
            out_tokens: int, token_times: list[float]) -> RequestRecord:
    """A successful request's record. TPOT spans first to last token over the tokens between them,
    so time spent after the last token (the usage chunk, `[DONE]`, connection close) is not decode."""
    tpot_ms = None
    if out_tokens > 1 and ttft_ms is not None:
        end_ms = last_ms if last_ms is not None and last_ms > ttft_ms else e2e_ms
        tpot_ms = max(0.0, (end_ms - ttft_ms) / (out_tokens - 1))
    itl = tuple(b - a for a, b in zip(token_times, token_times[1:]))
    return RequestRecord(ok=True, e2e_ms=e2e_ms, ttft_ms=ttft_ms, tpot_ms=tpot_ms, out_tokens=out_tokens,
                         itl_ms=itl)


def _from_json_body(obj, e2e_ms: float) -> RequestRecord:
    """A server that answered a stream request with one JSON body (chat or completions shape).
    The first token is not visible: use server timing `pd.ttft_ms`/`pd.wall_ms` if present, else
    token timing stays unknown, as `complete` does."""
    choices = obj.get("choices") if isinstance(obj, dict) else None
    first = choices[0] if choices and isinstance(choices[0], dict) else {}
    msg = first.get("message") if isinstance(first.get("message"), dict) else {}
    text = msg.get("content") if isinstance(msg.get("content"), str) else first.get("text")
    if not isinstance(text, str):
        return RequestRecord(ok=False, e2e_ms=e2e_ms)
    usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
    out_tokens = usage.get("completion_tokens")
    if type(out_tokens) is not int or out_tokens < 0 or (out_tokens == 0 and text):
        out_tokens = max(1, len(text.split()))
    pd = obj.get("pd") if isinstance(obj.get("pd"), dict) else {}
    server_ttft, server_wall = pd.get("ttft_ms"), pd.get("wall_ms")
    if (all(type(v) in (int, float) and 0 <= v <= sys.float_info.max
            for v in (server_ttft, server_wall)) and server_ttft <= server_wall):
        ttft_ms = min(e2e_ms, max(0.0, e2e_ms - server_wall) + server_ttft)
    else:
        ttft_ms = None
    tpot_ms = (max(0.0, (e2e_ms - ttft_ms) / (out_tokens - 1))
               if out_tokens > 1 and ttft_ms is not None else None)
    return RequestRecord(ok=True, e2e_ms=e2e_ms, ttft_ms=ttft_ms, tpot_ms=tpot_ms, out_tokens=out_tokens)


def stream_chat(url: str, model: str, prompt_tokens: int, max_tokens: int, timeout_s: float,
                scheduled_at: float | None = None, prompt: str | None = None) -> RequestRecord:
    """Send one streaming chat request and time it from the SSE chunks.

    TTFT is the first chunk carrying generated text; ITL the gaps between text chunks; TPOT
    (last text chunk - first) / (out_tokens - 1). Output tokens come from the last `usage` chunk
    (vLLM sends it with empty `choices` before `[DONE]`), else the number of text chunks. TTFT and
    e2e count from `scheduled_at` (a `time.perf_counter()` value) when given, so time queued behind
    the client's concurrency limit counts, as it would for a user. `timeout_s` bounds the whole
    request. The request is ok when it streamed text and ended with `[DONE]`, or, for servers that
    omit `[DONE]`, a `finish_reason` and a clean close. A server that ignores `stream` and answers
    with one JSON body is handled like `complete` (TTFT not visible).
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt or make_prompt(prompt_tokens)}],
        "max_tokens": max(1, int(max_tokens)),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    return _stream(url, payload, timeout_s, scheduled_at)


def stream_completions(url: str, model: str, prompt_tokens: int, max_tokens: int, timeout_s: float,
                       scheduled_at: float | None = None, prompt: str | None = None) -> RequestRecord:
    """Send one streaming /v1/completions request: the same prompt text as `complete` (no chat
    template), timed from the SSE chunks like `stream_chat`. For servers that stream completions
    (vLLM, furiosa-llm), so TTFT is the client's first token rather than an upper bound."""
    payload = {"model": model, "prompt": prompt or make_prompt(prompt_tokens),
               "max_tokens": max(1, int(max_tokens)), "stream": True,
               "stream_options": {"include_usage": True}}
    return _stream(url, payload, timeout_s, scheduled_at)


def _stream(url: str, payload: dict, timeout_s: float, scheduled_at: float | None) -> RequestRecord:
    t0 = time.perf_counter() if scheduled_at is None else scheduled_at
    deadline = time.perf_counter() + timeout_s
    token_times: list[float] = []
    usage_tokens: int | None = None
    done = finished = timed_out = False
    done_ms: float | None = None
    try:
        with _post(url, payload, timeout_s) as resp:
            if resp.status_code >= 400:
                return RequestRecord(ok=False, e2e_ms=(time.perf_counter() - t0) * 1000.0)
            if resp.headers.get("Content-Type", "").split(";")[0].strip() == "application/json":
                obj = resp.json()
                return _from_json_body(obj, (time.perf_counter() - t0) * 1000.0)
            for line in _sse_lines(resp):
                if time.perf_counter() > deadline:
                    timed_out = not done
                    break
                if done:
                    continue          # drain to the end so the connection can be reused
                line = (line or "").strip()
                if not line.startswith("data:"):
                    continue          # comments (": keepalive"), event:/id: fields, blank separators
                data = line[5:].strip()
                if data == "[DONE]":
                    done = True
                    done_ms = (time.perf_counter() - t0) * 1000.0
                    continue
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                usage = obj.get("usage")
                if (isinstance(usage, dict) and type(usage.get("completion_tokens")) is int
                        and usage["completion_tokens"] >= 0):
                    usage_tokens = usage["completion_tokens"]
                for choice in obj.get("choices") or []:
                    if _chunk_text(choice):
                        token_times.append((time.perf_counter() - t0) * 1000.0)
                    if isinstance(choice, dict) and choice.get("finish_reason"):
                        finished = True
    except Exception:  # noqa: BLE001 -- any transport/protocol error fails the request, not the run
        if not done:   # an error while draining after [DONE] does not undo a complete answer
            return RequestRecord(ok=False, e2e_ms=(time.perf_counter() - t0) * 1000.0)
    e2e_ms = done_ms if done_ms is not None else (time.perf_counter() - t0) * 1000.0
    if not token_times or timed_out or not (done or finished):
        return RequestRecord(ok=False, e2e_ms=e2e_ms)
    out_tokens = usage_tokens if usage_tokens is not None and usage_tokens > 0 else len(token_times)
    return _record(token_times[0], token_times[-1], e2e_ms, out_tokens, token_times)


def complete(url: str, model: str, prompt_tokens: int, max_tokens: int, timeout_s: float,
             scheduled_at: float | None = None, prompt: str | None = None) -> RequestRecord:
    """Send one non-streaming /v1/completions request.

    Without a stream the client cannot see the first token. When the response carries the
    server's own timing (`pd.ttft_ms` and `pd.wall_ms`, as rngd-pd's gateway reports), TTFT is the
    server's TTFT plus the time the client spent outside the server (queueing, network):
    (e2e - wall_ms) + ttft_ms. Otherwise TTFT and TPOT are unknown. Output tokens come from
    `usage.completion_tokens`; TPOT = (e2e - ttft) / (out_tokens - 1).
    """
    payload = {"model": model, "prompt": prompt or make_prompt(prompt_tokens),
               "max_tokens": max(1, int(max_tokens)), "stream": False}
    t0 = time.perf_counter() if scheduled_at is None else scheduled_at
    obj = None
    try:
        with _post(url, payload, timeout_s) as resp:
            if resp.status_code < 400:
                obj = resp.json()
    except Exception:  # noqa: BLE001 -- any transport/protocol error fails the request, not the run
        obj = None
    return _from_json_body(obj, (time.perf_counter() - t0) * 1000.0)
