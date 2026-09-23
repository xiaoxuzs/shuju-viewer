import time
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.agent_import.admission_policy import ImportPolicy, install_policy, wake_waiting
from app.agent_import.authorization_ledger import AuthorizationLedger, authority_scope, route_identity
from app.agent_import.case_service import CaseService
from app.agent_import.execution_control import ExecutionFence, execution_scope
from app.agent_import.errors import AgentImportError
from app.agent_import.migrations import ensure_agent_import_schema
from app.core.config import settings


@pytest.fixture
def policy_system(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agent_model_authorization_required", True)
    monkeypatch.setattr(settings, "openai_base_url", "http://127.0.0.1:19999/api/v1/_test")
    monkeypatch.setattr(settings, "openai_model", "gpt-test-fixture")
    monkeypatch.setattr(settings, "openai_api_key", "synthetic")
    target = os.environ.get("VIEWER_POLICY_TEST_URL")
    if target:
        url = make_url(target)
        assert url.get_backend_name() == "postgresql" and url.host in {"127.0.0.1", "localhost"} and url.database.startswith("viewer_test_")
        schema = "policy_fixture_" + uuid.uuid4().hex
        admin = create_engine(url)
        with admin.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        admin.dispose()
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'control.sqlite'}", connect_args={"timeout": 15})
    ensure_agent_import_schema(engine)
    source = tmp_path / "source"
    source.mkdir()
    (source / "table.tsv").write_text("id\tvalue\na\t0\n")
    ledger = AuthorizationLedger(engine)
    contract = {"request_limit": 4, "reservation_limit": 10000, "active_seconds": 600, "experiment_seconds": 300,
        "output_limit": 512, "route_sha256": route_identity(settings.openai_base_url + "/chat/completions", settings.openai_model),
        "roles": ["research", "implementation", "review"], "authorization_basis": "Offline synthetic contract tests only"}
    ledger.register("fixture", contract)
    policy = ImportPolicy(policy_id="fixture-policy", authorization_id="fixture", owner_id="owner", environment="test", source_root=str(source),
        valid_until=time.time()+600, experiment_seconds=300, case_calls=4, case_units=10000,
        stages={r: {"calls": 4, "units": 10000, "seconds": 300} for r in contract["roles"]})
    yield CaseService(engine), ledger, source, policy
    engine.dispose()


def create(service, source, owner="owner"):
    return service.create_case(source_ref=str(source), dataset_fingerprint="a"*32, analysis_category="BOTTOM_UP", source_profile="fixture", format_details=None, owner_id=owner, execution_mode="legacy_experiment")


def test_waiting_task_is_preserved_not_claimed_and_automatically_wakes(policy_system):
    service, ledger, source, policy = policy_system
    case = create(service, source)
    assert case.status.value == "WAITING_AUTHORIZATION"
    assert case.model_tokens_reserved == 0
    assert service.claim_next(include_legacy=True, worker_id="before-policy") is None
    install_policy(service.engine, policy)
    install_policy(service.engine, policy)  # restart must not reset grant
    wake_waiting(service)
    claimed = service.claim_next(include_legacy=True, worker_id="worker")
    assert claimed.case_id == case.case_id
    assert ledger.binding(case.case_id)
    assert ledger.status("fixture")["calls_used"] == 0


def test_concurrent_submission_reuses_case_and_one_experiment(policy_system):
    service, ledger, source, policy = policy_system
    install_policy(service.engine, policy)
    with ThreadPoolExecutor(max_workers=6) as pool:
        cases = list(pool.map(lambda _: create(service, source), range(6)))
    assert len({c.case_id for c in cases}) == 1
    with service.engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM agent_experiments")).scalar() == 1
    assert create(service, source, "other-owner").status.value == "WAITING_AUTHORIZATION"


def test_atomic_request_case_global_and_stage_counters_and_unsent_release(policy_system):
    service, ledger, source, policy = policy_system
    install_policy(service.engine, policy)
    case = create(service, source)
    claimed = service.claim_next(include_legacy=True, worker_id="worker")
    binding = ledger.binding(case.case_id)
    fence = ExecutionFence(case.case_id, claimed.lease_token, lambda amount: service.check_execution(case.case_id, claimed.lease_token, amount))
    def reserve(identity):
        return ledger.reserve(*binding, role="research", route_sha256=route_identity(settings.openai_base_url+"/chat/completions", settings.openai_model),
            request_bytes=100, output_limit=50, request_sha256="c"*64, request_id=identity)
    with execution_scope(fence), authority_scope(ledger, *binding):
        reserve("one")
        reserve("one")
        assert service.get_case(case.case_id).model_tokens_reserved == 150
        assert ledger.status("fixture")["calls_used"] == 1
        ledger.release_unsent("one", "test controller confirms no dispatch")
        assert service.get_case(case.case_id).model_tokens_reserved == 0
        assert ledger.status("fixture")["calls_used"] == 0
        reserve("two")
    with pytest.raises(AgentImportError, match="lease"):
        ledger.mark_sending("two")  # dropping the execution context cannot bypass fencing
    with execution_scope(fence), authority_scope(ledger, *binding):
        ledger.mark_sending("two")
        with pytest.raises(AgentImportError):
            ledger.mark_sending("two")
        ledger.finish_request("two", outcome="UNKNOWN", result={"lost_connection": True})
        with pytest.raises(AgentImportError):
            ledger.release_unsent("two", "not allowed")
        assert service.get_case(case.case_id).model_tokens_reserved == 150


def test_cancel_waiting_and_expired_policy_do_not_send_or_charge(policy_system):
    service, ledger, source, policy = policy_system
    case = create(service, source)
    assert service.request_stop(case.case_id).status.value == "STOPPED"
    install_policy(service.engine, policy)
    wake_waiting(service)
    assert service.claim_next(include_legacy=True, worker_id="worker") is None
    assert ledger.status("fixture")["reserved_units"] == 0


def test_last_quota_concurrent_reservations_and_revocation(policy_system):
    service, ledger, source, policy = policy_system
    install_policy(service.engine, policy)
    case = create(service, source)
    claimed = service.claim_next(include_legacy=True, worker_id="worker")
    binding = ledger.binding(case.case_id)
    def reserve(number):
        fence = ExecutionFence(case.case_id, claimed.lease_token, lambda amount: service.check_execution(case.case_id, claimed.lease_token, amount))
        with execution_scope(fence):
            try:
                request, _ = ledger.reserve(*binding, role="research", route_sha256=route_identity(settings.openai_base_url+"/chat/completions", settings.openai_model),
                    request_bytes=100, output_limit=50, request_sha256="c"*64, request_id=f"concurrent-{number}")
                return request
            except AgentImportError as exc:
                assert exc.code in {"MODEL_STAGE_BUDGET_EXHAUSTED", "MODEL_DIAGNOSTIC_BUDGET_EXCEEDED", "MODEL_AUTHORIZATION_BUDGET_EXCEEDED"}
                return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        accepted = list(filter(None, pool.map(reserve, range(8))))
    assert len(accepted) == 4
    assert ledger.status("fixture")["calls_used"] == 4
    assert service.get_case(case.case_id).model_tokens_reserved == 600
    ledger.revoke("fixture")
    with pytest.raises(AgentImportError, match="revoked"):
        ledger.mark_sending(accepted[0])
    # PREPARED has not been sent and can be reconciled after revocation.
    ledger.release_unsent(accepted[0], "controller confirmed no send")
    assert ledger.status("fixture")["calls_used"] == 3


def test_wait_reason_does_not_churn_and_expired_policy_cannot_activate(policy_system):
    service, ledger, source, policy = policy_system
    case = create(service, source)
    wake_waiting(service)
    assert service.get_case(case.case_id).version == case.version
    install_policy(service.engine, policy)
    # Simulate passage of time without sleeping or mutating the installed policy.
    from unittest.mock import patch
    with patch("app.agent_import.admission_policy.time.time", return_value=policy.valid_until + 1):
        wake_waiting(service)
    waiting = service.get_case(case.case_id)
    assert waiting.status.value == "WAITING_AUTHORIZATION"
    assert waiting.authorization_wait_reason == "POLICY_EXPIRED"
    assert not ledger.binding(case.case_id)
    assert waiting.model_tokens_reserved == 0


def test_stale_fence_cannot_dispatch_prepared_request(policy_system):
    service, ledger, source, policy = policy_system
    install_policy(service.engine, policy)
    case = create(service, source)
    claimed = service.claim_next(include_legacy=True, worker_id="worker")
    binding = ledger.binding(case.case_id)
    fence = ExecutionFence(case.case_id, claimed.lease_token, lambda amount: 10)
    with execution_scope(fence):
        request, _ = ledger.reserve(*binding, role="research", route_sha256=route_identity(settings.openai_base_url+"/chat/completions", settings.openai_model),
            request_bytes=100, output_limit=50, request_sha256="d"*64)
        service.request_stop(case.case_id)
        with pytest.raises(AgentImportError):
            ledger.mark_sending(request)
    ledger.release_unsent(request, "cancelled before dispatch")
    assert ledger.status("fixture")["calls_used"] == 0
