"""Verify and publish a repair using the existing immutable projection store."""
from dataclasses import replace
from pathlib import Path

from sqlalchemy import text

from app.core.config import settings
from .errors import AgentImportError
from .execution_control import checkpoint
from .source_code import SourceSnapshot, canonical_bytes, digest_bytes
from .revisions import RevisionStore


def revision_store(engine):
    return RevisionStore(engine, settings.resolved_zp_output_root / "revisions",
        build_sha256=settings.viewer_build_id or SourceSnapshot.capture(settings.agent_source_root).identity,
        signing_key=(settings.agent_verification_signing_key or "").encode())


def publish_repair(service, task, parent, decision, compiled, fence):
    from .delivery import validate_candidate_application
    from .verification import load_acceptance_contract
    from .revision_validation import verify_revision_projection
    from .maintenance import check_task_fence
    from .workflow import _execution_source
    from .asset_retention import register_asset

    if not settings.agent_candidate_verification_enabled or not settings.agent_revision_reads_enabled:
        raise AgentImportError("REVISION_VERIFICATION_NOT_CONFIGURED", "Repair publication requires source, application and revision verification.", status_code=409)
    strategy = parent.strategy_payload or {}
    retained = strategy.get("input_snapshot")
    requirements = strategy.get("requirements_sha256")
    if not retained or not requirements or settings.agent_verification_oracle_root is None:
        raise AgentImportError("VERIFICATION_BASELINE_REQUIRED", "The published source acceptance contract is required for a repair.", status_code=409)
    source = Path(_execution_source(parent))
    contract = load_acceptance_contract((settings.agent_verification_oracle_root / f"{retained['sha256']}-{requirements}.json").read_text(encoding="utf-8"))
    if contract.schema_version < 2:
        raise AgentImportError("APPLICATION_VALIDATION_COVERAGE_MISSING", "Repair publication requires full-source reconciliation.", status_code=409)
    store = revision_store(service.engine)
    with service.engine.connect() as db:
        head = db.execute(text("SELECT active_revision_id FROM dataset_revision_heads WHERE dataset_id=:id"), {"id": task["dataset_id"]}).scalar() or "legacy"
    if head != task["revision_id"]:
        raise AgentImportError("REVISION_BASE_CONFLICT", "Another repair changed this dataset; submit feedback against the current result.", status_code=409)
    evidence_root = settings.resolved_zp_output_root / "agent-cases" / task["task_id"] / "revision-verification"
    evidence_root.mkdir(parents=True, exist_ok=True)
    environment = digest_bytes(canonical_bytes({"build": store.build, "verifier": contract.verifier_version,
        "postgres": str(settings.agent_verification_postgres_bin), "node": str(settings.agent_verification_node)}))

    def prepare(candidate, payload, identity):
        context = replace(parent, case_id=identity, candidate_payload=payload)
        app_receipt = validate_candidate_application(context, Path(candidate), input_root=source)
        checkpoint()
        revision = store.prepare_from_zp(parent.dataset_id, parent.dataset_slug, source_sha256=retained["sha256"],
            zp_path=candidate, environment_sha256=environment)
        projection = verify_revision_projection(store, revision, contract=contract, input_root=source, ledger_path=evidence_root / f"{revision}.sqlite")
        checkpoint()
        store.seal(revision, app_receipt, projection_receipt=projection)
        return revision

    baseline = prepare(parent.candidate_zp_path, parent.candidate_payload, task["task_id"] + "-original") if head == "legacy" else None
    revision = prepare(compiled.zp_path, decision.candidate.model_dump(mode="json"), task["task_id"])
    checkpoint()
    activate_baseline = store.activation_action(baseline, expected_base="legacy") if baseline else None
    activate_repair = store.activation_action(revision, expected_base=baseline or head)
    with service.engine.begin() as db:
        check_task_fence(db, task["task_id"], fence, lock=True)
        if activate_baseline:
            activate_baseline(db)
        activate_repair(db)
        register_asset(db, compiled.zp_path, compiled.output_sha256, kind="candidate_zp", owner="revision:" + revision)
        for relative, entry in retained["files"].items():
            register_asset(db, source / relative, entry["sha256"], kind="source", owner="revision:" + revision)
        db.execute(text("""UPDATE agent_maintenance_tasks SET state='PUBLISHED',published_revision_id=:revision,
            candidate_json=:candidate,candidate_path=:path,candidate_sha256=:sha,decision_json=:decision,
            wait_reason=NULL,lease_token=NULL,lease_until=NULL WHERE task_id=:id"""),
            {"revision": revision, "candidate": decision.candidate.model_dump_json(), "path": str(compiled.zp_path),
             "sha": compiled.output_sha256, "decision": decision.model_dump_json(), "id": task["task_id"]})
    return revision


def list_revisions(service, case_id):
    parent = service.get_case(case_id)
    with service.engine.connect() as db:
        head = db.execute(text("SELECT active_revision_id FROM dataset_revision_heads WHERE dataset_id=:id"), {"id": parent.dataset_id}).scalar() or "legacy"
        rows = db.execute(text("""SELECT revision_id,base_revision_id,state FROM dataset_revisions
            WHERE dataset_id=:id AND state IN ('ACTIVE','RETIRED') ORDER BY revision_id"""), {"id": parent.dataset_id}).mappings().all()
    return {"active_revision_id": head, "revisions": [dict(row) for row in rows]}


def rollback_revision(service, case_id, revision, expected_base):
    parent = service.get_case(case_id)
    store = revision_store(service.engine)
    row = store._row(revision)
    if not parent.ever_published or row["dataset_id"] != parent.dataset_id:
        raise AgentImportError("REVISION_DATASET_MISMATCH", "Select a retained revision of this dataset.", status_code=409)
    with service.engine.connect() as db:
        published = db.execute(text("SELECT event_id FROM dataset_revision_events WHERE dataset_id=:id AND to_revision=:revision LIMIT 1"),
            {"id": parent.dataset_id, "revision": revision}).scalar()
    if row["state"] not in {"ACTIVE", "RETIRED"} or not published:
        raise AgentImportError("REVISION_NOT_READABLE", "Only a previously published dataset version can be restored.", status_code=409)
    store.activate(revision, expected_base=expected_base, rollback=True)
    return list_revisions(service, case_id)
