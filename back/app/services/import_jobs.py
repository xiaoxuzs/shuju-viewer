"""Persistent import-job registry and background ingest runner.

State is stored in the universal ``import_jobs`` table (see
``docs/universal_schema.sql``) so the frontend can keep polling a job id
across uvicorn ``--reload`` cycles. Old completed/failed jobs are GC'd
opportunistically on every read using :data:`JOB_TTL_DAYS`.

Imports are **path-based**: the client sends an on-disk folder; the worker
resolves the TopPIC ingest root, computes a fast metadata fingerprint for
duplicate detection, then runs the same universal ingest adapters as before.

Progress phases include ``fingerprint``, ``init``, ``proteins``, ``matches``,
and ``finalize``.
"""

from __future__ import annotations

import json
import re
import shutil
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
from app.ingest.universal_prsm_js_adapter import ingest_universal_prsm_js
from app.services.import_planner import ImportLayoutError, plan_zip_ingest
from app.services.import_planner.types import DatasetShape
from app.services.incoming_path_relocate import relocate_incoming_root
from app.services.mzml_mapping import (
    MzmlMappingError,
    build_mapping_from_extracted_dataset,
    normalize_spectrum_file_name,
)

log = get_logger(__name__)


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
    "ALTER TABLE import_jobs DROP COLUMN IF EXISTS source_zip_name",
)

_DATASET_FINGERPRINT_SQL: tuple[str, ...] = (
    "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS source_dataset_fingerprint CHAR(32) NULL",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_datasets_source_dataset_fingerprint
    ON datasets (source_dataset_fingerprint)
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
    """Add ``datasets.source_dataset_fingerprint`` and drop legacy ZIP digest column."""
    try:
        with _db_engine.begin() as conn:
            for stmt in _DATASET_FINGERPRINT_SQL:
                conn.execute(text(stmt))
    except Exception:  # noqa: BLE001
        log.exception(
            "could not bootstrap datasets.source_dataset_fingerprint; duplicate checks may fail until DB is fixed"
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


def find_dataset_with_fingerprint(fingerprint_hex: str) -> ExistingDatasetFingerprintMatch | None:
    """If a row already has this metadata fingerprint, return it; otherwise ``None``."""
    row = None
    try:
        with _db_engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT slug, dataset_name
                    FROM datasets
                    WHERE source_dataset_fingerprint = :h
                    LIMIT 1
                    """
                ),
                {"h": fingerprint_hex.lower()},
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
    "init":        (8.0, 12.0),
    "proteins":    (12.0, 20.0),
    "matches":     (20.0, 95.0),
    "finalize":    (95.0, 99.5),
}

_PHASE_LABELS: dict[str, str] = {
    "queued":      "排队中…",
    "fingerprint": "正在计算数据集元数据指纹…",
    "init":        "正在创建数据集记录…",
    "proteins":    "正在导入蛋白与形态…",
    "matches":     "正在导入鉴定结果（PrSM 详情）…",
    "finalize":    "正在收尾索引…",
    "success":     "导入完成",
    "failed":      "导入失败",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug_dir_name(slug: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", slug.strip()).strip("._-")
    return safe or "dataset"


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
) -> ImportJob:
    """Insert a new job row in status ``queued`` and return its snapshot."""
    job_id = str(uuid.uuid4())
    with _db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO import_jobs (
                    job_id, status, stage, stage_label, message, progress,
                    dataset_slug, dataset_name, description, source_path
                )
                VALUES (
                    CAST(:job_id AS uuid), 'queued', 'queued', :stage_label,
                    'Queued', 0, :slug, :name, :description, :source_path
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
            stage_detail=f"已扫描 {done_files} 个文件…",
            message=f"元数据指纹（{done_files} 个文件）…",
        )

    return handle


def run_path_import_job(
    *,
    job_id: str,
    source_path: str,
    slug: str,
    name: str,
    description: str | None,
) -> None:
    """Import from an on-disk folder: resolve ingest root, fingerprint, ingest, finalize."""
    _t0 = time.perf_counter()
    _t = _t0
    timing: dict[str, float] = {}

    def _slice(label: str) -> None:
        nonlocal _t
        now = time.perf_counter()
        timing[label] = now - _t
        _t = now

    try:
        user_root = Path(source_path).expanduser()
        ingest_root = resolve_ingest_root(user_root)

        if settings.import_path_must_be_under_data_root:
            ingest_root.resolve().relative_to(settings.resolved_data_root.resolve())

        _update_job(
            job_id,
            status="running",
            stage="fingerprint",
            stage_label=_PHASE_LABELS["fingerprint"],
            stage_detail="解析数据集根路径…",
            message="解析数据集根路径…",
            progress=_PHASE_RANGES["fingerprint"][0],
        )

        fp = compute_dataset_metadata_fingerprint(
            ingest_root,
            on_progress=_fingerprint_progress_handler(job_id),
        )
        if fp.file_count == 0:
            raise RuntimeError("所选路径下没有可统计文件，拒绝导入。")
        _update_job(
            job_id,
            progress=_PHASE_RANGES["fingerprint"][1],
            stage_detail=(
                f"指纹完成：{fp.file_count} 个文件，耗时 {fp.elapsed_seconds:.3f}s，digest={fp.fingerprint}"
            ),
        )
        _slice("fingerprint_s")

        dup = find_dataset_with_fingerprint(fp.fingerprint)
        if dup is not None:
            raise RuntimeError(
                f"该数据集的元数据指纹与已有数据集重复（slug={dup.slug}，名称={dup.dataset_name}）。"
                "请先删除已有数据集或更换数据目录。"
            )

        try:
            plan = plan_zip_ingest(ingest_root)
        except ImportLayoutError as exc:
            raise RuntimeError(str(exc)) from exc
        _slice("plan_s")

        mzml_mapping: dict[str, Path] | None = None
        spectra_source = plan.spectra_source
        if spectra_source == "mzml_memory":
            _update_job(
                job_id,
                stage_detail="Validating mzML mapping…",
                message="Validating mzML mapping…",
            )
            try:
                mapping_result = build_mapping_from_extracted_dataset(ingest_root=ingest_root)
            except MzmlMappingError as exc:
                raise RuntimeError(f"mzML mapping validation failed: {exc}") from exc
            mzml_mapping = mapping_result.mapping
            _slice("mzml_mapping_validate_s")
        else:
            timing["mzml_mapping_validate_s"] = 0.0

        _update_job(
            job_id,
            stage="init",
            stage_label=_PHASE_LABELS["init"],
            stage_detail=None,
            message="Importing into database…",
            progress=_PHASE_RANGES["init"][0],
        )
        if plan.shape == DatasetShape.TOPPIC_HTML:
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
        elif plan.shape == DatasetShape.PRSM_BUNDLE:
            stats = ingest_universal_prsm_js(
                root=ingest_root,
                database_url=settings.database_url,
                slug=slug,
                name=name,
                replace=True,
            )
            _slice("ingest_universal_prsm_js_s")
            timing["assign_toppic_runs_from_prsm_headers_s"] = 0.0
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
                        "source_dataset_fingerprint = :fp "
                        "WHERE dataset_id = :dataset_id"
                    ),
                    {
                        "source_root": str(new_source_root),
                        "fp": fp_hash,
                        "dataset_id": stats.dataset_id,
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

                if spectra_source == "mzml_memory":
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
                                "patch": json.dumps({"mzml_file_path": mzml_stored}, ensure_ascii=False),
                            },
                        )

                    if missing_runs:
                        raise RuntimeError(
                            "mzML mapping did not cover run.file_name: " + ", ".join(missing_runs[:10])
                        )
        except IntegrityError as exc:
            log.warning(
                "duplicate source_dataset_fingerprint after ingest slug=%s dataset_id=%s: %s",
                slug,
                stats.dataset_id,
                exc,
            )
            try:
                delete_dataset(slug, bypass_active_job_guard=True)
            except Exception:  # noqa: BLE001
                log.exception("rollback after duplicate fingerprint failed for slug=%s", slug)
            raise RuntimeError(
                "该数据集指纹与已有记录冲突（并发导入已回滚）。请稍后重试或删除冲突数据集。"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            log.exception(
                "could not finalize datasets row (source_root / source_dataset_fingerprint) for %s",
                slug,
            )
            raise RuntimeError(
                f"Import finished, but failed to persist dataset path / fingerprint: {exc}"
            ) from exc
        _slice("db_finalize_paths_and_metadata_s")

        timing["total_path_import_job_s"] = time.perf_counter() - _t0
        timing_parts = " ".join(f"{k}={v:.3f}" for k, v in sorted(timing.items()))
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
        _update_job(
            job_id,
            status="success",
            message="Import finished.",
            error=None,
            dataset_slug=slug,
            progress=100.0,
            stage="success",
            stage_label=_PHASE_LABELS["success"],
            stage_detail=(
                f"proteins={stats.proteins}, proteoforms={stats.proteoforms}, "
                f"matches={stats.matches}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        timing["total_path_import_job_s"] = time.perf_counter() - _t0
        log.warning(
            "import job %s failed | timing %s",
            job_id,
            " ".join(f"{k}={v:.3f}" for k, v in sorted(timing.items())),
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
) -> None:
    thread = threading.Thread(
        target=run_path_import_job,
        kwargs={
            "job_id": job_id,
            "source_path": source_path,
            "slug": slug,
            "name": name,
            "description": description,
        },
        name=f"import-{job_id}",
        daemon=True,
    )
    thread.start()


# ---------------------------------------------------------------------------
# Dataset deletion (DB + disk)
# ---------------------------------------------------------------------------


@dataclass
class DeleteResult:
    deleted_db: bool
    deleted_disk: bool
    folder: str | None
    folder_existed: bool


def delete_dataset(slug: str, *, bypass_active_job_guard: bool = False) -> DeleteResult:
    """Delete a dataset row (DB) and its on-disk folder (under DATA_ROOT).

    Raises:
        LookupError: slug doesn't exist.
        RuntimeError: an active import job still targets this slug (unless
            ``bypass_active_job_guard`` is set for internal rollback only).
        ValueError: could not derive any dataset folder under DATA_ROOT to remove
            (rare; usually means ``source_root`` points outside ``DATA_ROOT`` and
            no ``<slug>`` folder exists under ``DATA_ROOT``).
    """
    if not bypass_active_job_guard and has_active_job_for_slug(slug):
        raise RuntimeError(
            "Refusing to delete: an import job for this slug is still queued or running."
        )

    with _db_engine.begin() as conn:
        row = conn.execute(
            text("SELECT dataset_id, source_root FROM datasets WHERE slug = :slug"),
            {"slug": slug},
        ).mappings().one_or_none()
        if row is None:
            raise LookupError(slug)
        dataset_id = int(row["dataset_id"])
        source_root = row.get("source_root") or ""

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

    # ---- Disk side ---------------------------------------------------------
    data_root = settings.resolved_data_root.resolve()
    expected_dir = (data_root / _slug_dir_name(slug)).resolve()
    incoming_dir = (data_root / f"{_slug_dir_name(slug)}.incoming").resolve()

    # Walk a path up to its top-level directory directly under ``data_root``;
    # this lets us delete the whole dataset folder even if ``source_root``
    # happens to point at a nested subdir (e.g. an ingest_root that was a
    # subfolder of the wrapper).
    def _top_under_data_root(p: Path) -> Path | None:
        try:
            p.relative_to(data_root)
        except ValueError:
            return None
        cur = p
        while cur.parent != data_root and cur.parent != cur:
            cur = cur.parent
        return cur if cur.parent == data_root else None

    # Build an ordered, de-duplicated list of folders to try removing.
    candidates: list[Path] = []
    seen: set[Path] = set()

    def _add_candidate(p: Path | None) -> None:
        if p is None:
            return
        if p in seen:
            return
        seen.add(p)
        candidates.append(p)

    if source_root:
        try:
            _add_candidate(_top_under_data_root(Path(source_root).resolve()))
        except OSError:
            pass
    _add_candidate(_top_under_data_root(expected_dir))
    # Also clean up any leftover ``<slug>.incoming`` from a crashed import.
    _add_candidate(_top_under_data_root(incoming_dir))

    if not candidates:
        raise ValueError(
            f"could not derive any dataset folder under data_root {data_root} for slug {slug!r}"
        )

    primary = candidates[0]
    folder_existed = False
    deleted_disk = False
    for cand in candidates:
        if not cand.exists():
            continue
        folder_existed = True
        try:
            shutil.rmtree(cand)
            # Mark success the first time anything was actually removed.
            if cand == primary or not deleted_disk:
                deleted_disk = True
        except OSError:
            log.exception("could not remove dataset folder %s", cand)

    log.info(
        "deleted dataset slug=%s dataset_id=%s primary=%s candidates=%s "
        "folder_existed=%s deleted_disk=%s",
        slug,
        dataset_id,
        primary,
        [str(c) for c in candidates],
        folder_existed,
        deleted_disk,
    )
    return DeleteResult(
        deleted_db=True,
        deleted_disk=deleted_disk,
        folder=str(primary),
        folder_existed=folder_existed,
    )
