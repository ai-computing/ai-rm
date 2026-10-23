"""client.stream_chat against a stdlib SSE server: TTFT/TPOT/ITL from chunk arrival times."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from rm_bench import client

FIRST_S = 0.20     # prefill: delay before the first token
GAP_S = 0.02       # decode: delay between tokens


class SSE(BaseHTTPRequestHandler):
    """One configurable chat-completions stream per request (class attributes set per test)."""
    protocol_version = "HTTP/1.1"
    chunked = True            # False: HTTP/1.0-style stream delimited by connection close
    tokens_per_chunk = 1
    send_usage = True
    send_done = True
    send_finish = True
    keepalive = False         # SSE comment lines between events
    field = "content"         # delta field carrying text
    json_body = False         # ignore stream=true and answer with one JSON body
    server_timing = None
    usage_count = None

    def log_message(self, *args):
        pass

    def handle(self):
        try:
            super().handle()
        except ConnectionError:   # the client hangs up once it has [DONE]
            pass

    def _write(self, data: bytes):
        if self.chunked:
            self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
        else:
            self.wfile.write(data)
        self.wfile.flush()

    def _event(self, obj):
        self._write(f"data: {obj if isinstance(obj, str) else json.dumps(obj)}\n\n".encode())

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).last_request = req
        n = req["max_tokens"]
        if self.json_body:
            time.sleep(FIRST_S)
            body = json.dumps({"choices": [{"index": 0, "message": {"role": "assistant", "content": "x " * n},
                                            "finish_reason": "length"}],
                               "usage": {"prompt_tokens": 3, "completion_tokens": n},
                               "pd": self.server_timing}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.chunked:
            self.protocol_version = "HTTP/1.0"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        if self.chunked:
            self.send_header("Transfer-Encoding", "chunked")
        else:
            self.send_header("Connection", "close")
        self.end_headers()
        self._event({"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}]})  # role only
        time.sleep(FIRST_S)
        chunks = n // self.tokens_per_chunk
        for i in range(chunks):
            if i:
                time.sleep(GAP_S)
            if self.keepalive:
                self._write(b": ping\n\n")
            last = i == chunks - 1
            text = "tok " * self.tokens_per_chunk
            choice = {"index": 0, "text": text} if self.field == "text" else                 {"index": 0, "delta": {self.field: text}}
            choice["finish_reason"] = "length" if last and self.send_finish else None
            self._event({"choices": [choice]})
        time.sleep(0.15)        # tail after the last token (not decode time)
        if self.send_usage:
            count = n if self.usage_count is None else self.usage_count
            self._event({"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": count}})
        if self.send_done:
            self._event("[DONE]")
        if self.chunked:
            self.wfile.write(b"0\r\n\r\n")


@pytest.fixture
def sse():
    handler = type("H", (SSE,), {})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield client.chat_url(f"http://127.0.0.1:{srv.server_port}"), handler
    srv.shutdown()
    srv.server_close()


def _send(url, n=8):
    return client.stream_chat(url, "m", prompt_tokens=4, max_tokens=n, timeout_s=10)


def _assert_timing(rec, n, chunks):
    assert rec.ok and rec.out_tokens == n
    assert FIRST_S * 1000 <= rec.ttft_ms < FIRST_S * 1000 + 150
    # TPOT spans first..last token, not the 150 ms tail before [DONE]
    decode_ms = (chunks - 1) * GAP_S * 1000
    assert rec.tpot_ms == pytest.approx(decode_ms / (n - 1), abs=8)
    assert len(rec.itl_ms) == chunks - 1
    assert all(g >= GAP_S * 1000 * 0.5 for g in rec.itl_ms)


def test_chunked_stream_with_usage_and_done(sse):
    url, _ = sse
    _assert_timing(_send(url), 8, 8)


def test_close_delimited_stream_ttft_not_delayed(sse):
    # No chunked encoding: reading must not wait for a full buffer before seeing the first token
    url, h = sse
    h.chunked = False
    _assert_timing(_send(url), 8, 8)


def test_usage_counts_tokens_when_chunks_carry_several(sse):
    url, h = sse
    h.tokens_per_chunk = 2
    rec = _send(url, 8)
    _assert_timing(rec, 8, 4)


def test_no_usage_counts_chunks(sse):
    url, h = sse
    h.send_usage = False
    h.keepalive = True
    rec = _send(url, 6)
    assert rec.ok and rec.out_tokens == 6


def test_reasoning_content_is_a_token(sse):
    url, h = sse
    h.field = "reasoning_content"
    _assert_timing(_send(url), 8, 8)


def test_finish_reason_without_done_is_ok(sse):
    url, h = sse
    h.send_done = False
    assert _send(url).ok


def test_truncated_stream_fails(sse):
    url, h = sse
    h.send_done = h.send_finish = False
    rec = _send(url)
    assert not rec.ok and rec.ttft_ms is None


def test_json_body_fallback(sse):
    url, h = sse
    h.json_body = True
    rec = _send(url, 5)
    assert rec.ok and rec.out_tokens == 5 and rec.itl_ms == ()
    assert rec.ttft_ms is None and rec.tpot_ms is None


@pytest.mark.parametrize("send", [client.stream_chat, client.complete])
def test_json_body_with_inconsistent_server_timing_keeps_latency_unknown(sse, send):
    url, handler = sse
    handler.json_body = True
    handler.server_timing = {"ttft_ms": 101, "wall_ms": 100}
    record = send(url, "m", 4, 5, timeout_s=10)
    assert record.ok and record.ttft_ms is None and record.tpot_ms is None


@pytest.mark.parametrize("tokens", [True, -1, 0])
def test_invalid_stream_usage_count_uses_chunk_estimate(sse, tokens):
    url, handler = sse
    handler.usage_count = tokens
    record = _send(url, 5)
    assert record.ok and type(record.out_tokens) is int and record.out_tokens == 5
    assert record.tpot_ms > 0


def test_single_token_usage_still_takes_precedence_over_chunk_count(sse):
    url, handler = sse
    handler.usage_count = 1
    record = _send(url, 5)
    assert record.ok and record.out_tokens == 1 and record.tpot_ms is None


def test_http_error_fails():
    rec = client.stream_chat("http://127.0.0.1:9/v1/chat/completions", "m", 4, 4, timeout_s=2)
    assert not rec.ok


def test_streaming_completions(sse):
    url, handler = sse
    handler.field = "text"                     # completions chunks: choices[].text
    url = client.completions_url(url.rsplit("/v1/", 1)[0])
    rec = client.stream_completions(url, "m", prompt_tokens=4, max_tokens=8, timeout_s=10, prompt="a b c")
    _assert_timing(rec, 8, 8)
    assert handler.last_request["prompt"] == "a b c" and handler.last_request["stream"] is True
    assert "messages" not in handler.last_request
