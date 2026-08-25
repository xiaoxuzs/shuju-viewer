"""数据集与 cutoff 元数据 API：兼容旧前端输出，读取 universal schema。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.universal_compat import cutoff_id, cutoff_label, require_dataset
from app.schemas import BuRunSummary, CutoffOut, DatasetDeletedOut, DatasetOut, DatasetRunSummary
from app.services import import_jobs

router = APIRouter(tags=["datasets"])


def _capabilities_out(raw: Any, *, source_software: str | None) -> dict[str, Any]:
    """Normalize JSONB + infer ``spectra_source`` for legacy prsm*.js-only rows."""
    caps: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    if caps.get("spectra_source") is None and (source_software or "").strip() == "TopPIC_prsm_js":
        caps = {**caps, "spectra_source": "mzml_memory"}
    return caps


def _json_object(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _is_bottom_up(value: Any) -> bool:
    return str(value or "").upper() == "BOTTOM_UP"


def _dataset_mode(row: Any) -> str:
    if _is_bottom_up(row.get("analysis_mode")):
        return "bottom_up"
    caps = _capabilities_out(row.get("capabilities"), source_software=row.get("source_software"))
    if str(caps.get("analysis_shape") or "").lower() in {"mzml_only", "raw_mzml_only", "zp_spectra_only"}:
        return "spectra_only"
    return "top_down"


def _cutoffs_payload(session: Session, dataset_id: int, *, analysis_mode: str | None = None) -> list[CutoffOut]:
    """Synthesize legacy cutoffs from ``identification_matches.source_cutoff``.

    All three counts are filtered by ``extra_metadata.source_cutoff`` so the
    two virtual cutoffs (``prsm`` / ``proteoform``) get distinct numbers, even
    though proteins and proteoforms are stored as cutoff-independent rows in
    the universal schema.
    """
    if _is_bottom_up(analysis_mode):
        return []
    rows = session.execute(
        text(
            """
            WITH cutoff_matches AS (
                SELECT
                    jsonb_extract_path_text(im.extra_metadata, 'source_cutoff') AS cutoff,
                    im.entity_type,
                    im.entity_id
                FROM identification_matches im
                WHERE im.dataset_id = :dataset_id
            )
            SELECT
                cm.cutoff AS cutoff,
                count(*) AS prsm_count,
                count(DISTINCT cm.entity_id) FILTER (WHERE cm.entity_type = 'PROTEOFORM')
                    AS proteoform_count,
                count(DISTINCT prm.protein_id)
                    AS protein_count
            FROM cutoff_matches cm
            LEFT JOIN protein_relation_mapping prm
              ON prm.dataset_id = :dataset_id
             AND prm.entity_type = cm.entity_type
             AND prm.entity_id = cm.entity_id
            WHERE cm.cutoff IS NOT NULL
            GROUP BY cm.cutoff
            """
        ),
        {"dataset_id": dataset_id},
    ).mappings().all()

    by_cutoff = {row["cutoff"]: row for row in rows}
    cutoffs = [
        CutoffOut(
            id=cutoff_id(kind),
            kind=kind,
            label=cutoff_label(kind),
            protein_count=int(by_cutoff.get(kind, {}).get("protein_count") or 0),
            proteoform_count=int(by_cutoff.get(kind, {}).get("proteoform_count") or 0),
            prsm_count=int(by_cutoff.get(kind, {}).get("prsm_count") or 0),
        )
        for kind in ("prsm", "proteoform")
    ]
    return [c for c in cutoffs if c.protein_count > 0 or c.proteoform_count > 0 or c.prsm_count > 0]


def _run_metadata(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _bu_runs_by_dataset(session: Session, dataset_ids: list[int]) -> dict[int, list[BuRunSummary]]:
    """Return BU run summaries grouped by dataset id using a single runs query."""
    if not dataset_ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT dataset_id, run_id, file_name, run_metadata
            FROM runs
            WHERE dataset_id = ANY(:dataset_ids)
            ORDER BY dataset_id, run_id
            """
        ),
        {"dataset_ids": dataset_ids},
    ).mappings().all()
    grouped: dict[int, list[BuRunSummary]] = {}
    for row in rows:
        meta = _run_metadata(row.get("run_metadata"))
        dataset_id = int(row["dataset_id"])
        grouped.setdefault(dataset_id, []).append(
            BuRunSummary(
                run_id=int(row["run_id"]),
                file_name=str(row["file_name"] or ""),
                raw_format=meta.get("raw_format"),
                diann_run_name=meta.get("diann_run_name"),
            )
        )
    return grouped


def _runs_by_dataset(session: Session, dataset_ids: list[int]) -> dict[int, list[DatasetRunSummary]]:
    """Return generic run summaries grouped by dataset id using a single runs query."""
    if not dataset_ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT dataset_id, run_id, file_name, run_metadata
            FROM runs
            WHERE dataset_id = ANY(:dataset_ids)
            ORDER BY dataset_id, run_id
            """
        ),
        {"dataset_ids": dataset_ids},
    ).mappings().all()
    grouped: dict[int, list[DatasetRunSummary]] = {}
    for row in rows:
        meta = _run_metadata(row.get("run_metadata"))
        dataset_id = int(row["dataset_id"])
        grouped.setdefault(dataset_id, []).append(
            DatasetRunSummary(
                run_id=int(row["run_id"]),
                run_name=str(row["file_name"] or ""),
                raw_format=meta.get("raw_format"),
                mzml_file_path=meta.get("mzml_file_path"),
                raw_path=meta.get("raw_path"),
                metadata=meta,
            )
        )
    return grouped


def _dataset_out(
    *,
    row: Any,
    cutoffs: list[CutoffOut],
    bu_runs: list[BuRunSummary] | None,
    runs: list[DatasetRunSummary] | None = None,
) -> DatasetOut:
    return DatasetOut(
        id=row["dataset_id"],
        slug=row["slug"],
        name=row["dataset_name"],
        description=row["description"],
        source_path=row["source_root"],
        capabilities=_capabilities_out(row.get("capabilities"), source_software=row.get("source_software")),
        analysis_mode=row.get("analysis_mode"),
        dataset_mode=_dataset_mode(row),
        status=row.get("status"),
        source_software=row.get("source_software"),
        extra_metadata=_json_object(row.get("extra_metadata")),
        runs=runs,
        bu_runs=bu_runs,
        created_at=row["created_at"],
        updated_at=None,
        cutoffs=cutoffs,
    )


@router.get("/datasets", response_model=list[DatasetOut])
def list_datasets(session: Session = Depends(get_db)) -> list[DatasetOut]:
    """返回全部数据集，按 id 排序；每个元素附带嵌套的 cutoff 统计。"""
    datasets = session.execute(
        text(
            """
            SELECT
                dataset_id, slug, dataset_name, description,
                analysis_mode, status, source_software, source_root,
                created_at, capabilities, extra_metadata
            FROM datasets
            ORDER BY dataset_id
            """
        )
    ).mappings().all()
    bu_dataset_ids = [int(d["dataset_id"]) for d in datasets if _is_bottom_up(d.get("analysis_mode"))]
    bu_runs_by_dataset = _bu_runs_by_dataset(session, bu_dataset_ids)
    spectra_dataset_ids = [int(d["dataset_id"]) for d in datasets if _dataset_mode(d) == "spectra_only"]
    runs_by_dataset = _runs_by_dataset(session, spectra_dataset_ids)
    return [
        _dataset_out(
            row=d,
            cutoffs=_cutoffs_payload(session, d["dataset_id"], analysis_mode=d.get("analysis_mode")),
            bu_runs=bu_runs_by_dataset.get(int(d["dataset_id"])) if _is_bottom_up(d.get("analysis_mode")) else None,
            runs=runs_by_dataset.get(int(d["dataset_id"])) if _dataset_mode(d) == "spectra_only" else None,
        )
        for d in datasets
    ]


@router.get("/datasets/{slug}", response_model=DatasetOut)
def get_dataset_detail(
    slug: str,
    session: Session = Depends(get_db),
) -> DatasetOut:
    """按 slug 取单个数据集；slug 不存在时由依赖注入层返回 404。"""
    dataset = require_dataset(session, slug)
    dataset_id = int(dataset["dataset_id"])
    bu_runs_by_dataset = (
        _bu_runs_by_dataset(session, [dataset_id])
        if _is_bottom_up(dataset.get("analysis_mode"))
        else {}
    )
    runs_by_dataset = (
        _runs_by_dataset(session, [dataset_id])
        if _dataset_mode(dataset) == "spectra_only"
        else {}
    )
    return _dataset_out(
        row=dataset,
        cutoffs=_cutoffs_payload(session, dataset_id, analysis_mode=dataset.get("analysis_mode")),
        bu_runs=bu_runs_by_dataset.get(dataset_id) if _is_bottom_up(dataset.get("analysis_mode")) else None,
        runs=runs_by_dataset.get(dataset_id) if _dataset_mode(dataset) == "spectra_only" else None,
    )


@router.delete("/datasets/{slug}", response_model=DatasetDeletedOut)
def delete_dataset(
    slug: str,
    cancel_import: bool = Query(
        False,
        description=(
            "When true, mark any queued/running import jobs for this slug as cancelled "
            "before deleting the dataset (use when deletion would otherwise return 409)."
        ),
    ),
) -> DatasetDeletedOut:
    """删除一个数据集（仅数据库；磁盘上的导入目录一律保留，由用户自行管理）。

    1. 在 ``datasets`` 表上做 ``DELETE`` —— 由 ``ON DELETE CASCADE`` 顺带清掉
       runs / proteins / proteoforms / identification_matches /
       protein_relation_mapping 中所有关联行。
    2. 清理同 slug 的 ``import_jobs`` 记录，避免 UI 残留幽灵任务。
    3. 若有进行中的导入任务还指向同一个 slug，会拒绝删除（409），除非
       ``cancel_import=true``（先取消任务再删除）。
    """
    try:
        if cancel_import:
            import_jobs.cancel_active_import_jobs_for_slug(slug)
            result = import_jobs.delete_dataset(slug, bypass_active_job_guard=True)
        else:
            result = import_jobs.delete_dataset(slug)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dataset not found: {slug}") from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return DatasetDeletedOut(
        slug=slug,
        deleted_db=result.deleted_db,
        deleted_disk=result.deleted_disk,
        folder=result.folder,
        folder_existed=result.folder_existed,
    )
