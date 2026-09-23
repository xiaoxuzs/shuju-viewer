import pytest

from app.agent_import.errors import AgentImportError
from app.agent_import.model_routing import route_for
from app.core.config import settings


def test_every_role_uses_exactly_one_connection(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "synthetic-key")
    monkeypatch.setattr(settings, "openai_base_url", "http://127.0.0.1:55597/v1")
    monkeypatch.setattr(settings, "openai_model", "gpt-configured-test")
    routes = [route_for(role) for role in ("research", "implementation", "review", "maintenance")]
    assert all(r.model == "gpt-configured-test" for r in routes)
    assert all(r.api_key == "synthetic-key" for r in routes)
    assert all(r.base_url == "http://127.0.0.1:55597/v1" for r in routes)
    maintenance = route_for("maintenance")
    assert maintenance.model == "gpt-configured-test"
    assert maintenance.max_tokens == settings.agent_maintenance_max_output_tokens
    with pytest.raises(ValueError, match="Unimplemented"):
        route_for("unimplemented-role")


def test_incomplete_single_connection_is_not_replaced_by_another_provider(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "synthetic-key")
    monkeypatch.setattr(settings, "openai_base_url", "")
    for role in ("research", "implementation", "review", "maintenance"):
        with pytest.raises(AgentImportError) as failure:
            route_for(role)
        assert failure.value.code == "MODEL_PROFILE_INVALID"


def test_local_profile_is_opt_in_and_refuses_production(monkeypatch):
    from app.agent_import.local_profile import apply_local_gpt_profile
    monkeypatch.setenv("VIEWER_ENV", "production")
    with pytest.raises(RuntimeError, match="explicit"):
        apply_local_gpt_profile()


@pytest.mark.parametrize("finish,refusal", [("length", None), ("stop", "refused"), ("tool_calls", None)])
def test_valid_json_is_not_executable_if_refused_or_truncated(monkeypatch, finish, refusal):
    from app.agent_import import model_provider
    from app.agent_import.execution_control import ExecutionFence, execution_scope
    monkeypatch.setattr(model_provider, "request_model_json", lambda *_a, **_k: {
        "choices": [{"finish_reason": finish, "message": {"content": "{}", "refusal": refusal}}]})
    with execution_scope(ExecutionFence("test", "test", lambda _: 10)), pytest.raises(RuntimeError, match="refused or did not complete"):
        model_provider._chat_json(base_url="http://127.0.0.1", api_key="synthetic", model="gpt-test", timeout=1,
                                  system_prompt="json", payload={}, max_tokens=256)


def test_final_implementation_and_review_requests_apply_context_guard(monkeypatch):
    from app.agent_import import model_provider
    monkeypatch.setattr(model_provider.urlrequest, "urlopen", lambda *_a, **_k: pytest.fail("overbudget network egress"))
    for role in ("implementation", "review"):
        with pytest.raises(AgentImportError) as failure:
            model_provider._chat_json(base_url="http://127.0.0.1", api_key="synthetic", model="gpt-test", timeout=1,
                system_prompt="json", payload={"untrusted": "x" * 200000}, max_tokens=256, role=role)
        assert failure.value.code == "MODEL_CONTEXT_BUDGET_EXCEEDED"


def test_final_research_request_applies_context_guard(monkeypatch):
    from app.agent_import.kimi_research_runtime import UrllibJsonTransport
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: pytest.fail("overbudget network egress"))
    with pytest.raises(AgentImportError) as failure:
        UrllibJsonTransport(base_url="http://127.0.0.1", api_key="synthetic").request_json(
            "POST", "/chat/completions", body={"messages": [{"content": "x" * 200000}]}, timeout=1)
    assert failure.value.code == "MODEL_CONTEXT_BUDGET_EXCEEDED"


def test_model_change_invalidates_prior_model_evidence(monkeypatch):
    from types import SimpleNamespace
    from app.agent_import.model_routing import model_route_identity
    from app.agent_import.workflow import _assert_model_routes
    monkeypatch.setattr(settings, "openai_api_key", "synthetic-key")
    monkeypatch.setattr(settings, "openai_model", "gpt-before")
    previous = model_route_identity()
    monkeypatch.setattr(settings, "openai_model", "gpt-after")
    for strategy in ({"model_route_identity": previous}, {}):
        with pytest.raises(AgentImportError) as failure:
            _assert_model_routes(SimpleNamespace(strategy_payload=strategy))
        assert failure.value.code == "MODEL_ROUTE_CHANGED"


def test_local_profile_keeps_existing_gpt_route_and_explicit_180_timeout(tmp_path, monkeypatch):
    import dotenv
    from app.agent_import.local_profile import apply_local_gpt_profile
    monkeypatch.setenv("VIEWER_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{(tmp_path / 'unused.sqlite').as_posix()}")
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "process-override")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-process-override")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1/v1")
    for name in ("AGENT_API_WORKER_ENABLED", "AGENT_CASE_TOKEN_BUDGET", "AGENT_READ_MAX_OUTPUT_TOKENS", "AGENT_IMPLEMENTATION_MAX_OUTPUT_TOKENS",
                 "AGENT_REVIEW_MAX_OUTPUT_TOKENS", "AGENT_RESEARCH_REASONING_EFFORT", "OPENAI_REQUEST_TIMEOUT_SECONDS", "AGENT_IMPLEMENTATION_REQUEST_TIMEOUT_SECONDS"):
        monkeypatch.setenv(name, "old-value")
    monkeypatch.setattr(dotenv, "dotenv_values", lambda _: {"OPENAI_API_KEY": "dotenv-key", "DATABASE_URL": "must-not-copy"})
    apply_local_gpt_profile()
    import os
    assert os.environ["OPENAI_API_KEY"] == "process-override"
    assert os.environ["OPENAI_MODEL"] == "gpt-process-override"
    assert os.environ["OPENAI_REQUEST_TIMEOUT_SECONDS"] == "300"
    assert os.environ["DATABASE_URL"].startswith("sqlite")


def test_local_profile_rejects_formal_or_remote_database(monkeypatch):
    from app.agent_import.local_profile import apply_local_gpt_profile
    monkeypatch.setenv("VIEWER_ENV", "test")
    monkeypatch.setenv("DATA_ROOT", "placeholder")
    for url in ("postgresql://localhost/production", "postgresql://remote.invalid/viewer_test_probe"):
        monkeypatch.setenv("DATABASE_URL", url)
        with pytest.raises(RuntimeError, match="PostgreSQL"):
            apply_local_gpt_profile()


def test_retired_provider_environment_variables_are_not_credentials(monkeypatch):
    from app.core.config import Settings
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("MOONSHOT_API_KEY", "obsolete-fixture")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "obsolete-fixture")
    configured = Settings(_env_file=None)
    assert configured.openai_api_key is None
    assert "moonshot_api_key" not in Settings.model_fields
    assert "deepseek_api_key" not in Settings.model_fields
    assert "agent_model_profile" not in Settings.model_fields
