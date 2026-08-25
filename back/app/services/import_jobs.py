"""Persistent import-job registry and background ingest runner.

State is stored in the universal ``import_jobs`` table (see
``docs/universal_schema.sql``) so the frontend can keep polling a job id
across uvicorn ``--reload`` cycles. Old completed/failed jobs are GC'd
opportunistically on every read using :data:`JOB_TTL_DAYS`.

Imports are **path-based**: the client sends an on-disk folder; the worker
resolves the TopPIC ingest root, computes a fast metadata fingerprint for
duplicate detection, then runs the same universal ingest adapters as before.

Progress phases include ``fingerprint``, ``init``, ``proteins``, ``matches``,
``finalize``, and post-commit ``derived_data`` generation.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.v1.universal_compat import cutoff_kinds
from app.core.config import settings
from app.core.db import engine as _db_engine
from app.core.logging import get_logger
from app.dataset_ingest_root import resolve_ingest_root
from app.fingerprint import compute_dataset_metadata_fingerprint
from app.ingest.universal_toppic_adapter import (
    ProgressEvent,
    assign_toppic_runs_from_prsm_headers,
    ingest_universal_toppic,
)
from app.ingest.bu.diann_parquet_reader import find_diann_report, inspect_report
from app.ingest.bu.run_discovery import discover_bu_runs, match_diann_runs_to_files
from app.ingest.bu.diaclip_source import inspect_diaclip_source
from app.ingest.bu.universal_diaclip_adapter import ingest_universal_diaclip
from app.ingest.bu.universal_diann_adapter import ingest_universal_diann
from app.ingest.td.toppic_native_output import (
    PreparedTopPicNativeOutput,
    prepare_toppic_native_output,
)
from app.import_types import ImportType
from app.ingest.mzml_only_adapter import ingest_mzml_only
from app.ingest.universal_prsm_js_adapter import ingest_universal_prsm_js
from app.pfmb.sidecar_prepare import prepare_bu_pfmb_sidecar
from app.raw_conversion import (
    RawConversionBatch,
    RawConversionError,
    RawFileCandidate,
    convert_raw_files_for_import,
)
from app.services.import_planner import ImportLayoutError, plan_zip_ingest
from app.services.import_planner.types import DatasetShape, ImportPlan
from app.services.import_selection import default_import_kind, validate_import_selection
from app.services.incoming_path_relocate import relocate_incoming_root
from app.services.mzml_mapping import (
    MzmlMappingError,
    build_mapping_from_extracted_dataset,
    build_one_to_one_mapping,
    extract_spectrum_file_names_from_prsms,
    normalize_spectrum_file_name,
)
from app.services.post_import_derived_data import build_post_import_derived_data
from app.spectrum_memory import release_dataset

log = get_logger(__name__)

_PATH_IMPORT_WORKER_TIMING_ORDER: tuple[str, ...] = (
    "resolve_ingest_root_worker_s",
    "fingerprint_job_updates_s",
    "fingerprint_compute_s",
    "duplicate_check_by_fingerprint_s",
    "plan_zip_ingest_s",
    "raw_conversion_s",
    "toppic_native_prepare_s",
    "mzml_mapping_validate_s",
    "bu_mzml_mapping_validate_s",
    "bu_pfmb_prepare_s",
    "job_stage_init_update_s",
    "ingest_universal_toppic_s",
    "ingest_universal_prsm_js_s",
    "ingest_universal_diann_s",
    "ingest_universal_diaclip_s",
    "ingest_mzml_only_s",
    "assign_toppic_runs_from_prsm_headers_s",
    "description_update_s",
    "db_finalize_paths_and_metadata_s",
    "zp_conversion_s",
    "derived_data_backfill_s",
    "job_status_success_update_s",
    "total_path_import_worker_s",
)


def _format_timing_log(timing: dict[str, float], order: tuple[str, ...]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for key in order:
        if key in timing:
            parts.append(f"{key}={timing[key]:.3f}")
            seen.add(key)
    for key in sorted(timing):
        if key not in seen:
            parts.append(f"{key}={timing[key]:.3f}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Schema bootstrap & TTL
# ---------------------------------------------------------------------------

JOB_TTL_DAYS = 7

# ``running`` rows with ``updated_at`` older than this are ignored by
# :func:`has_active_job_for_slug` (crashed worker / reload zombie).
STALE_RUNNING_IMPORT_JOB_MINUTES = 120
# ``queued`` should flip to ``running`` almost immediately; if it sits this long,
# the background thread never attached and the row is safe to ignore for deletes.
STALE_QUEUED_IMPORT_JOB_MINUTES = 15

_BOOTSTRAP_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS import_jobs (
        job_id UUID PRIMARY KEY,
        status VARCHAR(20) NOT NULL,
        stage VARCHAR(40) NULL,
        stage_label TEXT NULL,
        stage_detail TEXT NULL,
        message TEXT NULL,
        error TEXT NULL,
        progress DOUBLE PRECISION NOT NULL DEFAULT 0,
        dataset_slug VARCHAR(160) NULL,
        dataset_name VARCHAR(255) NULL,
        description TEXT NULL,
        source_path TEXT NULL,
        import_type VARCHAR(40) NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT ck_import_jobs_status
            CHECK (status IN ('queued', 'running', 'success', 'failed'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_import_jobs_status_updated_at ON import_jobs(status, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_import_jobs_dataset_slug ON import_jobs(dataset_slug)",
)

_IMPORT_JOBS_ALTER_SQL: tuple[str, ...] = (
    "ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS source_path TEXT NULL",
    "ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS import_type VARCHAR(40) NULL",
    "ALTER TABLE import_jobs DROP COLUMN IF EXISTS source_zip_name",
)

_DATASET_FINGERPRINT_SQL: tuple[str, ...] = (
    "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS source_dataset_fingerprint CHAR(32) NULL",
    "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS source_import_kind VARCHAR(40) NOT NULL DEFAULT 'LEGACY'",
    """
    UPDATE datasets
    SET source_import_kind = CASE
        WHEN source_software ILIKE 'DIA-CLIP%' THEN 'DIA_CLIP'
        WHEN source_software ILIKE 'DIA-NN%' THEN 'DIA_NN'
        WHEN source_software = 'TopPIC_TopFD' THEN 'TOPPIC'
        WHEN source_software = 'TopPIC_prsm_js' THEN 'PRSM'
        WHEN source_software = 'mzML_only' THEN 'MZML_ONLY'
        ELSE source_import_kind
    END
    WHERE source_import_kind = 'LEGACY'
    """,
    "DROP INDEX IF EXISTS uq_datasets_source_dataset_fingerprint",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_datasets_source_fingerprint_import_kind
    ON datasets (source_dataset_fingerprint, source_import_kind)
    WHERE source_dataset_fingerprint IS NOT NULL
    """,
    "DROP INDEX IF EXISTS uq_datasets_source_zip_sha256",
    "ALTER TABLE datasets DROP COLUMN IF EXISTS source_zip_sha256",
)

_RUNS_METADATA_SQL: tuple[str, ...] = (
    """
    ALTER TABLE runs
    ADD COLUMN IF NOT EXISTS run_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
    """,
)


def ensure_jobs_table() -> None:
    """Create ``import_jobs`` (and indexes) if they don't exist yet.

    Called once at FastAPI startup. Safe to call repeatedly.
    """
    try:
        with _db_engine.begin() as conn:
            for stmt in _BOOTSTRAP_SQL:
                conn.execute(text(stmt))
            for stmt in _IMPORT_JOBS_ALTER_SQL:
                conn.execute(text(stmt))
    except Exception:  # noqa: BLE001
        log.exception("could not bootstrap import_jobs table; jobs API will fail until DB is reachable")


def ensure_dataset_fingerprint_schema() -> None:
    """Ensure composite metadata-fingerprint/import-kind duplicate protection."""
    try:
        with _db_engine.begin() as conn:
            for stmt in _DATASET_FINGERPRINT_SQL:
                conn.execute(text(stmt))
    except Exception:  # noqa: BLE001
        log.exception(
            "could not bootstrap dataset fingerprint/import-kind schema; "
            "duplicate checks may fail until DB is fixed"
        )


def ensure_runs_metadata_schema() -> None:
    """Add ``runs.run_metadata`` JSONB column if missing.

    Used for strict run ↔ mzML file mapping (lazy mzML loading by run id).
    """
    try:
        with _db_engine.begin() as conn:
            for stmt in _RUNS_METADATA_SQL:
                conn.execute(text(stmt))
    except Exception:  # noqa: BLE001
        log.exception("could not bootstrap runs.run_metadata; mzML mapping will fail until DB is fixed")


@dataclass
class ExistingDatasetFingerprintMatch:
    slug: str
    dataset_name: str


def find_dataset_with_fingerprint(
    fingerprint_hex: str,
    import_kind: str,
) -> ExistingDatasetFingerprintMatch | None:
    """Return an existing dataset with the same physical fingerprint and import interpretation."""
    row = None
    try:
        with _db_engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT slug, dataset_name
                    FROM datasets
                    WHERE source_dataset_fingerprint = :h
                      AND source_import_kind = :import_kind
                    LIMIT 1
                    """
                ),
                {"h": fingerprint_hex.lower(), "import_kind": import_kind},
            ).mappings().one_or_none()
    except Exception:  # noqa: BLE001
        log.exception("find_dataset_with_fingerprint failed")
        return None
    if row is None:
        return None
    return ExistingDatasetFingerprintMatch(
        slug=str(row["slug"]),
        dataset_name=str(row["dataset_name"]),
    )


def _gc_old_jobs(conn: Any) -> None:
    """Best-effort delete of finished jobs older than :data:`JOB_TTL_DAYS`."""
    try:
        conn.execute(
            text(
                f"""
                DELETE FROM import_jobs
                WHERE status IN ('success', 'failed')
                  AND updated_at < NOW() - INTERVAL '{JOB_TTL_DAYS} days'
                """
            )
        )
    except Exception:  # noqa: BLE001 - GC is opportunistic, never fail reads on it
        pass


# ---------------------------------------------------------------------------
# Progress mapping (per-phase global percentage windows)
# ---------------------------------------------------------------------------

# Cutoffs known to ``app.ingest.universal_toppic_adapter.CUTOFF_DIRS``. Each
# per-cutoff phase is split evenly across this list so an event for "prsm"
# fills the first half and "proteoform" fills the second half. If a cutoff
# is missing on disk the bar simply skips its slice. Order comes from the
# central cutoff registry in ``app.api.v1.universal_compat``.
_CUTOFF_ORDER: dict[str, int] = {kind: idx for idx, kind in enumerate(cutoff_kinds())}

# (start, end) percentage windows. Tuned so that ``matches`` – which is by far
# the longest phase for full imports – occupies ~70% of the bar.
_PHASE_RANGES: dict[str, tuple[float, float]] = {
    "queued":      (0.0, 1.0),
    "fingerprint": (1.0, 8.0),
    "raw_conversion": (8.0, 12.0),
    "init":        (8.0, 12.0),
    "proteins":    (12.0, 20.0),
    "matches":     (20.0, 95.0),
    "finalize":    (95.0, 99.5),
}

_PHASE_LABELS: dict[str, str] = {
    "queued":      "Queued…",
    "fingerprint": "Computing dataset metadata fingerprint…",
    "raw_conversion": "Converting RAW to mzML",
    "init":        "Creating dataset record…",
    "proteins":    "Importing proteins and proteoforms…",
    "matches":     "Importing identifications (PrSM details)…",
    "finalize":    "Finalizing indexes…",
    "success":     "Import complete",
    "failed":      "Import failed",
}

_BU_PHASE_RANGES: dict[str, tuple[float, float]] = {
    "queued":      (0.0, 1.0),
    "fingerprint": (1.0, 8.0),
    "raw_conversion": (8.0, 12.0),
    "init":        (8.0, 12.0),
    "runs":        (12.0, 18.0),
    "proteins":    (18.0, 35.0),
    "peptides":    (35.0, 50.0),
    "matches":     (50.0, 92.0),
    "finalize":    (92.0, 99.5),
}

_BU_PHASE_LABELS: dict[str, str] = {
    "queued":      "Queued",
    "fingerprint": "Computing fingerprint",
    "raw_conversion": "Converting RAW to mzML",
    "init":        "Initializing dataset",
    "runs":        "Registering spectrum files",
    "proteins":    "Importing proteins",
    "peptides":    "Importing peptides",
    "matches":     "Importing identifications",
    "finalize":    "Finalizing",
    "success":     "Import complete",
    "failed":      "Import failed",
}


# ---------------------------------------------------------------------------
# Job dataclass + persistence
# ---------------------------------------------------------------------------


@dataclass
class ImportJob:
    """In-memory snapshot of an ``import_jobs`` row."""

    job_id: str
    status: str  # queued | running | success | failed
    message: str | None = None
    error: str | None = None
    dataset_slug: str | None = None
    progress: float = 0.0  # 0..100
    stage: str | None = None
    stage_label: str | None = None
    stage_detail: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


def _row_to_job(row: dict[str, Any]) -> ImportJob:
    return ImportJob(
        job_id=str(row["job_id"]),
        status=row["status"],
        message=row.get("message"),
        error=row.get("error"),
        dataset_slug=row.get("dataset_slug"),
        progress=float(row.get("progress") or 0.0),
        stage=row.get("stage"),
        stage_label=row.get("stage_label"),
        stage_detail=row.get("stage_detail"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def create_job(
    *,
    slug: str | None = None,
    name: str | None = None,
    description: str | None = None,
    source_path: str | None = None,
    import_type: str | None = None,
) -> ImportJob:
    """Insert a new job row in status ``queued`` and return its snapshot."""
    job_id = str(uuid.uuid4())
    with _db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO import_jobs (
                    job_id, status, stage, stage_label, message, progress,
                    dataset_slug, dataset_name, description, source_path, import_type
                )
                VALUES (
                    CAST(:job_id AS uuid), 'queued', 'queued', :stage_label,
                    'Queued', 0, :slug, :name, :description, :source_path, :import_type
                )
                RETURNING
                    job_id, status, stage, stage_label, stage_detail, message,
                    error, progress, dataset_slug, created_at, updated_at
                """
            ),
            {
                "job_id": job_id,
                "stage_label": _PHASE_LABELS["queued"],
                "slug": slug,
                "name": name,
                "description": description,
                "source_path": source_path,
                "import_type": import_type,
            },
        ).mappings().one()
    return _row_to_job(dict(row))


def get_job(job_id: str) -> ImportJob | None:
    """Return current job state (or ``None`` if unknown).

    Also opportunistically GCs old finished jobs.
    """
    try:
        uuid.UUID(job_id)
    except (ValueError, TypeError):
        return None
    with _db_engine.begin() as conn:
        _gc_old_jobs(conn)
        row = conn.execute(
            text(
                """
                SELECT job_id, status, stage, stage_label, stage_detail, message,
                       error, progress, dataset_slug, created_at, updated_at
                FROM import_jobs
                WHERE job_id = CAST(:job_id AS uuid)
                """
            ),
            {"job_id": job_id},
        ).mappings().one_or_none()
    return _row_to_job(dict(row)) if row is not None else None


def cancel_active_import_jobs_for_slug(slug: str) -> int:
    """Mark all queued/running import jobs for ``slug`` as failed.

    Returns the number of jobs cancelled. Safe to call when none are active.
    """
    cancelled_message = "Import cancelled by user before dataset delete."
    with _db_engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE import_jobs
                SET status = 'failed',
                    stage = 'failed',
                    stage_label = 'Import cancelled',
                    message = 'Import cancelled.',
                    error = :error,
                    updated_at = NOW()
                WHERE dataset_slug = :slug
                  AND status IN ('queued', 'running')
                """
            ),
            {"slug": slug, "error": cancelled_message},
        )
    count = int(result.rowcount or 0)
    if count:
        log.info("cancelled %s active import job(s) for slug=%s", count, slug)
    return count


def has_active_job_for_slug(slug: str) -> bool:
    """``True`` if a non-stale queued/running job currently targets this slug.

    Rows left in ``queued``/``running`` after a crash or process restart are
    treated as inactive once ``updated_at`` is older than the per-status
    thresholds :data:`STALE_QUEUED_IMPORT_JOB_MINUTES` /
    :data:`STALE_RUNNING_IMPORT_JOB_MINUTES`.
    """
    with _db_engine.begin() as conn:
        n = conn.scalar(
            text(
                """
                SELECT count(1) FROM import_jobs
                WHERE dataset_slug = :slug
                  AND (
                    (
                        status = 'queued'
                        AND updated_at >= NOW()
                            - (CAST(:stale_queued_mins AS int) * INTERVAL '1 minute')
                    )
                    OR (
                        status = 'running'
                        AND updated_at >= NOW()
                            - (CAST(:stale_running_mins AS int) * INTERVAL '1 minute')
                    )
                  )
                """
            ),
            {
                "slug": slug,
                "stale_queued_mins": STALE_QUEUED_IMPORT_JOB_MINUTES,
                "stale_running_mins": STALE_RUNNING_IMPORT_JOB_MINUTES,
            },
        ) or 0
    return int(n) > 0


_ALLOWED_UPDATE_COLUMNS = {
    "status",
    "stage",
    "stage_label",
    "stage_detail",
    "message",
    "error",
    "progress",
    "dataset_slug",
}


def _update_job(job_id: str, **kwargs: Any) -> None:
    """Patch a job row; silently ignored if the row was already GC'd."""
    payload = {k: v for k, v in kwargs.items() if k in _ALLOWED_UPDATE_COLUMNS}
    if not payload:
        return
    set_parts = ", ".join(f"{k} = :{k}" for k in payload)
    payload["job_id"] = job_id
    try:
        with _db_engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                    UPDATE import_jobs
                    SET {set_parts}, updated_at = NOW()
                    WHERE job_id = CAST(:job_id AS uuid)
                    """
                ),
                payload,
            )
    except Exception:  # noqa: BLE001 - never fail an ingest on a status write
        log.exception("could not update import_jobs row %s", job_id)


def _phase_percent(phase: str, cutoff: str | None, current: int, total: int) -> float:
    """Translate one phase event into the global progress percentage."""
    start, end = _PHASE_RANGES.get(phase, (0.0, 100.0))
    span = end - start
    if total <= 0:
        local = 0.0
    else:
        local = min(1.0, max(0.0, current / total))

    if cutoff is None or cutoff not in _CUTOFF_ORDER:
        return start + span * local

    n_cutoffs = max(len(_CUTOFF_ORDER), 1)
    per_cutoff = span / n_cutoffs
    cutoff_offset = _CUTOFF_ORDER[cutoff] * per_cutoff
    return start + cutoff_offset + per_cutoff * local


def _make_adapter_progress_handler(job_id: str) -> Callable[[ProgressEvent], None]:
    def handle(event: ProgressEvent) -> None:
        pct = _phase_percent(event.phase, event.cutoff, event.current, event.total)
        # Never let internal phases reach 100%; that's reserved for the
        # ``success`` transition. Clamp to 99.5 (matches _PHASE_RANGES.finalize).
        pct = max(0.0, min(99.5, pct))
        _update_job(
            job_id,
            progress=pct,
            stage=event.phase,
            stage_label=_PHASE_LABELS.get(event.phase, event.phase),
            stage_detail=event.message,
            message=event.message,
        )

    return handle


def _make_bu_adapter_progress_handler(job_id: str) -> Callable[[ProgressEvent], None]:
    def handle(event: ProgressEvent) -> None:
        start, end = _BU_PHASE_RANGES.get(event.phase, (0.0, 100.0))
        if event.total <= 0:
            local = 0.0
        else:
            local = min(1.0, max(0.0, event.current / event.total))
        pct = max(0.0, min(99.5, start + (end - start) * local))
        _update_job(
            job_id,
            progress=pct,
            stage=event.phase,
            stage_label=_BU_PHASE_LABELS.get(event.phase, event.phase),
            stage_detail=event.message,
            message=event.message,
        )

    return handle


def _validate_bu_mzml_mapping(
    ingest_root: Path,
    *,
    extra_mzml_roots: tuple[Path, ...] | None = None,
    run_names: set[str] | None = None,
    source_label: str = "DIA-NN",
) -> None:
    """Validate DIA-NN Run values against discovered mzML files before ingest."""
    if run_names is None:
        report = find_diann_report(ingest_root)
        info = inspect_report(report)
        run_names = info.run_names
    run_files = discover_bu_runs(ingest_root, extra_mzml_roots=extra_mzml_roots)
    if not any(run_file.raw_format == "mzml" for run_file in run_files):
        raise RuntimeError(f"{source_label} dataset requires mzML mapping validation, but no mzML files were found.")
    matched = match_diann_runs_to_files(run_names, run_files)
    if not any(run_file.raw_format == "mzml" for run_file in matched.values()):
        raise RuntimeError(f"{source_label} result did not map any Run value to an mzML file.")


def _run_post_import_derived_data(job_id: str, dataset_id: int) -> str | None:
    """Build derived data without turning a completed DB import into a failure."""
    manual_command = (
        f"python scripts/backfill_dataset_derived_data.py --dataset-id {dataset_id}"
    )
    _update_job(
        job_id,
        stage="derived_data",
        stage_label="Building derived data",
        stage_detail="Generating mzML scan indexes and applicable chromatogram summaries...",
        message="Building derived data...",
        progress=99.6,
    )
    try:
        result = build_post_import_derived_data(dataset_id)
    except Exception as exc:  # noqa: BLE001 - import data is already committed
        log.exception(
            "post-import derived-data build failed dataset_id=%s",
            dataset_id,
        )
        return (
            f"Derived data generation failed: {exc}. "
            f"Retry with: {manual_command}"
        )

    failed_runs = [run for run in result.runs if run.error is not None]
    if failed_runs:
        failed_ids = ", ".join(str(run.run_id) for run in failed_runs)
        log.warning(
            "post-import derived-data build completed with errors "
            "dataset_id=%s run_ids=%s",
            dataset_id,
            failed_ids,
        )
        return (
            f"Derived data generation failed for run(s): {failed_ids}. "
            f"Retry with: {manual_command}"
        )

    log.info(
        "post-import derived-data build completed dataset_id=%s runs=%s",
        dataset_id,
        len(result.runs),
    )
    return None


# ---------------------------------------------------------------------------
# Background job runner
# ---------------------------------------------------------------------------


def _fingerprint_progress_handler(job_id: str) -> Callable[[int], None]:
    """Map monotonically increasing file counts into the fingerprint phase window."""

    def handle(done_files: int) -> None:
        start, end = _PHASE_RANGES["fingerprint"]
        span = end - start
        cap = 50_000
        frac = min(1.0, done_files / cap)
        pct = start + span * frac * 0.92
        _update_job(
            job_id,
            progress=min(end - 0.02, pct),
            stage="fingerprint",
            stage_label=_PHASE_LABELS["fingerprint"],
            stage_detail=f"Scanned {done_files} files…",
            message=f"Metadata fingerprint ({done_files} files)…",
        )

    return handle


def _raw_conversion_output_dir(ingest_root: Path) -> Path:
    configured = settings.raw_conversion_output_dir
    if configured is None:
        return ingest_root / ".viewer-derived" / "raw-converted-mzml"
    if configured.is_absolute():
        return configured
    return ingest_root / configured


def _raw_conversion_progress_handler(job_id: str) -> Callable[[int, int, RawFileCandidate], None]:
    def handle(current: int, total: int, candidate: RawFileCandidate) -> None:
        start, end = _PHASE_RANGES["raw_conversion"]
        if total <= 0:
            local = 0.0
        else:
            local = min(1.0, max(0.0, current / total))
        pct = max(start, min(end - 0.02, start + (end - start) * local))
        _update_job(
            job_id,
            progress=pct,
            stage="raw_conversion",
            stage_label=_PHASE_LABELS["raw_conversion"],
            stage_detail=f"Converting {current}/{total}: {candidate.raw_path.name}",
            message="Converting RAW to mzML",
        )

    return handle


def _raw_conversion_error_detail(exc: RawConversionError) -> str:
    parts = [f"{exc.code}: {exc.message}"]
    result = exc.result
    if result is not None:
        if result.stdout_log_path is not None:
            parts.append(f"stdout log: {result.stdout_log_path}")
        if result.stderr_log_path is not None:
            parts.append(f"stderr log: {result.stderr_log_path}")
    return ". ".join(parts)


def _raw_conversion_metadata_by_mzml_key(batch: RawConversionBatch | None) -> dict[str, dict[str, Any]]:
    if batch is None:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for result in batch.results:
        if result.mzml_path is None:
            continue
        key = normalize_spectrum_file_name(result.mzml_path.name)
        out[key] = {
            "raw_path": str(result.raw_path),
            "raw_conversion": result.metadata(),
        }
    return out


def _dataset_raw_conversion_summary(batch: RawConversionBatch | None) -> dict[str, Any] | None:
    if batch is None:
        return None
    return {"raw_conversion_summary": batch.summary()}


def _run_zp_conversion_for_import(
    *,
    job_id: str,
    ingest_root: Path,
    slug: str,
    plan: ImportPlan,
    raw_conversion_batch: RawConversionBatch | None,
    prepared_toppic_native: PreparedTopPicNativeOutput | None,
) -> None:
    source = _zp_source_for_import(
        ingest_root=ingest_root,
        plan=plan,
        raw_conversion_batch=raw_conversion_batch,
        prepared_toppic_native=prepared_toppic_native,
    )
    _update_job(
        job_id,
        stage="finalize",
        stage_label=_PHASE_LABELS["finalize"],
        stage_detail="Generating ZP artifact",
        message="Generating ZP artifact",
        progress=98.0,
    )
    # Keep ZP conversion lazy so disabled production imports do not load worker-only code.
    from app.zp_conversion import service as zp_conversion_service
    from app.zp_conversion.contracts import ZpConversionError

    try:
        zp_job = zp_conversion_service.enqueue_conversion(
            source_path=source,
            dataset_slug=slug,
            start_background=False,
        )
    except ZpConversionError as exc:
        raise RuntimeError(f"ZP conversion could not be queued: {exc.message}") from exc
    finished = zp_conversion_service.run_conversion_job(zp_job.job_id)
    if finished is None:
        raise RuntimeError("ZP conversion job disappeared before completion.")
    if finished.status != "success":
        message = finished.public_error_message or finished.error_message or finished.error_code or "ZP conversion failed."
        raise RuntimeError(f"ZP conversion failed: {message}")


def _zp_source_for_import(
    *,
    ingest_root: Path,
    plan: ImportPlan,
    raw_conversion_batch: RawConversionBatch | None,
    prepared_toppic_native: PreparedTopPicNativeOutput | None,
) -> Path:
    if plan.shape == DatasetShape.TOPPIC_NATIVE:
        if prepared_toppic_native is None:
            raise RuntimeError("internal error: prepared TopPIC Native Output is missing for ZP conversion")
        return prepared_toppic_native.root
    if plan.shape != DatasetShape.MZML_ONLY:
        return ingest_root

    converted_mzml = tuple(
        result.mzml_path
        for result in (raw_conversion_batch.results if raw_conversion_batch else ())
        if result.mzml_path is not None
    )
    candidates = converted_mzml or plan.mzml_files or plan.raw_files
    if len(candidates) != 1:
        raise RuntimeError(
            f"ZP conversion requires exactly one spectra source for mzML-only imports; found {len(candidates)}."
        )
    return candidates[0]


def run_path_import_job(
    *,
    job_id: str,
    source_path: str,
    slug: str,
    name: str,
    description: str | None,
    import_type: str | None = None,
) -> None:
    """Import from an on-disk folder: resolve ingest root, fingerprint, ingest, finalize."""
    _t0 = time.perf_counter()
    _t = _t0
    timing: dict[str, float] = {}

    def _slice(label: str) -> None:
        nonlocal _t
        now = time.perf_counter()
        elapsed = now - _t
        timing[label] = timing.get(label, 0.0) + elapsed
        _t = now

    try:
        user_root = Path(source_path).expanduser()
        ingest_root = resolve_ingest_root(user_root)

        if settings.import_path_must_be_under_data_root:
            ingest_root.resolve().relative_to(settings.resolved_data_root.resolve())
        _slice("resolve_ingest_root_worker_s")

        _update_job(
            job_id,
            status="running",
            stage="fingerprint",
            stage_label=_PHASE_LABELS["fingerprint"],
            stage_detail="Resolving dataset root path…",
            message="Resolving dataset root path…",
            progress=_PHASE_RANGES["fingerprint"][0],
        )
        _slice("fingerprint_job_updates_s")

        fp = compute_dataset_metadata_fingerprint(
            ingest_root,
            on_progress=_fingerprint_progress_handler(job_id),
        )
        timing["fingerprint_compute_s"] = fp.elapsed_seconds
        _t = time.perf_counter()

        if fp.file_count == 0:
            raise RuntimeError("No countable files found under the selected path; import rejected.")
        _update_job(
            job_id,
            progress=_PHASE_RANGES["fingerprint"][1],
            stage_detail=(
                f"Fingerprint complete: {fp.file_count} files, {fp.elapsed_seconds:.3f}s, digest={fp.fingerprint}"
            ),
        )
        _slice("fingerprint_job_updates_s")

        try:
            plan = plan_zip_ingest(ingest_root)
        except ImportLayoutError as exc:
            raise RuntimeError(str(exc)) from exc
        _slice("plan_zip_ingest_s")

        selected_import_type = ImportType(import_type) if import_type is not None else None
        if selected_import_type is not None:
            validate_import_selection(selected_import_type, ingest_root, plan)
        source_import_kind = (
            selected_import_type.value
            if selected_import_type is not None
            else default_import_kind(plan)
        )
        dup = find_dataset_with_fingerprint(fp.fingerprint, source_import_kind)
        if dup is not None:
            raise RuntimeError(
                f"This dataset's metadata fingerprint and import type {source_import_kind} "
                f"match an existing dataset (slug={dup.slug}, name={dup.dataset_name}). "
                "Delete the existing dataset or choose a different import type or data directory."
            )
        _slice("duplicate_check_by_fingerprint_s")

        raw_conversion_batch: RawConversionBatch | None = None
        raw_conversion_output_dir: Path | None = None
        raw_conversion_by_mzml_key: dict[str, dict[str, Any]] = {}
        if plan.contains_raw:
            raw_conversion_output_dir = _raw_conversion_output_dir(ingest_root)
            _update_job(
                job_id,
                stage="raw_conversion",
                stage_label=_PHASE_LABELS["raw_conversion"],
                stage_detail="Preparing converted mzML files",
                message="Converting RAW to mzML",
                progress=_PHASE_RANGES["raw_conversion"][0],
            )
            try:
                raw_conversion_batch = convert_raw_files_for_import(
                    source_root=ingest_root,
                    output_dir=raw_conversion_output_dir,
                    converter_exe=settings.thermo_raw_file_parser_exe,
                    timeout_seconds=settings.raw_conversion_timeout_seconds,
                    force=settings.raw_conversion_force,
                    progress_callback=_raw_conversion_progress_handler(job_id),
                )
            except RawConversionError as exc:
                raise RuntimeError(_raw_conversion_error_detail(exc)) from exc
            raw_conversion_by_mzml_key = _raw_conversion_metadata_by_mzml_key(raw_conversion_batch)
            _update_job(
                job_id,
                progress=_PHASE_RANGES["raw_conversion"][1],
                stage_detail="Preparing converted mzML files",
                message="Preparing converted mzML files",
            )
            _slice("raw_conversion_s")
        else:
            timing["raw_conversion_s"] = 0.0
            _t = time.perf_counter()

        extra_mzml_roots = (raw_conversion_output_dir,) if raw_conversion_output_dir is not None else None
        prepared_toppic_native: PreparedTopPicNativeOutput | None = None
        if plan.shape == DatasetShape.TOPPIC_NATIVE:
            _update_job(
                job_id,
                stage="init",
                stage_label=_PHASE_LABELS["init"],
                stage_detail="Generating PrSM details from TopPIC Native Output",
                message="Preparing TopPIC Native Output",
                progress=_PHASE_RANGES["init"][0],
            )
            converted_mzml_files = tuple(
                result.mzml_path
                for result in (raw_conversion_batch.results if raw_conversion_batch else ())
                if result.mzml_path is not None
            )
            prepared_toppic_native = prepare_toppic_native_output(
                source_root=ingest_root,
                output_root=(
                    settings.resolved_data_root
                    / ".viewer-derived"
                    / "toppic-native"
                    / fp.fingerprint.lower()
                ),
                additional_mzml_files=converted_mzml_files,
            )
            _slice("toppic_native_prepare_s")
        else:
            timing["toppic_native_prepare_s"] = 0.0
            _t = time.perf_counter()

        mzml_mapping: dict[str, Path] | None = None
        spectra_source = plan.spectra_source
        is_bu_diann = plan.shape == DatasetShape.DIANN_DIA
        is_mzml_only = plan.shape == DatasetShape.MZML_ONLY
        needs_prsm_mzml_mapping = (
            plan.shape
            in {
                DatasetShape.TOPPIC_HTML,
                DatasetShape.PRSM_BUNDLE,
                DatasetShape.TOPPIC_NATIVE,
            }
            and spectra_source == "mzml_memory"
        )
        pfmb_sidecar_dir: Path | None = None
        pfmb_prepare_message: str | None = None
        if is_bu_diann and spectra_source in {"mzml_memory", "mixed"}:
            is_diaclip_import = selected_import_type in {ImportType.BU_DIA_CLIP, ImportType.DIA_CLIP}
            source_label = "DIA-CLIP" if is_diaclip_import else "DIA-NN"
            run_names = (
                inspect_diaclip_source(ingest_root).report_info.run_names
                if is_diaclip_import
                else None
            )
            _update_job(
                job_id,
                stage_detail=f"Validating {source_label} mzML mapping...",
                message=f"Validating {source_label} mzML mapping...",
            )
            try:
                _validate_bu_mzml_mapping(
                    ingest_root,
                    extra_mzml_roots=extra_mzml_roots,
                    run_names=run_names,
                    source_label=source_label,
                )
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"{source_label} mzML mapping validation failed: {exc}") from exc
            _slice("bu_mzml_mapping_validate_s")
            timing["mzml_mapping_validate_s"] = 0.0
            _t = time.perf_counter()
        elif needs_prsm_mzml_mapping:
            _update_job(
                job_id,
                stage_detail="Validating mzML mapping…",
                message="Validating mzML mapping…",
            )
            try:
                if plan.shape == DatasetShape.TOPPIC_NATIVE:
                    if prepared_toppic_native is None:
                        raise RuntimeError(
                            "internal error: prepared TopPIC Native Output is missing"
                        )
                    spectrum_file_names = extract_spectrum_file_names_from_prsms(
                        prepared_toppic_native.root / "data" / "prsms"
                    )
                    mzml_mapping = build_one_to_one_mapping(
                        spectrum_file_names=spectrum_file_names,
                        mzml_files=list(prepared_toppic_native.mzml_files),
                    )
                else:
                    mapping_result = build_mapping_from_extracted_dataset(
                        ingest_root=ingest_root,
                        extra_mzml_roots=extra_mzml_roots,
                    )
                    mzml_mapping = mapping_result.mapping
            except MzmlMappingError as exc:
                raise RuntimeError(f"mzML mapping validation failed: {exc}") from exc
            timing["bu_mzml_mapping_validate_s"] = 0.0
            _slice("mzml_mapping_validate_s")
        else:
            timing["bu_mzml_mapping_validate_s"] = 0.0
            timing["mzml_mapping_validate_s"] = 0.0
            _t = time.perf_counter()

        _update_job(
            job_id,
            stage="init",
            stage_label=_PHASE_LABELS["init"],
            stage_detail=None,
            message="Importing into database…",
            progress=_PHASE_RANGES["init"][0],
        )
        _slice("job_stage_init_update_s")

        if plan.shape == DatasetShape.TOPPIC_HTML:
            timing["ingest_universal_diann_s"] = 0.0
            timing["ingest_universal_prsm_js_s"] = 0.0
            timing["ingest_mzml_only_s"] = 0.0
            stats = ingest_universal_toppic(
                root=ingest_root,
                database_url=settings.database_url,
                slug=slug,
                name=name,
                mode="fast",
                replace=True,
                progress_callback=_make_adapter_progress_handler(job_id),
            )
            _slice("ingest_universal_toppic_s")
            timing["assign_toppic_runs_from_prsm_headers_s"] = 0.0
            if plan.need_toppic_multirun_pass:
                _update_job(
                    job_id,
                    stage_detail="Assigning runs from PrSM headers…",
                    message="Assigning runs from PrSM headers…",
                )
                assign_toppic_runs_from_prsm_headers(
                    database_url=settings.database_url,
                    dataset_id=stats.dataset_id,
                    root=ingest_root,
                    progress_callback=_make_adapter_progress_handler(job_id),
                )
                _slice("assign_toppic_runs_from_prsm_headers_s")
        elif plan.shape in {DatasetShape.PRSM_BUNDLE, DatasetShape.TOPPIC_NATIVE}:
            timing["ingest_universal_toppic_s"] = 0.0
            timing["ingest_universal_diann_s"] = 0.0
            timing["ingest_mzml_only_s"] = 0.0
            native_import = plan.shape == DatasetShape.TOPPIC_NATIVE
            if native_import and prepared_toppic_native is None:
                raise RuntimeError(
                    "internal error: prepared TopPIC Native Output is missing"
                )
            stats = ingest_universal_prsm_js(
                root=(
                    prepared_toppic_native.root
                    if prepared_toppic_native is not None
                    else ingest_root
                ),
                database_url=settings.database_url,
                slug=slug,
                name=name,
                replace=True,
                source_software=(
                    "TopPIC Native Output" if native_import else "TopPIC_prsm_js"
                ),
                description=(
                    "Dataset imported from TopPIC PrSM XML and TopFD MSAlign files"
                    if native_import
                    else "Dataset imported from PrSM detail files (no TopPIC HTML tree)"
                ),
                import_mode="toppic_native" if native_import else "prsm_js",
            )
            _slice("ingest_universal_prsm_js_s")
            timing["assign_toppic_runs_from_prsm_headers_s"] = 0.0
        elif plan.shape == DatasetShape.DIANN_DIA:
            timing["ingest_universal_toppic_s"] = 0.0
            timing["ingest_universal_prsm_js_s"] = 0.0
            timing["ingest_mzml_only_s"] = 0.0
            timing["assign_toppic_runs_from_prsm_headers_s"] = 0.0
            _update_job(
                job_id,
                stage_detail="Preparing Fragment Match sidecar...",
                message="Preparing Fragment Match sidecar...",
            )
            pfmb_prepare = prepare_bu_pfmb_sidecar(ingest_root, slug=slug)
            pfmb_sidecar_dir = pfmb_prepare.sidecar_dir
            pfmb_prepare_message = pfmb_prepare.message
            if pfmb_prepare.status.startswith("skipped"):
                log.warning(
                    "BU PFMB sidecar skipped slug=%s status=%s message=%s",
                    slug,
                    pfmb_prepare.status,
                    pfmb_prepare.message,
                )
            else:
                log.info(
                    "BU PFMB sidecar ready slug=%s status=%s dir=%s",
                    slug,
                    pfmb_prepare.status,
                    pfmb_prepare.sidecar_dir,
                )
            _slice("bu_pfmb_prepare_s")
            bu_ingest = (
                ingest_universal_diaclip
                if selected_import_type
                in {ImportType.BU_DIA_CLIP, ImportType.DIA_CLIP}
                else ingest_universal_diann
            )
            stats = bu_ingest(
                root=ingest_root,
                database_url=settings.database_url,
                slug=slug,
                name=name,
                replace=True,
                spectra_source=spectra_source,
                extra_mzml_roots=extra_mzml_roots,
                raw_conversion_by_mzml_key=raw_conversion_by_mzml_key,
                pfmb_sidecar_dir=pfmb_sidecar_dir,
                progress_callback=_make_bu_adapter_progress_handler(job_id),
            )
            _slice(
                "ingest_universal_diaclip_s"
                if selected_import_type
                in {ImportType.BU_DIA_CLIP, ImportType.DIA_CLIP}
                else "ingest_universal_diann_s"
            )
        elif plan.shape == DatasetShape.MZML_ONLY:
            timing["ingest_universal_toppic_s"] = 0.0
            timing["ingest_universal_prsm_js_s"] = 0.0
            timing["ingest_universal_diann_s"] = 0.0
            timing["assign_toppic_runs_from_prsm_headers_s"] = 0.0
            spectra_profile = {
                ImportType.TD_RAW: (
                    "TOP_DOWN",
                    "Top-Down Thermo RAW",
                    "Top-Down spectra imported from Thermo RAW",
                ),
                ImportType.TD_MZML: (
                    "TOP_DOWN",
                    "Top-Down mzML",
                    "Top-Down spectra imported from mzML",
                ),
                ImportType.DDA_RAW: (
                    "BOTTOM_UP",
                    "DDA Thermo RAW",
                    "DDA spectra imported from Thermo RAW",
                ),
            }.get(
                selected_import_type,
                (
                    "TOP_DOWN",
                    "mzML_only",
                    "Standalone mzML spectra dataset imported for basic spectra viewing",
                ),
            )
            stats = ingest_mzml_only(
                root=ingest_root,
                database_url=settings.database_url,
                slug=slug,
                name=name,
                replace=True,
                extra_mzml_roots=extra_mzml_roots,
                raw_conversion_by_mzml_key=raw_conversion_by_mzml_key,
                analysis_mode=spectra_profile[0],
                source_software=spectra_profile[1],
                description=spectra_profile[2],
            )
            _slice("ingest_mzml_only_s")
        else:
            raise RuntimeError("internal error: unsupported import plan shape")

        if description:
            with _db_engine.begin() as conn:
                conn.execute(
                    text("UPDATE datasets SET description = :description WHERE dataset_id = :dataset_id"),
                    {"description": description, "dataset_id": stats.dataset_id},
                )
        _slice("description_update_s")

        ingest_root_abs = str(ingest_root.resolve())
        incoming_dir_abs = ingest_root_abs
        final_dir_abs = ingest_root_abs
        new_source_root = ingest_root.resolve()
        fp_hash = fp.fingerprint.lower()

        try:
            with _db_engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE datasets SET source_root = :source_root, "
                        "source_dataset_fingerprint = :fp, "
                        "source_import_kind = :source_import_kind "
                        "WHERE dataset_id = :dataset_id"
                    ),
                    {
                        "source_root": str(new_source_root),
                        "fp": fp_hash,
                        "source_import_kind": source_import_kind,
                        "dataset_id": stats.dataset_id,
                    },
                )

                raw_summary_patch = _dataset_raw_conversion_summary(raw_conversion_batch)
                if raw_summary_patch is not None:
                    conn.execute(
                        text(
                            """
                            UPDATE datasets
                            SET extra_metadata = COALESCE(extra_metadata, '{}'::jsonb) || CAST(:extra_patch AS jsonb)
                            WHERE dataset_id = :dataset_id
                            """
                        ),
                        {
                            "dataset_id": stats.dataset_id,
                            "extra_patch": json.dumps(raw_summary_patch, ensure_ascii=False),
                        },
                    )

                if incoming_dir_abs != final_dir_abs:
                    conn.execute(
                        text(
                            """
                            UPDATE identification_matches
                            SET detail_path = REPLACE(detail_path, :oldb, :newb)
                            WHERE dataset_id = :dataset_id
                              AND detail_path LIKE :pfx
                            """
                        ),
                        {
                            "oldb": incoming_dir_abs,
                            "newb": final_dir_abs,
                            "pfx": incoming_dir_abs + "%",
                            "dataset_id": stats.dataset_id,
                        },
                    )

                if not is_bu_diann:
                    conn.execute(
                        text(
                            "UPDATE datasets "
                            "SET capabilities = capabilities || CAST(:cap_patch AS jsonb) "
                            "WHERE dataset_id = :dataset_id"
                        ),
                        {
                            "dataset_id": stats.dataset_id,
                            "cap_patch": (
                                '{"spectra_source": "mzml_memory"}'
                                if spectra_source == "mzml_memory"
                                else '{"spectra_source": "topfd_js"}'
                            ),
                        },
                    )

                if not is_bu_diann and not is_mzml_only and spectra_source == "mzml_memory":
                    if mzml_mapping is None:
                        raise RuntimeError("internal error: mzml_mapping is missing for mzml_memory dataset")

                    conn.execute(
                        text(
                            """
                            DELETE FROM runs r
                            WHERE r.dataset_id = :dataset_id
                              AND NOT EXISTS (
                                  SELECT 1 FROM identification_matches im
                                  WHERE im.dataset_id = r.dataset_id
                                    AND im.run_id = r.run_id
                              )
                            """
                        ),
                        {"dataset_id": stats.dataset_id},
                    )

                    run_rows = conn.execute(
                        text(
                            """
                            SELECT run_id, file_name
                            FROM runs
                            WHERE dataset_id = :dataset_id
                            ORDER BY run_id
                            """
                        ),
                        {"dataset_id": stats.dataset_id},
                    ).mappings().all()

                    missing_runs: list[str] = []
                    for r in run_rows:
                        run_id = int(r["run_id"])
                        file_name = str(r["file_name"] or "")
                        key = normalize_spectrum_file_name(file_name)
                        mzml_path = mzml_mapping.get(key)
                        if mzml_path is None:
                            missing_runs.append(file_name)
                            continue
                        if incoming_dir_abs != final_dir_abs:
                            mzml_stored = relocate_incoming_root(
                                path=Path(mzml_path),
                                incoming_root=Path(incoming_dir_abs),
                                final_root=Path(final_dir_abs),
                            )
                        else:
                            mzml_stored = str(mzml_path)
                        patch = {"raw_format": "mzml", "mzml_file_path": mzml_stored}
                        raw_patch = raw_conversion_by_mzml_key.get(key)
                        if raw_patch is not None:
                            patch.update(raw_patch)
                        conn.execute(
                            text(
                                """
                                UPDATE runs
                                SET run_metadata = run_metadata || CAST(:patch AS jsonb)
                                WHERE run_id = :run_id
                                """
                            ),
                            {
                                "run_id": run_id,
                                "patch": json.dumps(patch, ensure_ascii=False),
                            },
                        )

                    if missing_runs:
                        raise RuntimeError(
                            "mzML mapping did not cover run.file_name: " + ", ".join(missing_runs[:10])
                        )
        except IntegrityError as exc:
            log.warning(
                "duplicate source fingerprint/import kind after ingest slug=%s dataset_id=%s: %s",
                slug,
                stats.dataset_id,
                exc,
            )
            try:
                delete_dataset(slug, bypass_active_job_guard=True)
            except Exception:  # noqa: BLE001
                log.exception("rollback after duplicate fingerprint failed for slug=%s", slug)
            raise RuntimeError(
                "This dataset's fingerprint and import type conflict with an existing record "
                "(concurrent import was rolled back). Please retry later or delete the conflicting dataset."
            ) from exc
        except Exception as exc:  # noqa: BLE001
            log.exception(
                "could not finalize datasets row "
                "(source_root / source_dataset_fingerprint / source_import_kind) for %s",
                slug,
            )
            raise RuntimeError(
                f"Import finished, but failed to persist dataset path / fingerprint: {exc}"
            ) from exc
        _slice("db_finalize_paths_and_metadata_s")

        if settings.zp_management_enabled and settings.zp_import_conversion_enabled:
            _run_zp_conversion_for_import(
                job_id=job_id,
                ingest_root=ingest_root,
                slug=slug,
                plan=plan,
                raw_conversion_batch=raw_conversion_batch,
                prepared_toppic_native=prepared_toppic_native,
            )
            _slice("zp_conversion_s")
        else:
            # Emergency fallback only; normal imports should generate a ZP artifact.
            timing["zp_conversion_s"] = 0.0
            _t = time.perf_counter()

        derived_data_warning = _run_post_import_derived_data(
            job_id,
            stats.dataset_id,
        )
        _slice("derived_data_backfill_s")

        final_detail = (
            f"proteins={stats.proteins}, proteoforms={stats.proteoforms}, "
            f"matches={stats.matches}"
        )
        if derived_data_warning is not None:
            final_detail = f"{final_detail}. Warning: {derived_data_warning}"
        if pfmb_prepare_message is not None:
            final_detail = f"{final_detail}. Fragment Match: {pfmb_prepare_message}"

        _update_job(
            job_id,
            status="success",
            message=(
                "Import finished with derived data warnings."
                if derived_data_warning is not None
                else "Import finished."
            ),
            error=None,
            dataset_slug=slug,
            progress=100.0,
            stage="success",
            stage_label=_PHASE_LABELS["success"],
            stage_detail=final_detail,
        )
        _slice("job_status_success_update_s")

        timing["total_path_import_worker_s"] = time.perf_counter() - _t0
        timing_parts = _format_timing_log(timing, _PATH_IMPORT_WORKER_TIMING_ORDER)
        log.info(
            "import job %s done dataset_id=%s run_id=%s proteins=%s proteoforms=%s matches=%s | timing %s",
            job_id,
            stats.dataset_id,
            stats.run_id,
            stats.proteins,
            stats.proteoforms,
            stats.matches,
            timing_parts,
        )
    except Exception as exc:  # noqa: BLE001
        timing["total_path_import_worker_s"] = time.perf_counter() - _t0
        log.warning(
            "import job %s failed | timing %s",
            job_id,
            _format_timing_log(timing, _PATH_IMPORT_WORKER_TIMING_ORDER),
        )
        log.exception("import job %s failed", job_id)
        _update_job(
            job_id,
            status="failed",
            message="Import failed.",
            error=str(exc),
            stage="failed",
            stage_label=_PHASE_LABELS["failed"],
            stage_detail=str(exc),
        )


def start_path_import_background(
    *,
    job_id: str,
    source_path: str,
    slug: str,
    name: str,
    description: str | None,
    import_type: str | None = None,
) -> None:
    thread = threading.Thread(
        target=run_path_import_job,
        kwargs={
            "job_id": job_id,
            "source_path": source_path,
            "slug": slug,
            "name": name,
            "description": description,
            "import_type": import_type,
        },
        name=f"import-{job_id}",
        daemon=True,
    )
    thread.start()


def enqueue_path_import(
    *,
    source_path: str,
    slug: str,
    name: str,
    description: str | None,
    import_type: str | None = None,
) -> ImportJob:
    """Create the existing ImportJob and start its existing in-process worker."""
    job = create_job(
        slug=slug,
        name=name,
        description=description,
        source_path=source_path,
        import_type=import_type,
    )
    start_path_import_background(
        job_id=job.job_id,
        source_path=source_path,
        slug=slug,
        name=name,
        description=description,
        import_type=import_type,
    )
    return job


# ---------------------------------------------------------------------------
# Dataset deletion (DB only; on-disk import trees are never removed here)
# ---------------------------------------------------------------------------


@dataclass
class DeleteResult:
    deleted_db: bool
    deleted_disk: bool
    folder: str | None
    folder_existed: bool


def delete_dataset(slug: str, *, bypass_active_job_guard: bool = False) -> DeleteResult:
    """Remove the dataset row and cascaded DB rows; do not delete any files on disk.

    Raises:
        LookupError: slug doesn't exist.
        RuntimeError: an active import job still targets this slug (unless
            ``bypass_active_job_guard`` is set for internal rollback only).
    """
    if not bypass_active_job_guard and has_active_job_for_slug(slug):
        raise RuntimeError(
            "Refusing to delete: an import job for this slug is still queued or running."
        )

    with _db_engine.begin() as conn:
        row = conn.execute(
            text("SELECT dataset_id FROM datasets WHERE slug = :slug"),
            {"slug": slug},
        ).mappings().one_or_none()
        if row is None:
            raise LookupError(slug)
        dataset_id = int(row["dataset_id"])
        release_dataset(dataset_id)

        # Drop any import_jobs rows for this slug (finished, failed, or stale
        # queued/running) so deletes do not leave ghosts that confuse the UI.
        conn.execute(
            text("DELETE FROM import_jobs WHERE dataset_slug = :slug"),
            {"slug": slug},
        )

        # Cascade kills runs / proteins / proteoforms / identification_matches /
        # protein_relation_mapping (FKs use ON DELETE CASCADE).
        conn.execute(
            text("DELETE FROM datasets WHERE dataset_id = :dataset_id"),
            {"dataset_id": dataset_id},
        )

    log.info("deleted dataset from DB only slug=%s dataset_id=%s", slug, dataset_id)
    return DeleteResult(
        deleted_db=True,
        deleted_disk=False,
        folder=None,
        folder_existed=False,
    )
