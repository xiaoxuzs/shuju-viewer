from pathlib import Path
import os

import pytest

from app.core.config import Settings
from app.local_start import prepare_environment


def configured(tmp_path):
    pg = tmp_path / "postgres"
    pg.mkdir()
    for name in ("initdb", "postgres", "pg_ctl"):
        (pg / (name + (".exe" if os.name == "nt" else ""))).write_text("metadata-only fixture; not executed")
    node = tmp_path / "node"
    node.write_text("metadata-only fixture; not executed")
    browser = tmp_path / "browser"
    (browser / "chromium-fixture").mkdir(parents=True)
    return Settings(_env_file=None, database_url="postgresql://fixture@localhost/viewer_test_fixture", data_root=tmp_path,
        agent_source_root=tmp_path, agent_verification_postgres_bin=pg, agent_verification_node=node,
        agent_verification_browser_cache=browser, agent_verification_signing_key="fixture-" * 8,
        openai_api_key="synthetic-fixture", openai_base_url="http://model-fixture.invalid/v1", openai_model="gpt-fixture")


def test_normal_start_sets_roles_and_independent_validation_without_per_case_inputs(tmp_path):
    settings = configured(tmp_path)
    before = settings.model_dump()
    env, root = prepare_environment(settings, {"VIEWER_ENV": "test"})
    assert env["OPENAI_API_KEY"] == "synthetic-fixture"
    assert env["AGENT_API_WORKER_ENABLED"] == "false"
    assert env["AGENT_INPUT_SNAPSHOT_ENABLED"] == env["AGENT_CANDIDATE_VERIFICATION_ENABLED"] == "true"
    assert env["AGENT_IMPLEMENTATION_REQUEST_TIMEOUT_SECONDS"] == "300"
    assert env["AGENT_IMPLEMENTATION_MAX_OUTPUT_TOKENS"] == "8192"
    assert env["AGENT_CASE_TOKEN_BUDGET"] == "750000"
    assert not (root / "source-contracts").exists()  # no source-specific bootstrap
    assert settings.model_dump() == before
    overridden, _ = prepare_environment(settings, {"VIEWER_ENV": "test", "AGENT_IMPLEMENTATION_REQUEST_TIMEOUT_SECONDS": "240", "AGENT_CASE_TOKEN_BUDGET": "1000"})
    assert overridden["AGENT_IMPLEMENTATION_REQUEST_TIMEOUT_SECONDS"] == "240"
    assert overridden["AGENT_CASE_TOKEN_BUDGET"] == "1000"


def test_normal_start_refuses_production_remote_or_missing_prerequisites(tmp_path):
    settings = configured(tmp_path)
    with pytest.raises(RuntimeError, match="production"):
        prepare_environment(settings, {"VIEWER_ENV": "production"})
    settings.database_url = "postgresql://remote.invalid/not-local"
    with pytest.raises(RuntimeError, match="local PostgreSQL"):
        prepare_environment(settings, {})
    settings.database_url = "postgresql://localhost/viewer_test_fixture"
    settings.agent_verification_node = tmp_path / "missing-node"
    with pytest.raises(RuntimeError, match="prerequisite"):
        prepare_environment(settings, {})
