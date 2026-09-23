import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.agent_import.model_http import request_model_json
from app.agent_import.model_audit import diagnostic_budget, code_fingerprint


def test_model_http_stalled_response_has_a_real_wall_clock_limit():
    finished = threading.Event()
    response_started = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{")
            self.wfile.flush()
            response_started.set()
            finished.wait(10)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    started = time.monotonic()
    records = []
    try:
        with diagnostic_budget(records.append, calls=1, seconds=4), pytest.raises(TimeoutError):
            request_model_json(f"http://127.0.0.1:{server.server_port}/model", method="POST", api_key="synthetic-test-key", body={}, timeout=1.0)
        assert time.monotonic() - started < 4
        assert response_started.is_set(), "The test must exercise a real stalled HTTP response"
        assert records[0]["transport_capture_complete"] is True
        assert records[0]["transport_timings"]["response_headers_seconds"] >= 0
        assert records[0]["transport_timings"]["first_body_byte_seconds"] >= 0
    finally:
        finished.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_loaded_code_fingerprint_does_not_change_after_execution():
    def sample():
        return {"constant": [1, 2, 3]}
    before = code_fingerprint(sample.__code__)
    for _ in range(100):
        sample()
    assert before == code_fingerprint(sample.__code__)


def test_no_response_headers_is_distinguished_from_connection_or_body_stall():
    finished = threading.Event()
    received = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            received.set()
            finished.wait(5)
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    records = []
    try:
        with diagnostic_budget(records.append, calls=1, seconds=4), pytest.raises(TimeoutError):
            request_model_json(f"http://127.0.0.1:{server.server_port}/model", method="POST", api_key="synthetic", body={}, timeout=1)
        assert received.is_set()
        timing = records[0]["transport_timings"]
        assert timing["phase"] == "waiting_response_headers"
        assert timing["connection_seconds"] >= 0 and timing["request_sent_seconds"] >= 0
        assert "response_headers_seconds" not in timing
    finally:
        finished.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_loaded_code_fingerprint_is_stable_across_process_hash_seeds():
    import os
    import subprocess
    import sys
    code = "from app.agent_import.model_audit import code_fingerprint\ndef sample(v):\n return v in {'a','b','c'}\nprint(code_fingerprint(sample.__code__))"
    env = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "TEMP", "TMP") if name in os.environ}
    outputs = [subprocess.check_output([sys.executable, "-B", "-c", code], env={**env, "PYTHONHASHSEED": seed}, timeout=10)
               for seed in ("1", "2")]
    assert outputs[0] == outputs[1]
