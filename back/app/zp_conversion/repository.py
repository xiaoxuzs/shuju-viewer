"""Database persistence for ZP conversion jobs and artifacts."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.db import engine as _db_engine
from app.core.logging import get_logger
from app.zp_conversion.contracts import ZpArtifact, ZpConversionJob

log = get_logger(__name__)


def ensure_zp_conversion_schema() -> None:
    try:
        with _db_engine.begin() as conn:
            for statement in _schema_sql():
                conn.execute(text(statement))
            _migrate_binary_layer_version_column(conn)
    except Exception:  # noqa: BLE001
        log.exception("could not bootstrap ZP conversion schema")


def create_job(
    *,
    job_id: str,
    source_path: Path,
    dataset_slug: str | None,
    paths: Any,
    format_version: int,
    input_bytes: int,
) -> ZpConversionJob:
    _validate_uuid(job_id)
    now = _now_sql()
    with _db_engine.begin() as conn:
        conn.execute(
            text(
                f"""
                INSERT INTO zp_conversion_jobs (
                    job_id, status, stage, progress, dataset_slug, input_root,
                    zp_temp_path, zp_final_path, validation_certificate_path,
                    format_version, input_bytes, created_at, updated_at
                )
                VALUES (
                    :job_id, 'queued', 'queued', 0, :dataset_slug, :input_root,
                    :zp_temp_path, :zp_final_path, :validation_certificate_path,
                    :format_version, :input_bytes, {now}, {now}
                )
                """
            ),
            {
                "job_id": job_id,
                "dataset_slug": dataset_slug,
                "input_root": str(source_path),
                "zp_temp_path": str(paths.partial_path),
                "zp_final_path": str(paths.final_path),
                "validation_certificate_path": str(paths.certificate_path),
                "format_version": format_version,
                "input_bytes": input_bytes,
            },
        )
    job = get_job(job_id)
    if job is None:
        raise RuntimeError("ZP job insert did not return a readable row")
    return job


def get_job(job_id: str) -> ZpConversionJob | None:
    if not _looks_like_uuid(job_id):
        return None
    with _db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT job_id, status, stage, progress, dataset_slug, input_root,
                       zp_temp_path, zp_final_path, worker_pid, format_version,
                       binary_layer_version, input_bytes, output_bytes, output_sha256,
                       validation_mode, validation_certificate_path, error_code,
                       error_message, created_at, updated_at, finished_at
                FROM zp_conversion_jobs
                WHERE job_id = :job_id
                """
            ),
            {"job_id": job_id},
        ).mappings().one_or_none()
    return _row_to_job(dict(row)) if row is not None else None


def update_job(job_id: str, **kwargs: Any) -> None:
    if not _looks_like_uuid(job_id):
        return
    allowed = {
        "status",
        "stage",
        "progress",
        "worker_pid",
        "binary_layer_version",
        "output_bytes",
        "output_sha256",
        "validation_mode",
        "error_code",
        "error_message",
    }
    payload = {key: value for key, value in kwargs.items() if key in allowed}
    if not payload:
        return
    assignments = [f"{key} = :{key}" for key in payload]
    now = _now_sql()
    assignments.append(f"updated_at = {now}")
    if payload.get("status") in {"success", "failed", "cancelled"}:
        assignments.append(f"finished_at = COALESCE(finished_at, {now})")
    payload["job_id"] = job_id
    with _db_engine.begin() as conn:
        conn.execute(
            text(
                f"""
                UPDATE zp_conversion_jobs
                SET {", ".join(assignments)}
                WHERE job_id = :job_id
                """
            ),
            payload,
        )


def request_cancel(job_id: str) -> ZpConversionJob | None:
    if not _looks_like_uuid(job_id):
        return None
    now = _now_sql()
    with _db_engine.begin() as conn:
        conn.execute(
            text(
                f"""
                UPDATE zp_conversion_jobs
                SET status = 'cancelling', stage = 'cancelled', updated_at = {now}
                WHERE job_id = :job_id
                  AND status IN ('queued', 'running', 'cancelling')
                """
            ),
            {"job_id": job_id},
        )
    return get_job(job_id)


def dataset_id_for_slug(slug: str | None) -> int | None:
    if not slug:
        return None
    try:
        with _db_engine.begin() as conn:
            value = conn.scalar(text("SELECT dataset_id FROM datasets WHERE slug = :slug LIMIT 1"), {"slug": slug})
    except Exception:  # noqa: BLE001 - datasets may not exist in isolated unit tests
        return None
    return int(value) if value is not None else None


def register_asset(
    *,
    dataset_id: int,
    zp_path: Path,
    format_version: int,
    output_sha256: str,
    source_fingerprint: str | None = None,
    run_id: int | None = None,
    capabilities: dict[str, object] | None = None,
) -> None:
    payload = json.dumps(capabilities or {"spectra": True}, ensure_ascii=False, sort_keys=True)
    now = _now_sql()
    if _is_sqlite():
        statement = text(
            f"""
            INSERT INTO dataset_zp_assets (
                dataset_id, run_id, zp_path, format_version, source_fingerprint,
                output_sha256, status, capabilities, created_at, updated_at
            )
            VALUES (
                :dataset_id, :run_id, :zp_path, :format_version, :source_fingerprint,
                :output_sha256, 'active', :capabilities, {now}, {now}
            )
            """
        )
    else:
        statement = text(
            f"""
            INSERT INTO dataset_zp_assets (
                dataset_id, run_id, zp_path, format_version, source_fingerprint,
                output_sha256, status, capabilities, created_at, updated_at
            )
            VALUES (
                :dataset_id, :run_id, :zp_path, :format_version, :source_fingerprint,
                :output_sha256, 'active', CAST(:capabilities AS jsonb), {now}, {now}
            )
            """
        )
    with _db_engine.begin() as conn:
        conn.execute(
            statement,
            {
                "dataset_id": dataset_id,
                "run_id": run_id,
                "zp_path": str(zp_path),
                "format_version": format_version,
                "source_fingerprint": source_fingerprint,
                "output_sha256": output_sha256,
                "capabilities": payload,
            },
        )


def list_assets_for_dataset(dataset_id: int) -> list[ZpArtifact]:
    with _db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT asset_id, dataset_id, run_id, zp_path, format_version,
                       source_fingerprint, output_sha256, status, capabilities,
                       created_at, updated_at
                FROM dataset_zp_assets
                WHERE dataset_id = :dataset_id
                  AND status <> 'deleted'
                ORDER BY asset_id DESC
                """
            ),
            {"dataset_id": dataset_id},
        ).mappings().all()
    return [_row_to_asset(dict(row)) for row in rows]


def latest_job_for_dataset_slug(slug: str | None) -> ZpConversionJob | None:
    if not slug:
        return None
    with _db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT job_id, status, stage, progress, dataset_slug, input_root,
                       zp_temp_path, zp_final_path, worker_pid, format_version,
                       binary_layer_version, input_bytes, output_bytes, output_sha256,
                       validation_mode, validation_certificate_path, error_code,
                       error_message, created_at, updated_at, finished_at
                FROM zp_conversion_jobs
                WHERE dataset_slug = :slug
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"slug": slug},
        ).mappings().one_or_none()
    return _row_to_job(dict(row)) if row is not None else None


def _migrate_binary_layer_version_column(conn: Any) -> None:
    legacy_column = "viewer" + "_two_version"
    columns = _table_columns(conn, "zp_conversion_jobs")
    has_legacy = legacy_column in columns
    has_current = "binary_layer_version" in columns
    if has_legacy and not has_current:
        conn.execute(text(f"ALTER TABLE zp_conversion_jobs RENAME COLUMN {legacy_column} TO binary_layer_version"))
        return
    if not has_current:
        conn.execute(text("ALTER TABLE zp_conversion_jobs ADD COLUMN binary_layer_version TEXT NULL"))
        return
    if has_legacy:
        conn.execute(
            text(
                f"""
                UPDATE zp_conversion_jobs
                SET binary_layer_version = COALESCE(binary_layer_version, {legacy_column})
                """
            )
        )


def _table_columns(conn: Any, table_name: str) -> set[str]:
    if _is_sqlite():
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).mappings().all()
        return {str(row["name"]) for row in rows}
    rows = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).scalars().all()
    return {str(row) for row in rows}


def _schema_sql() -> tuple[str, ...]:
    if _is_sqlite():
        return (
            """
            CREATE TABLE IF NOT EXISTS zp_conversion_jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                stage TEXT NULL,
                progress REAL NOT NULL DEFAULT 0,
                dataset_slug TEXT NULL,
                input_root TEXT NOT NULL,
                zp_temp_path TEXT NULL,
                zp_final_path TEXT NULL,
                worker_pid INTEGER NULL,
                format_version INTEGER NOT NULL,
                binary_layer_version TEXT NULL,
                input_bytes INTEGER NULL,
                output_bytes INTEGER NULL,
                output_sha256 TEXT NULL,
                validation_mode TEXT NULL,
                validation_certificate_path TEXT NULL,
                error_code TEXT NULL,
                error_message TEXT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT NULL,
                CHECK (status IN ('queued', 'running', 'cancelling', 'success', 'failed', 'cancelled'))
            )
            """,
            (
                "CREATE INDEX IF NOT EXISTS ix_zp_conversion_jobs_status_updated_at "
                "ON zp_conversion_jobs(status, updated_at DESC)"
            ),
            "CREATE INDEX IF NOT EXISTS ix_zp_conversion_jobs_dataset_slug ON zp_conversion_jobs(dataset_slug)",
            """
            CREATE TABLE IF NOT EXISTS dataset_zp_assets (
                asset_id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_id INTEGER NOT NULL,
                run_id INTEGER NULL,
                zp_path TEXT NOT NULL,
                format_version INTEGER NOT NULL,
                source_fingerprint TEXT NULL,
                output_sha256 TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                capabilities TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK (status IN ('active', 'stale', 'deleted'))
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_dataset_zp_assets_dataset_status ON dataset_zp_assets(dataset_id, status)",
        )
    return (
        """
        CREATE TABLE IF NOT EXISTS zp_conversion_jobs (
            job_id UUID PRIMARY KEY,
            status VARCHAR(20) NOT NULL,
            stage VARCHAR(40) NULL,
            progress DOUBLE PRECISION NOT NULL DEFAULT 0,
            dataset_slug VARCHAR(160) NULL,
            input_root TEXT NOT NULL,
            zp_temp_path TEXT NULL,
            zp_final_path TEXT NULL,
            worker_pid INTEGER NULL,
            format_version INTEGER NOT NULL,
            binary_layer_version TEXT NULL,
            input_bytes BIGINT NULL,
            output_bytes BIGINT NULL,
            output_sha256 CHAR(64) NULL,
            validation_mode VARCHAR(20) NULL,
            validation_certificate_path TEXT NULL,
            error_code VARCHAR(80) NULL,
            error_message TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ NULL,
            CONSTRAINT ck_zp_conversion_jobs_status
                CHECK (status IN ('queued', 'running', 'cancelling', 'success', 'failed', 'cancelled'))
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS ix_zp_conversion_jobs_status_updated_at "
            "ON zp_conversion_jobs(status, updated_at DESC)"
        ),
        "CREATE INDEX IF NOT EXISTS ix_zp_conversion_jobs_dataset_slug ON zp_conversion_jobs(dataset_slug)",
        """
        CREATE TABLE IF NOT EXISTS dataset_zp_assets (
            asset_id BIGSERIAL PRIMARY KEY,
            dataset_id BIGINT NOT NULL,
            run_id BIGINT NULL,
            zp_path TEXT NOT NULL,
            format_version INTEGER NOT NULL,
            source_fingerprint CHAR(32) NULL,
            output_sha256 CHAR(64) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_dataset_zp_assets_status CHECK (status IN ('active', 'stale', 'deleted'))
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_dataset_zp_assets_dataset_status ON dataset_zp_assets(dataset_id, status)",
    )


def _row_to_job(row: dict[str, Any]) -> ZpConversionJob:
    return ZpConversionJob(
        job_id=str(row["job_id"]),
        status=row["status"],
        stage=row.get("stage"),
        progress=float(row.get("progress") or 0.0),
        dataset_slug=row.get("dataset_slug"),
        input_root=Path(str(row["input_root"])),
        zp_temp_path=_path_or_none(row.get("zp_temp_path")),
        zp_final_path=_path_or_none(row.get("zp_final_path")),
        worker_pid=_int_or_none(row.get("worker_pid")),
        format_version=int(row["format_version"]),
        binary_layer_version=row.get("binary_layer_version"),
        input_bytes=_int_or_none(row.get("input_bytes")),
        output_bytes=_int_or_none(row.get("output_bytes")),
        output_sha256=row.get("output_sha256"),
        validation_mode=row.get("validation_mode"),
        validation_certificate_path=_path_or_none(row.get("validation_certificate_path")),
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
        created_at=_datetime_or_none(row.get("created_at")),
        updated_at=_datetime_or_none(row.get("updated_at")),
        finished_at=_datetime_or_none(row.get("finished_at")),
    )


def _row_to_asset(row: dict[str, Any]) -> ZpArtifact:
    raw_capabilities = row.get("capabilities")
    if isinstance(raw_capabilities, str):
        try:
            capabilities = json.loads(raw_capabilities)
        except json.JSONDecodeError:
            capabilities = {}
    elif isinstance(raw_capabilities, dict):
        capabilities = dict(raw_capabilities)
    else:
        capabilities = {}
    return ZpArtifact(
        asset_id=int(row["asset_id"]),
        dataset_id=int(row["dataset_id"]),
        run_id=_int_or_none(row.get("run_id")),
        zp_path=Path(str(row["zp_path"])),
        format_version=int(row["format_version"]),
        source_fingerprint=row.get("source_fingerprint"),
        output_sha256=str(row["output_sha256"]),
        status=str(row["status"]),
        capabilities=capabilities,
        created_at=_datetime_or_none(row.get("created_at")),
        updated_at=_datetime_or_none(row.get("updated_at")),
    )


def _path_or_none(value: Any) -> Path | None:
    return Path(str(value)) if value else None


def _int_or_none(value: Any) -> int | None:
    return int(value) if value is not None else None


def _datetime_or_none(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
    return None


def _looks_like_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def _validate_uuid(value: str) -> None:
    uuid.UUID(str(value))


def _is_sqlite() -> bool:
    return _db_engine.dialect.name == "sqlite"


def _now_sql() -> str:
    return "CURRENT_TIMESTAMP" if _is_sqlite() else "NOW()"
