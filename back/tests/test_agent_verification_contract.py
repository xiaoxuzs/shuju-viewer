from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.agent_import.verification import (
    CandidateVerifier, VerificationRuntime, restricted_environment, seal_record, verify_receipt,
)
from app.agent_import.input_assets import content_manifest, freeze_source
from app.agent_import.errors import AgentImportError


def receipt_record():
    return {"status": "PASSED", "code_sha256": "a" * 64, "candidate_sha256": "b" * 64,
            "source_sha256": "c" * 64, "browser_assertions": [{"name": "independent source oracle"}],
            "import_result": {"dataset_id": 1}, "cleanup": {"processes_stopped": True}}


def verify(receipt):
    verify_receipt(receipt, b"x" * 32, code_sha256="a" * 64, candidate_sha256="b" * 64, source_sha256="c" * 64)


def test_agent_cannot_turn_failed_receipt_into_passed_by_changing_json():
    failed = {**receipt_record(), "status": "FAILED"}
    receipt = seal_record(failed, b"x" * 32)
    receipt["record"]["status"] = "PASSED"
    with pytest.raises(ValueError, match="signature"):
        verify(receipt)


def test_stale_candidate_or_source_or_code_rejects_signed_receipt():
    for field in ("code_sha256", "candidate_sha256", "source_sha256"):
        record = receipt_record()
        record[field] = "d" * 64
        with pytest.raises(ValueError, match="stale"):
            verify(seal_record(record, b"x" * 32))


def test_no_browser_or_import_cannot_satisfy_verification_gate():
    record = receipt_record()
    record["browser_assertions"] = []
    with pytest.raises(ValueError, match="browser"):
        verify(seal_record(record, b"x" * 32))


def test_child_environment_does_not_inherit_privileged_values(tmp_path, monkeypatch):
    for name in ("DATABASE_URL", "OPENAI_API_KEY", "HTTPS_PROXY", "NODE_OPTIONS", "PYTHONPATH"):
        monkeypatch.setenv(name, "private")
    env = restricted_environment(tmp_path)
    assert "private" not in env.values()
    assert env["TEMP"] == str(tmp_path)


def test_generated_code_has_no_host_execution_fallback(tmp_path):
    runtime = VerificationRuntime(*(tmp_path for _ in range(6)))
    with pytest.raises(ValueError, match="sandbox"):
        CandidateVerifier(runtime, signing_key=b"x" * 32).verify(tmp_path, None, case_id="blocked", generated_code=True)


def test_source_content_change_with_same_size_and_mtime_invalidates_snapshot(tmp_path):
    import os
    source = tmp_path / "source"
    source.mkdir()
    value = source / "values.tsv"
    value.write_text("value\n1\n", encoding="utf-8")
    before = value.stat()
    frozen = tmp_path / "retained"
    saved = freeze_source(source, frozen)
    assert content_manifest(frozen / "files") == saved
    value.write_text("value\n2\n", encoding="utf-8")
    os.utime(value, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(AgentImportError, match="identity"):
        freeze_source(source, frozen)


def test_source_credentials_are_rejected_without_copying(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / ".env").write_text("secret", encoding="utf-8")
    with pytest.raises(AgentImportError):
        freeze_source(source, tmp_path / "retained")
    assert not (tmp_path / "retained").exists()
def test_verification_runtime_resolves_evidence_before_child_cwd_changes(tmp_path, monkeypatch):
    from app.agent_import.verification import VerificationRuntime
    from pathlib import Path
    monkeypatch.chdir(tmp_path)
    runtime = VerificationRuntime(**{name: Path(name) for name in (
        "source_root", "postgres_bin", "python", "node", "browser_cache", "evidence_root")})
    assert runtime.evidence_root == tmp_path / "evidence_root"


def test_verifier_cancellable_http_preserves_list_responses_without_model_budget():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    from app.agent_import.verification import _json_http
    from app.agent_import.model_audit import diagnostic_budget
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"[]")
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with diagnostic_budget(lambda _: pytest.fail("business HTTP counted as model call"), calls=0, seconds=5):
            assert _json_http(f"http://127.0.0.1:{server.server_port}") == []
        with pytest.raises(ValueError, match="loopback"):
            _json_http("https://example.invalid")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
