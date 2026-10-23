"""Real slow-drip HTTP responses must obey the total timeout, and lose their socket."""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from rm_bench import client


@pytest.fixture
def drip_server():
    class Drip(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        mode = "json"
        stopped = threading.Event()
        disconnected = threading.Event()

        def log_message(self, *args):
            pass

        def handle(self):
            try:
                super().handle()
            except ConnectionError:
                self.disconnected.set()

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            try:
                if self.mode == "headers":
                    self.wfile.write(b"HTTP/1.1 200 OK\r\nX-Drip: ")
                else:
                    self.send_response(200)
                    if self.mode == "json":
                        body = json.dumps({"choices": [{"text": "one two"}],
                                           "usage": {"completion_tokens": 2}}).encode()
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(body) + 60))
                    else:
                        self.send_header("Content-Type", "text/event-stream")
                        if self.mode == "chunked":
                            self.send_header("Transfer-Encoding", "chunked")
                        else:
                            self.send_header("Connection", "close")
                            self.close_connection = True
                    self.end_headers()
                for _ in range(60):
                    # No line break: neither iter_lines nor JSON decoding can yield to the caller.
                    self.wfile.write(b"1\r\nx\r\n" if self.mode == "chunked" else b" ")
                    self.wfile.flush()
                    time.sleep(0.02)
                if self.mode == "json":
                    self.wfile.write(body)
                elif self.mode == "headers":
                    self.wfile.write(b"\r\nContent-Length: 0\r\n\r\n")
                elif self.mode == "chunked":
                    self.wfile.write(b"0\r\n\r\n")
            except ConnectionError:
                self.disconnected.set()
            finally:
                self.stopped.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Drip)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", Drip
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.mark.parametrize("send,mode", [
    (client.stream_chat, "chunked"),
    (client.stream_chat, "close"),
    (client.stream_chat, "json"),
    (client.complete, "json"),
    (client.stream_chat, "headers"),
    (client.complete, "headers"),
])
def test_total_deadline_interrupts_drips_and_closes_connection(drip_server, send, mode):
    url, handler = drip_server
    handler.mode = mode
    before = set(threading.enumerate())
    start = time.perf_counter()
    record = send(url, "m", 2, 2, timeout_s=0.2)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.65, f"timeout_s=0.2 took {elapsed:.2f}s"
    assert not record.ok
    assert handler.disconnected.wait(0.4), "request left the server connection open"
    assert handler.stopped.wait(0.4)
    assert not [t for t in threading.enumerate() if t not in before and t.is_alive()
                and isinstance(t, threading.Timer)], "deadline worker leaked"


@pytest.mark.parametrize("send", [client.stream_chat, client.complete])
def test_connect_attempts_share_one_deadline(monkeypatch, send):
    class BlackHole:
        def __init__(self, *args):
            self.timeout = None

        def setsockopt(self, *args):
            pass

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, address):
            time.sleep(self.timeout)
            raise socket.timeout("black-holed address")

        def close(self):
            pass

        def dup(self):
            return self

        def shutdown(self, *args):
            pass

    addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))
                 for ip in ("192.0.2.1", "192.0.2.2", "192.0.2.3")]
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args: addresses)
    monkeypatch.setattr(socket, "socket", BlackHole)
    start = time.perf_counter()
    record = send("http://example.invalid", "m", 1, 2, timeout_s=0.15)
    elapsed = time.perf_counter() - start
    assert not record.ok
    assert elapsed < 0.3, f"timeout_s=0.15 took {elapsed:.2f}s over three addresses"


def test_socket_creation_failure_tries_next_address(drip_server, monkeypatch):
    url, _ = drip_server
    port = int(url.rsplit(":", 1)[1])
    address = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))
    original_socket = socket.socket
    first = True

    def create_socket(*args, **kwargs):
        nonlocal first
        if first:
            first = False
            raise OSError("address family unavailable")
        return original_socket(*args, **kwargs)

    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args: [address, address])
    monkeypatch.setattr(socket, "socket", create_socket)
    record = client.complete(url, "m", 1, 2, timeout_s=5)
    assert record.ok and record.out_tokens == 2
