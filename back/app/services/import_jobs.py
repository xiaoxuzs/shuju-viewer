"""Persistent import-job registry and background ingest runner.

State is stored in the universal ``import_jobs`` table (see
``docs/universal_schema.sql``) so the frontend can keep polling a job id
across uvicorn ``--reload`` cycles. Old completed/failed jobs are GC'd
opportunistically on every read using :data:`JOB_TTL_DAYS`.

Writes go through :func:`app.ingest.universal_toppic_adapter.ingest_universal_toppic`,
i.e. the universal 7-table schema — the same schema that ``app/api/v1/*.py``
reads from.

Each :class:`ImportJob` carries a real progress percentage that the frontend
polls. Progress is split into 4 weighted phases:

* ``extract`` – ZIP unpacking (counted by file entries).
* ``proteins`` – inserting proteins / proteoforms / relations (per cutoff).
* ``matches`` – inserting ``identification_matches`` (per cutoff, the slowest
  phase for ``--mode full`` imports).
* ``finalize`` – marking dataset / run rows ``READY`` and writing description.
"""

from __future__ import annotations

import re
import shutil
import threading
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from sqlalchemy import text

from app.api.v1.universal_compat import cutoff_kinds
from app.core.config import settings
from app.core.db import engine as _db_engine
from app.core.logging import get_logger
from app.ingest.universal_toppic_adapter import (
    ProgressEvent,
    ingest_universal_toppic,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Schema bootstrap & TTL
# ---------------------------------------------------------------------------

JOB_TTL_DAYS = 7

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
        source_zip_name TEXT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT ck_import_jobs_status
            CHECK (status IN ('queued', 'running', 'success', 'failed'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_import_jobs_status_updated_at ON import_jobs(status, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_import_jobs_dataset_slug ON import_jobs(dataset_slug)",
)


def ensure_jobs_table() -> None:
    """Create ``import_jobs`` (and indexes) if they don't exist yet.

    Called once at FastAPI startup. Safe to call repeatedly.
    """
    try:
        with _db_engine.begin() as conn:
            for stmt in _BOOTSTRAP_SQL:
                conn.execute(text(stmt))
    except Exception:  # noqa: BLE001
        log.exception("could not bootstrap import_jobs table; jobs API will fail until DB is reachable")


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
    "queued":   (0.0, 1.0),
    "extract":  (1.0, 18.0),
    "init":     (18.0, 22.0),
    "proteins": (22.0, 30.0),
    "matches":  (30.0, 95.0),
    "finalize": (95.0, 99.5),
}

_PHASE_LABELS: dict[str, str] = {
    "queued":   "排队中…",
    "extract":  "正在解压压缩包，耗时较长…",
    "init":     "正在创建数据集记录…",
    "proteins": "正在导入蛋白与形态…",
    "matches":  "正在导入鉴定结果（PrSM 详情）…",
    "finalize": "正在收尾索引…",
    "success":  "导入完成",
    "failed":   "导入失败",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug_dir_name(slug: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", slug.strip()).strip("._-")
    return safe or "dataset"


def _has_dataset_layout(path: Path) -> bool:
    return path.is_dir() and (
        (path / "toppic_prsm_cutoff").is_dir()
        or (path / "topfd").is_dir()
        or (path / "toppic_proteoform_cutoff").is_dir()
    )


def _find_ingest_root(extract_dir: Path) -> Path:
    if _has_dataset_layout(extract_dir):
        return extract_dir.resolve()
    subdirs = [p for p in extract_dir.iterdir() if p.is_dir()]
    matches = [p for p in subdirs if _has_dataset_layout(p)]
    if len(matches) == 1:
        return matches[0].resolve()
    if len(matches) > 1:
        raise ValueError("ZIP contains multiple dataset folders; keep a single TopPIC output tree at the top level.")
    raise ValueError(
        "Could not find a TopPIC dataset folder (expect topfd/ and/or toppic_*_cutoff/ under the archive root)."
    )


def _validate_zip_paths(zf: zipfile.ZipFile, dest: Path) -> list[zipfile.ZipInfo]:
    """Validate every entry against zip-slip before any disk write."""
    infos = zf.infolist()
    for info in infos:
        rel = PurePosixPath(info.filename)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"unsafe zip entry: {info.filename!r}")
        target = dest.joinpath(*rel.parts).resolve()
        try:
            target.relative_to(dest)
        except ValueError as exc:
            raise ValueError(f"zip slip attempt: {info.filename!r}") from exc
    return infos


def _extract_zip_with_progress(
    zip_path: Path,
    dest: Path,
    *,
    on_progress: Callable[[int, int], None] | None = None,
) -> None:
    """Safely extract ``zip_path`` into ``dest`` and report per-file progress."""
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        infos = _validate_zip_paths(zf, dest)
        n_total = len(infos)
        if on_progress is not None:
            on_progress(0, max(n_total, 1))
        for idx, info in enumerate(infos, start=1):
            zf.extract(info, dest)
            if on_progress is not None and (idx % 25 == 0 or idx == n_total):
                on_progress(idx, max(n_total, 1))


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
    source_zip_name: str | None = None,
) -> ImportJob:
    """Insert a new job row in status ``queued`` and return its snapshot."""
    job_id = str(uuid.uuid4())
    with _db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO import_jobs (
                    job_id, status, stage, stage_label, message, progress,
                    dataset_slug, dataset_name, description, source_zip_name
                )
                VALUES (
                    CAST(:job_id AS uuid), 'queued', 'queued', :stage_label,
                    'Queued', 0, :slug, :name, :description, :source_zip_name
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
                "source_zip_name": source_zip_name,
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
    """``True`` if a queued/running job currently targets this slug."""
    with _db_engine.begin() as conn:
        n = conn.scalar(
            text(
                """
                SELECT count(1) FROM import_jobs
                WHERE dataset_slug = :slug
                  AND status IN ('queued', 'running')
                """
            ),
            {"slug": slug},
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


def run_zip_import_job(
    *,
    job_id: str,
    zip_path: Path,
    slug: str,
    name: str,
    description: str | None,
) -> None:
    data_root = settings.resolved_data_root
    folder_name = _slug_dir_name(slug)
    final_dir = data_root / folder_name
    incoming_dir = data_root / f"{folder_name}.incoming"
    keep_incoming_on_error = False  # set True if the caller-visible error path is one we shouldn't auto-clean

    try:
        # ---- Phase: extract --------------------------------------------------
        # Extract into a sibling ``.incoming`` directory; only swap with the
        # final directory once the database ingest succeeds. This keeps the
        # previous version of the dataset readable until the new one is fully
        # imported (atomic-ish replace).
        _update_job(
            job_id,
            status="running",
            stage="extract",
            stage_label=_PHASE_LABELS["extract"],
            stage_detail="Preparing destination",
            message="Preparing destination",
            progress=_PHASE_RANGES["extract"][0],
        )
        if incoming_dir.exists():
            shutil.rmtree(incoming_dir)
        incoming_dir.mkdir(parents=True, exist_ok=True)

        def _extract_cb(current: int, total: int) -> None:
            pct = _phase_percent("extract", None, current, total)
            _update_job(
                job_id,
                progress=pct,
                stage="extract",
                stage_label=_PHASE_LABELS["extract"],
                stage_detail=f"{current}/{total} files extracted",
                message=f"Extracting {current}/{total} files",
            )

        _extract_zip_with_progress(zip_path, incoming_dir, on_progress=_extract_cb)
        ingest_root = _find_ingest_root(incoming_dir)

        # ---- Phases: init / proteins / matches / finalize -------------------
        _update_job(
            job_id,
            stage="init",
            stage_label=_PHASE_LABELS["init"],
            stage_detail=None,
            message="Importing into database…",
            progress=_PHASE_RANGES["init"][0],
        )
        stats = ingest_universal_toppic(
            root=ingest_root,
            database_url=settings.database_url,
            slug=slug,
            name=name,
            mode="full",
            replace=True,
            progress_callback=_make_adapter_progress_handler(job_id),
        )

        # description is not part of the universal datasets table INSERT
        # template today; if the caller passed one we attach it via a
        # follow-up UPDATE so list views can surface it next to the card.
        if description:
            with _db_engine.begin() as conn:
                conn.execute(
                    text("UPDATE datasets SET description = :description WHERE dataset_id = :dataset_id"),
                    {"description": description, "dataset_id": stats.dataset_id},
                )

        # ---- Atomic dir swap -------------------------------------------------
        # Now that the DB ingest succeeded, replace the previous final dir with
        # the freshly-extracted one. If the swap itself fails (extremely rare
        # on Windows when a previous handle is open), we keep the new ingest
        # in ``incoming`` for inspection rather than rolling back the DB.
        if final_dir.exists():
            shutil.rmtree(final_dir)
        try:
            incoming_dir.rename(final_dir)
        except OSError as exc:
            keep_incoming_on_error = True
            raise RuntimeError(
                f"DB import succeeded but renaming {incoming_dir} → {final_dir} failed: {exc}"
            ) from exc

        log.info(
            "import job %s done dataset_id=%s run_id=%s proteins=%s proteoforms=%s matches=%s",
            job_id,
            stats.dataset_id,
            stats.run_id,
            stats.proteins,
            stats.proteoforms,
            stats.matches,
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
        if not keep_incoming_on_error:
            try:
                if incoming_dir.exists():
                    shutil.rmtree(incoming_dir)
            except OSError:
                log.warning("could not remove partial incoming dir %s", incoming_dir)
    finally:
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass


def start_zip_import_background(
    *,
    job_id: str,
    zip_path: Path,
    slug: str,
    name: str,
    description: str | None,
) -> None:
    thread = threading.Thread(
        target=run_zip_import_job,
        kwargs={
            "job_id": job_id,
            "zip_path": zip_path,
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


def delete_dataset(slug: str) -> DeleteResult:
    """Delete a dataset row (DB) and its on-disk folder (under DATA_ROOT).

    Raises:
        LookupError: slug doesn't exist.
        RuntimeError: an active import job still targets this slug.
        ValueError: dataset's source_root is outside DATA_ROOT (refused to rm
            an unexpected path).
    """
    if has_active_job_for_slug(slug):
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

        # Cascade kills runs / proteins / proteoforms / identification_matches /
        # protein_relation_mapping (FKs use ON DELETE CASCADE).
        conn.execute(
            text("DELETE FROM datasets WHERE dataset_id = :dataset_id"),
            {"dataset_id": dataset_id},
        )

    # ---- Disk side ---------------------------------------------------------
    data_root = settings.resolved_data_root.resolve()
    expected_dir = (data_root / _slug_dir_name(slug)).resolve()

    folder_to_remove: Path | None = None
    if source_root:
        try:
            candidate = Path(source_root).resolve()
            # Only remove if the path is inside DATA_ROOT (defence in depth so
            # an accidentally-inserted absolute path elsewhere on disk can't
            # be deleted by this endpoint).
            candidate.relative_to(data_root)
            folder_to_remove = candidate
        except (OSError, ValueError):
            folder_to_remove = None
    if folder_to_remove is None:
        # Fallback: the conventional slug-derived directory.
        folder_to_remove = expected_dir
        try:
            folder_to_remove.relative_to(data_root)
        except ValueError as exc:
            raise ValueError(
                f"computed dataset folder {folder_to_remove} is outside data_root {data_root}; refusing to remove"
            ) from exc

    folder_existed = folder_to_remove.exists()
    deleted_disk = False
    if folder_existed:
        try:
            shutil.rmtree(folder_to_remove)
            deleted_disk = True
        except OSError:
            log.exception("could not remove dataset folder %s", folder_to_remove)
            deleted_disk = False

    log.info(
        "deleted dataset slug=%s dataset_id=%s folder=%s folder_existed=%s deleted_disk=%s",
        slug,
        dataset_id,
        folder_to_remove,
        folder_existed,
        deleted_disk,
    )
    return DeleteResult(
        deleted_db=True,
        deleted_disk=deleted_disk,
        folder=str(folder_to_remove) if folder_to_remove else None,
        folder_existed=folder_existed,
    )
