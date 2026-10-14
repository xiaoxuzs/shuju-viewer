"""Portable schema bootstrap for Agent Import business state."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.core.db import engine as default_engine


_DDL = (
    """
    CREATE TABLE IF NOT EXISTS agent_import_cases (
        case_id VARCHAR(36) PRIMARY KEY,
        workspace_id VARCHAR(100) NOT NULL,
        status VARCHAR(32) NOT NULL,
        source_mode VARCHAR(24) NOT NULL,
        source_ref TEXT NOT NULL,
        dataset_fingerprint CHAR(32) NOT NULL,
        analysis_category VARCHAR(80) NOT NULL,
        source_profile VARCHAR(160) NOT NULL,
        format_details TEXT NULL,
        interaction_mode VARCHAR(16) NOT NULL,
        autonomous_attempt_used INTEGER NOT NULL DEFAULT 0,
        guided_attempt_no INTEGER NOT NULL DEFAULT 0,
        context_revision INTEGER NOT NULL DEFAULT 1,
        version INTEGER NOT NULL DEFAULT 1,
        lease_owner VARCHAR(100) NULL,
        lease_expires_at TEXT NULL,
        stop_requested_at TEXT NULL,
        strategy_payload TEXT NULL,
        candidate_payload TEXT NULL,
        verification_payload TEXT NULL,
        candidate_zp_path TEXT NULL,
        candidate_zp_sha256 CHAR(64) NULL,
        dataset_id BIGINT NULL,
        dataset_slug VARCHAR(160) NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_attempts (
        attempt_id VARCHAR(36) PRIMARY KEY,
        case_id VARCHAR(36) NOT NULL REFERENCES agent_import_cases(case_id) ON DELETE CASCADE,
        attempt_no INTEGER NOT NULL,
        context_revision INTEGER NOT NULL,
        result VARCHAR(16) NOT NULL,
        failure_code VARCHAR(100) NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL,
        UNIQUE(case_id, attempt_no, context_revision)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_messages (
        message_id VARCHAR(36) PRIMARY KEY,
        case_id VARCHAR(36) NOT NULL REFERENCES agent_import_cases(case_id) ON DELETE CASCADE,
        sequence_no INTEGER NOT NULL,
        context_revision INTEGER NOT NULL,
        sender_type VARCHAR(16) NOT NULL,
        message_kind VARCHAR(16) NOT NULL,
        content TEXT NOT NULL,
        structured_payload TEXT NULL,
        idempotency_key VARCHAR(100) NULL,
        created_at TEXT NOT NULL,
        UNIQUE(case_id, sequence_no),
        UNIQUE(case_id, idempotency_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_artifacts (
        artifact_id VARCHAR(36) PRIMARY KEY,
        case_id VARCHAR(36) NOT NULL REFERENCES agent_import_cases(case_id) ON DELETE CASCADE,
        attempt_id VARCHAR(36) NULL REFERENCES agent_attempts(attempt_id) ON DELETE SET NULL,
        artifact_type VARCHAR(64) NOT NULL,
        storage_ref TEXT NOT NULL,
        sha256 CHAR(64) NOT NULL,
        size_bytes BIGINT NOT NULL,
        media_type VARCHAR(100) NULL,
        payload_json TEXT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_notifications (
        notification_id VARCHAR(36) PRIMARY KEY,
        case_id VARCHAR(36) NOT NULL REFERENCES agent_import_cases(case_id) ON DELETE CASCADE,
        kind VARCHAR(32) NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        created_at TEXT NOT NULL,
        resolved_at TEXT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_agent_cases_status_lease ON agent_import_cases(status, lease_expires_at)",
    "CREATE INDEX IF NOT EXISTS ix_agent_cases_workspace_updated ON agent_import_cases(workspace_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS ix_agent_messages_case_sequence ON agent_messages(case_id, sequence_no)",
    "CREATE INDEX IF NOT EXISTS ix_agent_artifacts_case_type ON agent_artifacts(case_id, artifact_type)",
    "CREATE INDEX IF NOT EXISTS ix_agent_notifications_active ON agent_notifications(active, kind)",
    """
    CREATE TABLE IF NOT EXISTS agent_deliveries (
        case_id VARCHAR(36) PRIMARY KEY REFERENCES agent_import_cases(case_id),
        operation_key CHAR(64) NOT NULL UNIQUE,
        dataset_id BIGINT NOT NULL UNIQUE,
        candidate_sha256 CHAR(64) NOT NULL,
        handover_sha256 CHAR(64) NOT NULL,
        published_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_engineering_operations (
        operation_key CHAR(64) PRIMARY KEY,
        case_id VARCHAR(36) NOT NULL REFERENCES agent_import_cases(case_id),
        context_revision INTEGER NOT NULL,
        lease_token VARCHAR(36) NOT NULL,
        state VARCHAR(40) NOT NULL,
        candidate_sha256 CHAR(64) NOT NULL,
        result_json TEXT NULL
    )
    """,
)


def ensure_agent_import_schema(db_engine: Engine | None = None) -> None:
    with (db_engine or default_engine).begin() as connection:
        for statement in _DDL:
            connection.execute(text(statement))
        _widen_analysis_category_column(connection)
        _ensure_artifact_payload_column(connection)
        _ensure_execution_columns(connection)
        from app.agent_import.authorization_ledger import DDL as authorization_ddl
        for statement in authorization_ddl:
            connection.execute(text(statement))
        from app.agent_import.local_sessions import DDL as session_ddl
        for statement in session_ddl:
            connection.execute(text(statement))
        from app.agent_import.maintenance import DDL as maintenance_ddl
        connection.execute(text(maintenance_ddl))
        from app.agent_import.revisions import DDL as revision_ddl
        for statement in revision_ddl:
            connection.execute(text(statement))
        from app.agent_import.import_recipes import DDL as recipe_ddl
        for statement in recipe_ddl:
            connection.execute(text(statement))
        from app.agent_import.asset_retention import DDL as retention_ddl
        for statement in retention_ddl:
            connection.execute(text(statement))
        from app.agent_import.admission_policy import DDL as policy_ddl
        for statement in policy_ddl:
            connection.execute(text(statement))
        from sqlalchemy import inspect
        bound_columns = {c["name"] for c in inspect(connection).get_columns("agent_case_authority")}
        if "policy_id" not in bound_columns:
            connection.execute(text("ALTER TABLE agent_case_authority ADD COLUMN policy_id TEXT NULL"))
        from app.agent_import.maintenance import ensure_consumer_columns
        ensure_consumer_columns(connection)
        from app.agent_import.task_runtime import DDL as task_ddl
        for statement in task_ddl:
            connection.execute(text(statement))
        from app.agent_import.asset_retention import DDL as retention_ddl
        for statement in retention_ddl:
            connection.execute(text(statement))


def _widen_analysis_category_column(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    current_length = connection.execute(
        text(
            """
            SELECT character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'agent_import_cases'
              AND column_name = 'analysis_category'
            """
        )
    ).scalar_one_or_none()
    if current_length is not None and current_length < 80:
        connection.execute(
            text(
                "ALTER TABLE agent_import_cases "
                "ALTER COLUMN analysis_category TYPE VARCHAR(80)"
            )
        )


def _ensure_artifact_payload_column(connection: Connection) -> None:
    from sqlalchemy import inspect

    columns = {item["name"] for item in inspect(connection).get_columns("agent_artifacts")}
    if "payload_json" not in columns:
        connection.execute(text("ALTER TABLE agent_artifacts ADD COLUMN payload_json TEXT NULL"))


def _ensure_execution_columns(connection: Connection) -> None:
    from sqlalchemy import inspect

    columns = {item["name"] for item in inspect(connection).get_columns("agent_import_cases")}
    for name, ddl in {
        "lease_token": "VARCHAR(36) NULL",
        "deadline_at": "TEXT NULL",
        "model_tokens_reserved": "BIGINT NOT NULL DEFAULT 0",
        "delivery_policy": "VARCHAR(20) NOT NULL DEFAULT 'manual'",
        "ever_published": "INTEGER NOT NULL DEFAULT 0",
        "progress_payload": "TEXT NULL",
        "owner_id": "TEXT NOT NULL DEFAULT 'unowned'",
        "source_content_sha256": "TEXT NULL",
        "authorization_wait_reason": "TEXT NULL",
        "authorization_resume_status": "TEXT NULL",
    }.items():
        if name not in columns:
            connection.execute(text(f"ALTER TABLE agent_import_cases ADD COLUMN {name} {ddl}"))
    connection.execute(text("UPDATE agent_import_cases SET ever_published=1 WHERE ever_published=0 AND (status='SUCCESS' OR dataset_id IS NOT NULL)"))
