"""Fixed staging probe in the validator's already isolated application database."""

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    if os.environ.get("VIEWER_ENV") != "test" or not os.environ.get("VIEWER_BUILD_ID"):
        raise SystemExit("Staging probe requires an explicitly identified validation process")
    from sqlalchemy import text
    from app.core.db import SessionLocal
    from app.agent_zp.service import stage_agent_zp_candidate
    from app.declarative_ingest import read_semantic_zp
    from app.agent_import.input_assets import hash_file
    from app.schemas.agent_zp import AgentZpImportCreateIn
    from app.agent_import.case_service import CaseService
    from app.agent_import.migrations import ensure_agent_import_schema
    from app.agent_import.execution_control import ExecutionFence, execution_scope
    from app.agent_import.errors import AgentImportError

    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    semantic = read_semantic_zp(args.candidate)
    ensure_agent_import_schema()
    cases = CaseService()
    execution_case = cases.create_case(source_ref=str(args.candidate.parent), dataset_fingerprint=semantic.source_fingerprint,
                                      analysis_category="BOTTOM_UP", source_profile="lease-probe", format_details=None, owner_id="validator")
    first = cases.claim_next(worker_id="first-probe", lease_seconds=60)
    assert first and first.case_id == execution_case.case_id
    cases.start_analysis(first.case_id)
    with cases.engine.begin() as connection:
        connection.execute(text("UPDATE agent_import_cases SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE case_id=:id"), {"id": first.case_id})
    second = cases.claim_next(worker_id="second-probe", lease_seconds=60)
    assert second and second.lease_token != first.lease_token
    assert not cases.renew_lease(first.case_id, worker_id="first-probe", lease_seconds=60, lease_token=first.lease_token)
    rejected = False
    with execution_scope(ExecutionFence(first.case_id, first.lease_token, lambda _: 60)):
        try:
            cases.save_strategy(first.case_id, {"forbidden": "stale-worker"})
        except AgentImportError as exc:
            rejected = exc.code == "WORKER_LEASE_LOST"
    assert rejected and cases.get_case(first.case_id).strategy_payload is None
    body = AgentZpImportCreateIn(source_path=str(args.candidate), slug="candidate-staging", name="Candidate staging",
                               analysis_category="BOTTOM_UP", source_profile="candidate", binary_operation="register_existing_zp")
    with SessionLocal() as session:
        if session.scalar(text("SELECT count(*) FROM datasets")) != 0:
            raise RuntimeError("Validation database was not initially empty")
        staged = stage_agent_zp_candidate(session, body, case_id="external-staging", expected_sha256=hash_file(args.candidate),
                                         source_fingerprint=semantic.source_fingerprint)
    with SessionLocal() as session:
        for table in ("datasets", "runs", "identification_matches", "dataset_zp_assets"):
            if session.scalar(text(f"SELECT count(*) FROM {table}")) != 0:
                raise RuntimeError("Staging projection escaped rollback")
    args.output.write_text(json.dumps({"verification": staged.verification, "database_rollback": True,
                                      "postgres_stale_worker_rejected": rejected,
                                      "cache_lifetime": "separate probe process; rollback alone does not clear caches"}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
