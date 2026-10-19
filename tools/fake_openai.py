#!/usr/bin/env python3
"""A tiny OpenAI-compatible server that stands in for the PD pool in the simulated cluster.

    python3 tools/fake_openai.py --port 8000 [--model sim-model] [--token-delay-ms 2]

Serves what rm-bench and the llm-d gateway clients use, with no model behind it:

- GET  /v1/models              one model
- POST /v1/chat/completions    streaming (SSE, chunked, one content chunk per token, a usage chunk, [DONE])
                               or a plain JSON reply when "stream" is false
- POST /v1/completions         non-streaming, with rngd-pd style server timing ("pd": {ttft_ms, wall_ms})
- GET  /health                 200

Replies are "t0 t1 ..." with max_tokens tokens. Python 3.9+, stdlib only.
"""
import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_MODEL = "sim-model"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # chunked streaming, as vLLM / llm-d send it
    model = DEFAULT_MODEL
    token_delay_s = 0.002
    requests_served = 0
    _lock = threading.Lock()

    def log_message(self, *args):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code, message):
        self._json(code, {"error": {"message": message, "type": "invalid_request_error", "code": code}})

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/v1/models":
            self._json(200, {"object": "list", "data": [{"id": self.model, "object": "model", "owned_by": "airm-sim"}]})
        elif path == "/health":
            self._json(200, {"status": "ok"})
        else:
            self._error(404, f"no route {path}")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            self._error(400, "body is not JSON")
            return
        if not isinstance(req, dict):
            self._error(400, "body is not a JSON object")
            return
        if req.get("model") not in (None, self.model):
            self._error(404, f"model {req.get('model')!r} not served (have {self.model!r})")
            return
        n = max(1, int(req.get("max_tokens") or 16))
        with self._lock:
            type(self).requests_served += 1
        if path == "/v1/chat/completions":
            if req.get("stream"):
                self._stream_chat(n)
            else:
                self._chat(n)
        elif path == "/v1/completions":
            self._completion(n)
        else:
            self._error(404, f"no route {path}")

    def _tokens(self, n):
        for i in range(n):
            time.sleep(self.token_delay_s)
            yield f"t{i} "

    def _usage(self, n):
        return {"prompt_tokens": 1, "completion_tokens": n, "total_tokens": n + 1}

    def _stream_chat(self, n):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def send(data):
            event = f"data: {data}\n\n".encode()
            self.wfile.write(b"%x\r\n%s\r\n" % (len(event), event))
            self.wfile.flush()

        rid = f"chatcmpl-sim-{time.monotonic_ns()}"
        for tok in self._tokens(n):
            send(json.dumps({"id": rid, "object": "chat.completion.chunk", "model": self.model,
                             "choices": [{"index": 0, "delta": {"content": tok}, "finish_reason": None}]}))
        send(json.dumps({"id": rid, "object": "chat.completion.chunk", "model": self.model, "choices": [],
                         "usage": self._usage(n)}))
        send("[DONE]")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _chat(self, n):
        text = "".join(self._tokens(n))
        self._json(200, {"id": "chatcmpl-sim", "object": "chat.completion", "model": self.model,
                         "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                      "finish_reason": "length"}],
                         "usage": self._usage(n)})

    def _completion(self, n):
        t0 = time.perf_counter()
        first = None
        text = ""
        for tok in self._tokens(n):
            first = first if first is not None else time.perf_counter()
            text += tok
        wall_ms = (time.perf_counter() - t0) * 1000
        self._json(200, {"id": "cmpl-sim", "object": "text_completion", "model": self.model,
                         "choices": [{"index": 0, "text": text, "finish_reason": "length"}],
                         "usage": self._usage(n),
                         "pd": {"ttft_ms": round((first - t0) * 1000, 3), "wall_ms": round(wall_ms, 3)}})


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
            return   # a client dropped an idle keep-alive connection
        super().handle_error(request, client_address)


def serve(host="127.0.0.1", port=0, model=DEFAULT_MODEL, token_delay_s=0.002):
    """Start the server in a background thread; returns it (server.server_address, server.shutdown())."""
    handler = type("SimHandler", (Handler,), {"model": model, "token_delay_s": token_delay_s,
                                              "requests_served": 0})
    srv = _Server((host, port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--token-delay-ms", type=float, default=2.0)
    args = ap.parse_args(argv)
    srv = serve(args.host, args.port, args.model, args.token_delay_ms / 1000)
    host, port = srv.server_address[:2]
    print(f"fake OpenAI-compatible server on http://{host}:{port} (model {args.model})", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
