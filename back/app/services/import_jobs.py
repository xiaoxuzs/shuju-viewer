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
import os
from pathlib import Path, PurePosixPath
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterable

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


def _collect_zip_entries(
    zf: zipfile.ZipFile,
    dest: Path,
) -> tuple[list[zipfile.ZipInfo], list[Path], list[zipfile.ZipInfo]]:
    """Return (all_infos, dir_paths, file_infos) after safety validation."""
    infos = _validate_zip_paths(zf, dest)
    dir_paths: set[Path] = set()
    file_infos: list[zipfile.ZipInfo] = []

    for info in infos:
        rel = PurePosixPath(info.filename)
        # Some archives don't include explicit dir entries; derive parent dirs from files.
        if info.is_dir():
            dir_paths.add(dest.joinpath(*rel.parts))
        else:
            file_infos.append(info)
            parent_rel = rel.parent
            if parent_rel.parts:
                dir_paths.add(dest.joinpath(*parent_rel.parts))

    return infos, sorted(dir_paths), file_infos


def _default_extract_workers() -> int:
    # Decompression (zlib) + IO benefits from some parallelism; keep it bounded.
    cpu = os.cpu_count() or 4
    return max(4, min(16, cpu * 2))


_ZIP_THREAD_LOCAL = threading.local()


def _get_thread_zip_handle(zip_path: Path) -> zipfile.ZipFile:
    """Return a per-thread ZipFile handle (jieya.py style).

    zipfile.ZipFile isn't guaranteed thread-safe, so every worker thread keeps
    its own instance to avoid internal locks and cross-thread state.
    """
    zf = getattr(_ZIP_THREAD_LOCAL, "zf", None)
    if zf is None:
        _ZIP_THREAD_LOCAL.zf = zipfile.ZipFile(zip_path, "r")
        zf = _ZIP_THREAD_LOCAL.zf
    return zf


def _chunk_iterable(items: list[Any], size: int) -> Iterable[list[Any]]:
    """Split a list into fixed-size chunks."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _extract_chunk(zip_path: Path, infos: list[zipfile.ZipInfo], dest: Path) -> int:
    """Extract a batch of files in a single thread.

    Important: caller must have pre-created all required directories.
    This function intentionally does NOT call mkdir to reduce per-file overhead.
    """
    zf = _get_thread_zip_handle(zip_path)
    count = 0
    for info in infos:
        rel = PurePosixPath(info.filename)
        target_path = dest.joinpath(*rel.parts)
        data = zf.read(info.filename)
        with open(target_path, "wb") as dst:
            dst.write(data)
        count += 1
    return count


def _maybe_unwrap_single_root_folder(dest: Path) -> None:
    """If ZIP extracted into a single wrapper dir, unwrap it in-place.

    Example:
      dest/
        some_outer_folder/
          topfd/
          toppic_prsm_cutoff/

    After unwrapping:
      dest/
        topfd/
        toppic_prsm_cutoff/

    We only unwrap when dest has exactly one directory entry and no files.
    """
    if not dest.exists() or not dest.is_dir():
        return
    entries = list(dest.iterdir())
    if not entries:
        return
    dirs = [p for p in entries if p.is_dir()]
    files = [p for p in entries if p.is_file()]
    if files or len(dirs) != 1:
        return

    wrapper = dirs[0]
    wrapper_entries = list(wrapper.iterdir())
    if not wrapper_entries:
        return

    # Move everything one level up, then remove the wrapper.
    for child in wrapper_entries:
        target = dest / child.name
        if target.exists():
            # Shouldn't happen for well-formed archives; if it does, fail loud.
            raise RuntimeError(f"cannot unwrap: target already exists: {target}")
        shutil.move(str(child), str(target))
    try:
        wrapper.rmdir()
    except OSError:
        # Best effort; if something still holds a handle, keep it.
        pass


def _extract_zip_with_progress(
    zip_path: Path,
    dest: Path,
    *,
    on_progress: Callable[[int, int], None] | None = None,
) -> None:
    """Safely extract ``zip_path`` into ``dest`` and report per-file progress.

    Optimized implementation:
    - validate zip-slip once
    - pre-create directory tree
    - extract file entries concurrently in chunks (jieya.py style: read -> write)
    """
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        infos, dir_paths, file_infos = _collect_zip_entries(zf, dest)

    # Progress semantics are kept consistent with the previous implementation:
    # it counted all entries (files + dirs) from zf.infolist().
    n_total = max(len(infos), 1)
    n_dirs = len(dir_paths)
    n_files = len(file_infos)

    if on_progress is not None:
        on_progress(0, n_total)

    # Pre-create all directories in one go (reduces per-file overhead).
    for d in dir_paths:
        d.mkdir(parents=True, exist_ok=True)

    # Consider directory entries "done" after pre-creation.
    done = n_dirs
    if on_progress is not None and done:
        on_progress(min(done, n_total), n_total)

    if n_files == 0:
        # Nothing else to do; we already created dirs.
        if on_progress is not None:
            on_progress(n_total, n_total)
        return

    workers = _default_extract_workers()

    # Chunking reduces threadpool scheduling overhead and keeps memory spikes
    # more predictable for huge archives.
    chunk_size = 500
    chunks = list(_chunk_iterable(file_infos, chunk_size))
    extracted_files = 0

    # Concurrent chunk extraction. Each future returns the number of files written.
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_extract_chunk, zip_path, chunk, dest) for chunk in chunks]
        for fut in as_completed(futures):
            # Propagate exceptions with useful context (job will be marked failed upstream).
            extracted_files += fut.result()
            done = n_dirs + extracted_files
            if on_progress is not None:
                on_progress(min(done, n_total), n_total)

    if on_progress is not None:
        on_progress(n_total, n_total)


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
        _maybe_unwrap_single_root_folder(incoming_dir)
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
            mode="fast",
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

        # The DB row now has source_root pointing into the (no-longer-existing)
        # ``<slug>.incoming`` path because ingest_universal_toppic was called
        # before the rename. Translate the path so that source_root reflects
        # the post-rename location, otherwise downstream code (spectrum loader,
        # delete_dataset) ends up chasing a stale path.
        try:
            rel_to_incoming = ingest_root.relative_to(incoming_dir.resolve())
        except ValueError:
            rel_to_incoming = Path()
        new_source_root = (final_dir / rel_to_incoming).resolve()
        try:
            with _db_engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE datasets SET source_root = :source_root "
                        "WHERE dataset_id = :dataset_id"
                    ),
                    {"source_root": str(new_source_root), "dataset_id": stats.dataset_id},
                )
        except Exception:  # noqa: BLE001 - non-fatal: delete_dataset has a slug-based fallback
            log.exception("could not refresh datasets.source_root for %s", slug)

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
