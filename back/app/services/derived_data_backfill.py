"""Orchestrate explicit generation of dataset derived data."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bu.services.chromatogram_summary import (
    ChromatogramSummaryMissingError,
    ChromatogramSummaryStaleError,
    generate_summary_from_mzml,
    load_summary,
    resolve_run_source_path,
    write_summary,
)
from app.services.mzml_scan_index import (
    ScanIndexMissingError,
    ScanIndexStaleError,
    generate_scan_index_from_mzml,
    load_scan_index,
    write_scan_index,
)
from app.services.mzml_scan_reader import resolve_run_mzml_path

DerivedKind = Literal["scan-index", "chromatogram"]


class DerivedDataBackfillArgumentError(ValueError):
    pass


@dataclass(frozen=True)
class DerivedDataRunResult:
    dataset_id: int
    dataset_slug: str
    run_id: int
    run_name: str
    raw_format: str
    mzml_path: str | None
    scan_index_status: str
    chromatogram_summary_status: str
    elapsed_ms: float
    error: str | None = None


@dataclass(frozen=True)
class DerivedDataBackfillResult:
    dataset_id: int
    dataset_slug: str
    runs: list[DerivedDataRunResult]

    @property
    def has_errors(self) -> bool:
        return any(run.error is not None for run in self.runs)


def resolve_dataset(
    session: Session,
    *,
    dataset_id: int | None,
    slug: str | None,
) -> dict[str, Any]:
    if dataset_id is None and slug is None:
        raise DerivedDataBackfillArgumentError("--dataset-id or --slug is required")

    rows: list[dict[str, Any]] = []
    if dataset_id is not None:
        row = session.execute(
            text(
                """
                SELECT dataset_id, slug, analysis_mode, capabilities
                FROM datasets
                WHERE dataset_id = :dataset_id
                """
            ),
            {"dataset_id": dataset_id},
        ).mappings().one_or_none()
        if row is None:
            raise DerivedDataBackfillArgumentError(f"dataset not found: {dataset_id}")
        rows.append(dict(row))
    if slug is not None:
        row = session.execute(
            text(
                """
                SELECT dataset_id, slug, analysis_mode, capabilities
                FROM datasets
                WHERE slug = :slug
                """
            ),
            {"slug": slug},
        ).mappings().one_or_none()
        if row is None:
            raise DerivedDataBackfillArgumentError(f"dataset not found: {slug}")
        rows.append(dict(row))
    if len(rows) == 2 and int(rows[0]["dataset_id"]) != int(rows[1]["dataset_id"]):
        raise DerivedDataBackfillArgumentError("--dataset-id and --slug refer to different datasets")
    return rows[0]


def select_runs(
    session: Session,
    *,
    dataset_id: int,
    run_id: int | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"dataset_id": dataset_id}
    run_filter = ""
    if run_id is not None:
        run_filter = "AND run_id = :run_id"
        params["run_id"] = run_id
    rows = session.execute(
        text(
            f"""
            SELECT run_id, file_name, file_path, run_metadata
            FROM runs
            WHERE dataset_id = :dataset_id
              {run_filter}
            ORDER BY run_id
            """
        ),
        params,
    ).mappings().all()
    if run_id is not None and not rows:
        raise DerivedDataBackfillArgumentError(
            f"run {run_id} does not belong to dataset {dataset_id}"
        )
    return [dict(row) for row in rows]


def _run_metadata(run: dict[str, Any]) -> dict[str, Any]:
    raw = run.get("run_metadata")
    return dict(raw) if isinstance(raw, dict) else {}


def _is_mzml(run: dict[str, Any]) -> bool:
    metadata = _run_metadata(run)
    raw_format = str(metadata.get("raw_format") or "").lower()
    return raw_format == "mzml" or bool(metadata.get("mzml_file_path"))


def _chromatogram_enabled(dataset: dict[str, Any]) -> bool:
    if str(dataset.get("analysis_mode") or "").upper() == "BOTTOM_UP":
        return True
    capabilities = dataset.get("capabilities")
    caps = dict(capabilities) if isinstance(capabilities, dict) else {}
    shape = str(caps.get("analysis_shape") or "").lower()
    return caps.get("has_chromatogram") is True or shape in {"mzml_only", "raw_mzml_only"}


def _scan_index_state(
    session: Session,
    *,
    dataset_id: int,
    run_id: int,
) -> str:
    try:
        load_scan_index(session, dataset_id, run_id)
    except ScanIndexMissingError:
        return "missing"
    except ScanIndexStaleError:
        return "stale"
    return "ready"


def _chromatogram_state(
    *,
    dataset_id: int,
    run_id: int,
    source_path: Path,
) -> str:
    try:
        load_summary(
            dataset_id=dataset_id,
            run_id=run_id,
            source_path=source_path,
        )
    except ChromatogramSummaryMissingError:
        return "missing"
    except ChromatogramSummaryStaleError:
        return "stale"
    return "ready"


def _generate_scan_index(
    session: Session,
    *,
    dataset_id: int,
    run_id: int,
    source_path: Path,
) -> None:
    index = generate_scan_index_from_mzml(source_path)
    write_scan_index(
        dataset_id=dataset_id,
        run_id=run_id,
        source_path=source_path,
        index=index,
    )


def _generate_chromatogram(
    *,
    dataset_id: int,
    run_id: int,
    source_path: Path,
) -> None:
    summary = generate_summary_from_mzml(source_path)
    write_summary(
        dataset_id=dataset_id,
        run_id=run_id,
        source_path=source_path,
        summary=summary,
    )


def backfill_dataset_derived_data(
    session: Session,
    *,
    dataset_id: int | None = None,
    slug: str | None = None,
    run_id: int | None = None,
    only: DerivedKind | None = None,
    force: bool = False,
    check_only: bool = False,
) -> DerivedDataBackfillResult:
    if only not in (None, "scan-index", "chromatogram"):
        raise DerivedDataBackfillArgumentError(
            "--only must be scan-index or chromatogram"
        )
    dataset = resolve_dataset(session, dataset_id=dataset_id, slug=slug)
    resolved_dataset_id = int(dataset["dataset_id"])
    dataset_slug = str(dataset["slug"])
    can_generate_chromatogram = _chromatogram_enabled(dataset)
    runs = select_runs(session, dataset_id=resolved_dataset_id, run_id=run_id)
    results: list[DerivedDataRunResult] = []

    for run in runs:
        started = time.perf_counter()
        selected_scan = only in (None, "scan-index")
        selected_chromatogram = only in (None, "chromatogram")
        scan_status = "skipped_not_selected" if not selected_scan else "pending"
        chromatogram_status = (
            "skipped_not_selected" if not selected_chromatogram else "pending"
        )
        error: str | None = None
        metadata = _run_metadata(run)
        raw_format = str(metadata.get("raw_format") or "").lower()
        source_path: Path | None = None

        if not _is_mzml(run):
            if selected_scan:
                scan_status = "skipped_not_mzml"
            if selected_chromatogram:
                chromatogram_status = "skipped_not_mzml"
        else:
            try:
                source_path, _path_committed = resolve_run_mzml_path(
                    session,
                    resolved_dataset_id,
                    int(run["run_id"]),
                )
                if selected_scan:
                    current = _scan_index_state(
                        session,
                        dataset_id=resolved_dataset_id,
                        run_id=int(run["run_id"]),
                    )
                    if check_only:
                        scan_status = current
                    elif force or current != "ready":
                        _generate_scan_index(
                            session,
                            dataset_id=resolved_dataset_id,
                            run_id=int(run["run_id"]),
                            source_path=source_path,
                        )
                        scan_status = "generated"
                    else:
                        scan_status = "ready"

                if selected_chromatogram:
                    if not can_generate_chromatogram:
                        chromatogram_status = "skipped_not_bu"
                    else:
                        summary_source_path = resolve_run_source_path(
                            {**run, "run_metadata": {**metadata, "mzml_file_path": str(source_path)}}
                        )
                        current = _chromatogram_state(
                            dataset_id=resolved_dataset_id,
                            run_id=int(run["run_id"]),
                            source_path=summary_source_path,
                        )
                        if check_only:
                            chromatogram_status = current
                        elif force or current != "ready":
                            _generate_chromatogram(
                                dataset_id=resolved_dataset_id,
                                run_id=int(run["run_id"]),
                                source_path=summary_source_path,
                            )
                            chromatogram_status = "generated"
                        else:
                            chromatogram_status = "ready"
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                if scan_status == "pending":
                    scan_status = "error"
                if chromatogram_status == "pending":
                    chromatogram_status = "error"

        results.append(
            DerivedDataRunResult(
                dataset_id=resolved_dataset_id,
                dataset_slug=dataset_slug,
                run_id=int(run["run_id"]),
                run_name=str(run.get("file_name") or ""),
                raw_format=raw_format,
                mzml_path=str(source_path) if source_path is not None else None,
                scan_index_status=scan_status,
                chromatogram_summary_status=chromatogram_status,
                elapsed_ms=round((time.perf_counter() - started) * 1000.0, 3),
                error=error,
            )
        )

    return DerivedDataBackfillResult(
        dataset_id=resolved_dataset_id,
        dataset_slug=dataset_slug,
        runs=results,
    )
