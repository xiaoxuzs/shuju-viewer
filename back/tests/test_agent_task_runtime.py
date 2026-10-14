"""Ordinary product tasks: no grant rows, real policies/fences/request journal."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.agent_import.case_service import CaseService
from app.agent_import.migrations import ensure_agent_import_schema
from app.agent_import.execution_control import ExecutionFence, execution_scope, checkpoint
from app.agent_import.task_runtime import TaskRuntime, task_scope
from app.agent_import.authorization_ledger import route_identity
from app.agent_import.errors import AgentImportError
from app.agent_import import model_http
from app.core.config import settings


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agent_model_authorization_required", True)
    monkeypatch.setattr(settings, "openai_base_url", "http://127.0.0.1:19999/_test")
    monkeypatch.setattr(settings, "openai_api_key", "synthetic-local-only")
    monkeypatch.setattr(settings, "openai_model", "gpt-test-fixture")
    monkeypatch.setattr(settings, "agent_case_token_budget", 1000)
    target = os.environ.get("VIEWER_TASK_TEST_URL")
    if target:
        url = make_url(target)
        assert url.get_backend_name() == "postgresql" and url.host == "127.0.0.1" and url.database.startswith("viewer_test_")
        schema = "task_fixture_" + uuid.uuid4().hex
        admin = create_engine(url)
        with admin.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        admin.dispose()
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'tasks.sqlite'}", connect_args={"timeout": 15})
    ensure_agent_import_schema(engine)
    source = tmp_path / "source"
    source.mkdir()
    (source / "table.tsv").write_text("id\tvalue\na\t0\n")
    service = CaseService(engine)
    case = service.create_case(source_ref=str(source), dataset_fingerprint="a"*32, analysis_category="BOTTOM_UP", source_profile="fixture", format_details=None, owner_id="owner")
    yield service, case, TaskRuntime(engine, case.case_id)
    with engine.connect() as db:
        for table in ("agent_authorizations", "agent_case_authority", "agent_import_policies", "agent_authorized_lineages", "agent_experiments"):
            assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0
    engine.dispose()


def scope(service, case):
    return execution_scope(ExecutionFence(case.case_id, case.lease_token, lambda amount: service.check_execution(case.case_id, case.lease_token, amount)))


def reserve(task, identity):
    return task.reserve(role="research", route_sha256=route_identity(settings.openai_base_url+"/chat/completions", settings.openai_model),
        request_bytes=450, output_limit=50, request_sha256="b"*64, request_id=identity)


def test_default_product_submission_is_claimable_without_any_grant(runtime):
    service, case, _ = runtime
    assert case.status.value == "CREATED"
    assert case.authorization_wait_reason is None
    claimed = service.claim_next(worker_id="normal")
    assert claimed.case_id == case.case_id
    again = service.create_case(source_ref=case.source_ref, dataset_fingerprint=case.dataset_fingerprint, analysis_category=case.analysis_category,
        source_profile=case.source_profile, format_details=None, owner_id="owner")
    assert again.case_id == case.case_id


def publish_fixture(service, case):
    with service.engine.begin() as db:
        db.execute(text("UPDATE agent_import_cases SET status='SUCCESS',ever_published=1,dataset_id=7,dataset_slug='existing' WHERE case_id=:id"),
            {"id": case.case_id})


def test_pre_fix_content_key_reuses_only_the_same_unpublished_metadata_task(runtime):
    from app.agent_import.admission_policy import submission_identity
    service, case, _ = runtime
    previous_key = submission_identity(case.owner_id, case.workspace_id, case.source_content_sha256,
        case.analysis_category, case.source_profile, case.format_details)
    with service.engine.begin() as db:
        db.execute(text("UPDATE agent_submission_keys SET submission_key=:key WHERE case_id=:id"),
            {"key": previous_key, "id": case.case_id})
    kwargs = dict(source_ref=case.source_ref, dataset_fingerprint=case.dataset_fingerprint,
        analysis_category=case.analysis_category, source_profile=case.source_profile, format_details=None, owner_id="owner")
    assert service.create_case(**kwargs).case_id == case.case_id
    kwargs["dataset_fingerprint"] = "b"*32
    assert service.create_case(**kwargs).case_id != case.case_id


def test_published_same_metadata_submission_returns_delivery_before_new_task(runtime):
    service, case, _ = runtime
    publish_fixture(service, case)
    result = service.create_case(source_ref=case.source_ref, dataset_fingerprint=case.dataset_fingerprint,
        analysis_category="AUTO", source_profile="different user label", format_details="different details", owner_id="owner")
    assert result.case_id == case.case_id and result.ever_published and result.dataset_id == 7
    with service.engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM agent_import_cases")).scalar_one() == 1
        assert db.execute(text("SELECT count(*) FROM agent_task_runs")).scalar_one() == 1
        assert db.execute(text("SELECT count(*) FROM agent_task_requests")).scalar_one() == 0


@pytest.mark.parametrize("published", [False, True])
def test_same_content_new_metadata_is_independent_and_idempotent(runtime, tmp_path, published):
    from pathlib import Path
    import shutil
    from app.fingerprint import compute_dataset_metadata_fingerprint
    service, case, _ = runtime
    if published:
        publish_fixture(service, case)
    fresh = tmp_path / "copy"
    fresh.mkdir()
    shutil.copyfile(Path(case.source_ref) / "table.tsv", fresh / "table.tsv")
    fingerprint = compute_dataset_metadata_fingerprint(fresh).fingerprint
    kwargs = dict(source_ref=str(fresh), dataset_fingerprint=fingerprint, analysis_category=case.analysis_category,
        source_profile=case.source_profile, format_details=None, owner_id="owner")
    independent = service.create_case(**kwargs)
    assert independent.case_id != case.case_id
    assert independent.source_content_sha256 == case.source_content_sha256
    assert not independent.ever_published and independent.dataset_id is None
    assert service.create_case(**kwargs).case_id == independent.case_id
    with service.engine.connect() as db:
        run = db.execute(text("SELECT kind,parent_case_id FROM agent_task_runs WHERE task_id=:id"), {"id": independent.case_id}).one()
        assert tuple(run) == ("initial", None)
    claimed = service.claim_next(worker_id="independent")
    if claimed.case_id != independent.case_id:
        service.request_stop(claimed.case_id)
        claimed = service.claim_next(worker_id="independent")
    assert claimed.case_id == independent.case_id
    task = TaskRuntime(service.engine, claimed.case_id)
    # Reproduce the old content-only parent association retained in historical tasks.
    if published:
        with service.engine.begin() as db:
            db.execute(text("UPDATE agent_task_runs SET parent_case_id=:parent WHERE task_id=:id"),
                {"parent": case.case_id, "id": independent.case_id})
    with scope(service, claimed):
        task.reserve(role="implementation", route_sha256=route_identity(settings.openai_base_url+"/chat/completions", settings.openai_model),
            request_bytes=100, output_limit=50, request_sha256="c"*64)
        with pytest.raises(AgentImportError) as failure:
            task.reserve(role="maintenance", route_sha256=route_identity(settings.openai_base_url+"/chat/completions", settings.openai_model),
                request_bytes=100, output_limit=50, request_sha256="d"*64)
        assert failure.value.code == "TASK_ROLE_INVALID"


@pytest.mark.parametrize("publication", [{"ever_published": 1}, {"dataset_id": 7}])
@pytest.mark.parametrize("role", ["implementation", "initial_engineering"])
def test_published_own_dataset_still_forbids_initial_implementation(runtime, publication, role):
    service, case, task = runtime
    claimed = service.claim_next(worker_id="normal")
    field, value = next(iter(publication.items()))
    with service.engine.begin() as db:
        db.execute(text(f"UPDATE agent_import_cases SET {field}=:value WHERE case_id=:id"), {"value": value, "id": case.case_id})
    with scope(service, claimed), pytest.raises(AgentImportError) as failure:
        task.reserve(role=role, route_sha256=route_identity(settings.openai_base_url+"/chat/completions", settings.openai_model),
            request_bytes=100, output_limit=50, request_sha256="c"*64)
    assert failure.value.code == "PUBLISHED_CASE_ROLE_FORBIDDEN"
    assert service.get_case(case.case_id).model_tokens_reserved == 0


@pytest.mark.parametrize("field,value", [("owner_id", "other"), ("workspace_id", "other")])
def test_published_source_reuse_does_not_cross_owner_or_workspace(runtime, field, value):
    service, case, _ = runtime
    publish_fixture(service, case)
    kwargs = dict(source_ref=case.source_ref, dataset_fingerprint=case.dataset_fingerprint,
        analysis_category=case.analysis_category, source_profile=case.source_profile, format_details=None, owner_id="owner")
    kwargs[field] = value
    assert service.create_case(**kwargs).case_id != case.case_id


def test_published_metadata_collision_with_changed_content_does_not_return_stale_delivery(runtime):
    from pathlib import Path
    service, case, _ = runtime
    publish_fixture(service, case)
    (Path(case.source_ref) / "table.tsv").write_text("id\tvalue\na\t1\n")
    with pytest.raises(AgentImportError) as failure:
        service.create_case(source_ref=case.source_ref, dataset_fingerprint=case.dataset_fingerprint,
            analysis_category=case.analysis_category, source_profile=case.source_profile, format_details=None, owner_id="owner")
    assert failure.value.code == "SOURCE_FINGERPRINT_CONFLICT"


def test_retry_of_historical_failed_duplicate_reuses_delivery_without_resetting_history(runtime):
    from app.agent_import.task_retry import retry_task
    service, case, _ = runtime
    duplicate = service.create_case(source_ref=case.source_ref, dataset_fingerprint=case.dataset_fingerprint,
        analysis_category="AUTO", source_profile="different label", format_details=None, owner_id="owner")
    with service.engine.begin() as db:
        db.execute(text("UPDATE agent_import_cases SET status='FAILED',model_tokens_reserved=250 WHERE case_id=:id"), {"id": duplicate.case_id})
        db.execute(text("UPDATE agent_task_runs SET parent_case_id=:parent,ended_at=1,reserved_units=250,request_count=2 WHERE task_id=:id"),
            {"parent": case.case_id, "id": duplicate.case_id})
    publish_fixture(service, case)
    result = retry_task(service, duplicate.case_id, duplicate.version)
    assert result.case_id == case.case_id and result.dataset_slug == "existing"
    unchanged = service.get_case(duplicate.case_id)
    assert unchanged.status.value == "FAILED" and unchanged.context_revision == 1 and unchanged.model_tokens_reserved == 250
    assert not service.list_artifacts(duplicate.case_id)
    with service.engine.connect() as db:
        run = db.execute(text("SELECT ended_at,request_count,reserved_units FROM agent_task_runs WHERE task_id=:id"), {"id": duplicate.case_id}).one()
        assert tuple(run) == (1, 2, 250)


def test_frozen_policy_atomic_reservation_concurrent_last_units(runtime, monkeypatch):
    service, case, task = runtime
    claimed = service.claim_next(worker_id="normal")
    monkeypatch.setattr(settings, "agent_case_token_budget", 1000000)  # cannot expand recorded policy
    def request(n):
        with scope(service, claimed):
            try:
                return reserve(task, str(n))[0]
            except AgentImportError as exc:
                assert exc.code == "TASK_RUN_LIMIT_REACHED"
                return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(list(filter(None, pool.map(request, range(6))))) == 2
    assert service.get_case(case.case_id).model_tokens_reserved == 1000
    with service.engine.connect() as db:
        assert db.execute(text("SELECT request_count FROM agent_task_runs")).scalar_one() == 2


def test_request_identity_unsent_release_unknown_outcome_and_replay(runtime):
    service, case, task = runtime
    claimed = service.claim_next(worker_id="normal")
    with scope(service, claimed):
        reserve(task, "one")
        reserve(task, "one")
        task.finish("one", response=False, result={"reason": "known unsent"})
        assert service.get_case(case.case_id).model_tokens_reserved == 0
        reserve(task, "two")
        task.mark_sending("two")
        with pytest.raises(AgentImportError):
            task.mark_sending("two")
        task.finish("two", response=False, result={"error_type": "TimeoutError"})
    assert service.get_case(case.case_id).model_tokens_reserved == 500
    with service.engine.connect() as db:
        assert dict(db.execute(text("SELECT request_id,outcome FROM agent_task_requests")).all()) == {"one": "NOT_SENT", "two": "UNKNOWN"}


def test_cancel_stale_fence_late_result_and_preview_persist(runtime):
    service, case, task = runtime
    claimed = service.claim_next(worker_id="normal")
    with scope(service, claimed), task_scope(task):
        task.charge_preview(131072)
        with pytest.raises(AgentImportError):
            TaskRuntime(service.engine, case.case_id).charge_preview(1)
        reserve(task, "late")
        task.mark_sending("late")
        service.request_stop(case.case_id)
        assert not task.finish("late", response=True, result={"usage": None})
        with pytest.raises(AgentImportError):
            checkpoint()
    with pytest.raises(AgentImportError):
        task.mark_sending("late")


def test_missing_key_rejected_before_any_reservation_or_child(runtime, monkeypatch):
    service, _, task = runtime
    claimed = service.claim_next(worker_id="normal")
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(model_http, "_bounded_child", lambda *a, **k: pytest.fail("No request should be dispatched"))
    with scope(service, claimed), task_scope(task), pytest.raises(AgentImportError) as exc:
        model_http.request_model_json(settings.openai_base_url+"/chat/completions", method="POST", api_key="", body={"model": settings.openai_model, "max_completion_tokens": 50}, timeout=10, role="research")
    assert exc.value.code == "MODEL_PROFILE_INVALID"
    assert service.get_case(claimed.case_id).model_tokens_reserved == 0


def test_cancel_at_model_progress_releases_prepared_reservation_without_sending(runtime, monkeypatch):
    service, case, task = runtime
    claimed = service.claim_next(worker_id="normal")
    def cancel(_phase):
        service.request_stop(case.case_id)
        raise AgentImportError("AGENT_CANCELLED", "Cancelled before dispatch")
    monkeypatch.setattr(model_http, "report_progress", cancel)
    monkeypatch.setattr(model_http, "_bounded_child", lambda *a, **k: pytest.fail("Cancelled preparation must not dispatch"))
    with scope(service, claimed), task_scope(task), pytest.raises(AgentImportError):
        model_http.request_model_json(settings.openai_base_url+"/chat/completions", method="POST", api_key=settings.openai_api_key,
            body={"model": settings.openai_model, "max_completion_tokens": 50}, timeout=10, role="research")
    with service.engine.connect() as db:
        assert db.execute(text("SELECT outcome FROM agent_task_requests")).scalar() == "NOT_SENT"
        row = db.execute(text("SELECT request_count,reserved_units FROM agent_task_runs")).one()
        assert tuple(row) == (0, 0)
    assert service.get_case(case.case_id).model_tokens_reserved == 0


def test_real_transport_boundary_without_grant_keeps_usage(runtime, monkeypatch):
    service, _, task = runtime
    claimed = service.claim_next(worker_id="normal")
    monkeypatch.setattr(model_http, "_bounded_child", lambda *a, **k: {"model": "gpt-test-fixture", "usage": {"total_tokens": 8}, "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})
    with scope(service, claimed), task_scope(task):
        result = model_http.request_model_json(settings.openai_base_url+"/chat/completions", method="POST", api_key=settings.openai_api_key,
            body={"model": settings.openai_model, "max_completion_tokens": 50}, timeout=10, role="research")
    assert result["usage"]["total_tokens"] == 8
    with service.engine.connect() as db:
        row = db.execute(text("SELECT outcome,result_json FROM agent_task_requests")).one()
        assert row.outcome == "RESPONSE" and json.loads(row.result_json)["usage"]["total_tokens"] == 8


def test_research_http_retry_is_finite_and_each_attempt_is_audited(runtime, monkeypatch):
    from urllib.error import HTTPError
    from app.agent_import.kimi_research_runtime import UrllibJsonTransport
    service, _, task = runtime
    claimed = service.claim_next(worker_id="normal")
    calls = []
    def failing(*args, **kwargs):
        calls.append(1)
        raise HTTPError("<synthetic>", 503, "fixture unavailable", {}, None)
    monkeypatch.setattr(model_http, "_bounded_child", failing)
    transport = UrllibJsonTransport(base_url=settings.openai_base_url, api_key=settings.openai_api_key)
    with scope(service, claimed), task_scope(task), pytest.raises(Exception):
        transport.request_json("POST", "/chat/completions", body={"model": settings.openai_model, "max_completion_tokens": 50}, timeout=10)
    assert len(calls) == 2  # existing MAX_HTTP_RETRIES=1; not an unbounded retry
    with service.engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM agent_task_requests WHERE outcome='UNKNOWN'")).scalar() == 2


def test_takeover_rejects_old_sender_and_expiry_does_not_charge(runtime):
    service, case, task = runtime
    first = service.claim_next(worker_id="first")
    with scope(service, first):
        reserve(task, "prepared")
    with service.engine.begin() as db:
        db.execute(text("UPDATE agent_import_cases SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE case_id=:id"), {"id": case.case_id})
    second = service.claim_next(worker_id="second")
    with scope(service, first), pytest.raises(AgentImportError) as exc:
        task.mark_sending("prepared")
    assert exc.value.code == "WORKER_LEASE_LOST"
    task.finish("prepared", response=False, result={"reason": "old sender never dispatched"})
    with service.engine.begin() as db:
        db.execute(text("UPDATE agent_import_cases SET deadline_at='2000-01-01T00:00:00+00:00' WHERE case_id=:id"), {"id": case.case_id})
    with scope(service, second), pytest.raises(AgentImportError) as exc:
        reserve(task, "expired")
    assert exc.value.code == "TASK_RUN_LIMIT_REACHED"
    assert service.get_case(case.case_id).model_tokens_reserved == 0


def test_explicit_retry_preserves_history_and_is_version_guarded(runtime):
    from app.agent_import.task_retry import retry_task
    service, case, task = runtime
    with service.engine.begin() as db:
        db.execute(text("UPDATE agent_import_cases SET status='FAILED',model_tokens_reserved=250 WHERE case_id=:id"), {"id": case.case_id})
        db.execute(text("UPDATE agent_task_runs SET reserved_units=250,request_count=2,preview_used=100,ended_at=1,deadline_at=1 WHERE task_id=:id"), {"id": case.case_id})
    retried = retry_task(service, case.case_id, case.version)
    assert retried.status.value == "CREATED" and retried.context_revision == 2
    assert retried.model_tokens_reserved == 250
    with service.engine.connect() as db:
        run = db.execute(text("SELECT * FROM agent_task_runs")).mappings().one()
        assert run["request_count"] == 2 and run["preview_used"] == 100
        assert json.loads(run["policy_json"])["reservation_units"] == 1250
    assert any(a.artifact_type == "task_retry" for a in service.list_artifacts(case.case_id))
    with pytest.raises(AgentImportError):
        retry_task(service, case.case_id, case.version)
    assert service.claim_next(worker_id="retry-worker").case_id == case.case_id


def test_retry_reuses_research_only_for_same_model_connection(runtime, monkeypatch):
    from app.agent_import.task_retry import retry_task
    service, case, task = runtime
    with service.engine.begin() as db:
        db.execute(text("UPDATE agent_import_cases SET status='NEEDS_USER',strategy_payload=:strategy WHERE case_id=:id"),
            {"id": case.case_id, "strategy": json.dumps({"model_route_identity": "old-policy", "observations": []})})
    monkeypatch.setattr(settings, "agent_implementation_request_timeout_seconds", 300)
    retried = retry_task(service, case.case_id, case.version)
    assert retried.status.value == "STRATEGY_READY"
    assert retried.strategy_payload["research_reuse"]["research_reexecuted"] is False
    assert retried.strategy_payload["research_reuse"]["research_route_identity"] == "old-policy"
    with service.engine.begin() as db:
        db.execute(text("UPDATE agent_import_cases SET status='FAILED' WHERE case_id=:id"), {"id": case.case_id})
    monkeypatch.setattr(settings, "openai_model", "different-model")
    with pytest.raises(AgentImportError) as exc:
        retry_task(service, case.case_id, retried.version)
    assert exc.value.code == "MODEL_ROUTE_CHANGED"
