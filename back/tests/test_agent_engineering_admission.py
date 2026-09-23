from dataclasses import replace

import pytest

from app.agent_import.engineering_admission import CHECKS, seal_admission, verify_admission, configured_runner
from app.agent_import.sandbox_runner import DockerPolicy
from app.agent_import.errors import AgentImportError


def test_admission_binds_exact_engine_image_policy_and_expiry(tmp_path):
    executable = tmp_path / "fake-engine"
    executable.write_bytes(b"not executable; signature contract test only")
    policy = DockerPolicy(executable=executable, engine="unix:///fixture.sock", image="sha256:" + "a" * 64)
    key = b"synthetic-admission-key-for-offline-test"
    receipt = seal_admission(policy, dict.fromkeys(CHECKS, True), key, now=100)
    assert len(verify_admission(receipt, policy, key, now=101)) == 64
    for changed in (replace(policy, memory_mb=2048), replace(policy, image="sha256:" + "b"*64), replace(policy, engine="unix:///other.sock")):
        with pytest.raises(AgentImportError):
            verify_admission(receipt, changed, key, now=101)
    with pytest.raises(AgentImportError):
        verify_admission(receipt, policy, key, now=1000)
    with pytest.raises(AgentImportError):
        verify_admission({"record": receipt["record"], "signature": "true"}, policy, key, now=101)
    executable.write_bytes(b"engine changed")
    with pytest.raises(AgentImportError):
        verify_admission(receipt, policy, key, now=101)


def test_partial_or_failed_probe_cannot_issue_admission(tmp_path):
    executable = tmp_path / "fake-engine"
    executable.write_bytes(b"offline")
    policy = DockerPolicy(executable=executable, engine="unix:///fixture.sock", image="sha256:" + "a"*64)
    with pytest.raises(ValueError):
        seal_admission(policy, {"non_root": True}, b"x"*32)
    with pytest.raises(ValueError):
        seal_admission(policy, {**dict.fromkeys(CHECKS, True), "network_denied": False}, b"x"*32)


def test_runtime_does_not_invent_a_runner_without_explicit_environment(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "agent_engineering_enabled", True)
    monkeypatch.setattr(settings, "agent_engineering_executable", None)
    assert configured_runner() is None
