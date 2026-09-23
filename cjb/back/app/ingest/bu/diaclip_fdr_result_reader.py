"""DIA-CLIP FDR parquet reader for direct Bottom-Up import."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from app.ingest.bu.bottom_up_identification import BottomUpIdentification, BottomUpSource
from app.ingest.bu.diaclip_result_reader import DIACLIP_SOFTWARE, DiaclipLayoutError
from app.ingest.bu.diann_parquet_reader import DiannReportInfo
from app.ingest.bu.field_mapping import Q_VALUE_CUTOFF, as_float, as_int
from app.ingest.bu.run_discovery import discover_bu_runs, match_diann_runs_to_files


DIACLIP_FDR_SCHEMA_VERSION = "dia_clip_fdr_parquet_v1"
DIACLIP_FDR_IMPORT_MODE = "diaclip_fdr_parquet"
DIACLIP_FDR_METHOD = "reported_by_diaclip_fdr_result_v1"
DIACLIP_FDR_COLUMNS = (
    "Run.Index",
    "Run",
    "Precursor.Id",
    "Modified.Sequence",
    "Stripped.Sequence",
    "Precursor.Charge",
    "Decoy",
    "Proteotypic",
    "Precursor.Mz",
    "Protein.Ids",
    "Protein.Group",
    "Protein.Names",
    "Genes",
    "RT",
    "iRT",
    "Predicted.RT",
    "Predicted.iRT",
    "IM",
    "iIM",
    "Predicted.IM",
    "Predicted.iIM",
    "RT.Start",
    "RT.Stop",
    "FWHM",
    "DIAClip.Score",
    "DIAClip.Q.Value",
    "DIAClip.Feature.Distance",
    "DIAClip.Cosine.Similarity",
    "DIAClip.Quantity",
    "DIAClip.Passed",
)


@dataclass(frozen=True)
class DiaclipFdrBundle:
    root: Path
    result_path: Path
    report_info: DiannReportInfo


@dataclass(frozen=True)
class DiaclipFdrImportStats:
    parquet_total_rows: int
    accepted_targets: int
    decoy_rows: int
    failed_rows: int
    q_value_cutoff: float
    fdr_method: str = DIACLIP_FDR_METHOD


@dataclass(frozen=True)
class PreparedDiaclipFdrSource:
    bundle: DiaclipFdrBundle
    source: BottomUpSource
    stats: DiaclipFdrImportStats


def _schema_names(path: Path) -> tuple[str, ...]:
    try:
        return tuple(pq.ParquetFile(path).schema_arrow.names)
    except Exception as exc:  # noqa: BLE001 - expose stable layout errors
        raise DiaclipLayoutError(f"Could not inspect DIA-CLIP FDR parquet: {path}") from exc


def _is_fdr_schema(path: Path) -> bool:
    return _schema_names(path) == DIACLIP_FDR_COLUMNS


def detect_diaclip_fdr_parquet(root: Path) -> Path | None:
    """Return the single supported DIA-CLIP FDR parquet, if present."""
    base = root.resolve()
    parquet_files = sorted(
        (path.resolve() for path in base.rglob("*.parquet") if path.is_file()),
        key=lambda item: str(item).casefold(),
    )
    name_candidates = [
        path
        for path in parquet_files
        if path.name.casefold().endswith(".diaclip.fdr.parquet")
    ]
    matches: list[Path] = []
    for path in parquet_files:
        try:
            if _is_fdr_schema(path):
                matches.append(path)
        except DiaclipLayoutError:
            if path in name_candidates:
                raise
    if len(matches) > 1:
        preview = ", ".join(path.name for path in matches[:5])
        raise DiaclipLayoutError(
            "Multiple DIA-CLIP FDR parquet files match the supported schema; "
            f"keep exactly one in the selected dataset folder. Found: {preview}."
        )
    if name_candidates and not matches:
        expected = ", ".join(DIACLIP_FDR_COLUMNS)
        raise DiaclipLayoutError(
            "A DIA-CLIP FDR parquet file was found, but its schema is unsupported. "
            f"Supported schema {DIACLIP_FDR_SCHEMA_VERSION} requires exactly: {expected}."
        )
    return matches[0] if matches else None


def has_diaclip_fdr_layout(root: Path) -> bool:
    return detect_diaclip_fdr_parquet(root) is not None


def _inspect_report(path: Path) -> DiannReportInfo:
    parquet = pq.ParquetFile(path)
    run_names: set[str] = set()
    try:
        for batch in parquet.iter_batches(columns=["Run"], batch_size=65_536):
            for value in batch.column("Run").to_pylist():
                text = str(value or "").strip()
                if text:
                    run_names.add(text)
    except Exception as exc:  # noqa: BLE001 - stable layout error
        raise DiaclipLayoutError(f"Could not read DIA-CLIP FDR Run column: {path}") from exc
    return DiannReportInfo(path=path.resolve(), total_rows=parquet.metadata.num_rows, run_names=run_names)


def inspect_diaclip_fdr_bundle(root: Path) -> DiaclipFdrBundle:
    """Validate the direct FDR parquet + mzML DIA-CLIP contract."""
    resolved = root.resolve()
    result_path = detect_diaclip_fdr_parquet(resolved)
    if result_path is None:
        raise DiaclipLayoutError(
            "No supported DIA-CLIP FDR parquet was found. "
            f"Supported schema {DIACLIP_FDR_SCHEMA_VERSION} expects a single parquet with the DIAClip.Q.Value columns."
        )
    report_info = _inspect_report(result_path)
    if len(report_info.run_names) != 1:
        raise DiaclipLayoutError(
            "DIA-CLIP FDR parquet import supports exactly one Run; "
            f"found {len(report_info.run_names)}."
        )
    run_files = discover_bu_runs(resolved)
    mzml_runs = [run_file for run_file in run_files if run_file.raw_format == "mzml"]
    if not mzml_runs:
        raise DiaclipLayoutError("DIA-CLIP FDR parquet import requires one matching mzML file.")
    matched = match_diann_runs_to_files(report_info.run_names, run_files)
    if not any(run_file.raw_format == "mzml" for run_file in matched.values()):
        raise DiaclipLayoutError("DIA-CLIP FDR Run did not map to an mzML file.")
    return DiaclipFdrBundle(root=resolved, result_path=result_path, report_info=report_info)


def _finite_float(row: dict[str, Any], field: str, row_number: int) -> float:
    value = as_float(row.get(field))
    if value is None:
        raise DiaclipLayoutError(f"DIA-CLIP FDR row {row_number}: {field} must be finite.")
    return value


def _integer(row: dict[str, Any], field: str, row_number: int) -> int:
    value = as_int(row.get(field))
    if value is None:
        raise DiaclipLayoutError(f"DIA-CLIP FDR row {row_number}: {field} must be an integer.")
    return value


def _bool_value(row: dict[str, Any], field: str, row_number: int) -> bool:
    raw = row.get(field)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.strip().casefold() in {"true", "false"}:
        return raw.strip().casefold() == "true"
    raise DiaclipLayoutError(f"DIA-CLIP FDR row {row_number}: {field} must be boolean.")


def _required_text(row: dict[str, Any], field: str, row_number: int) -> str:
    text = str(row.get(field) or "").strip()
    if not text:
        raise DiaclipLayoutError(f"DIA-CLIP FDR row {row_number}: {field} is required.")
    return text


def _optional_value(value: Any) -> Any:
    if value == "":
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _iter_rows(path: Path, *, batch_size: int = 8192):
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(columns=list(DIACLIP_FDR_COLUMNS), batch_size=batch_size):
        names = batch.schema.names
        columns = [batch.column(index).to_pylist() for index in range(len(names))]
        for row_index in range(batch.num_rows):
            yield {
                name: columns[column_index][row_index]
                for column_index, name in enumerate(names)
            }


def _validate_row(row: dict[str, Any], *, expected_run: str, row_number: int) -> tuple[bool, bool]:
    run = _required_text(row, "Run", row_number)
    if run != expected_run:
        raise DiaclipLayoutError(
            f"DIA-CLIP FDR row {row_number}: Run {run!r} does not match the single-run contract."
        )
    _required_text(row, "Precursor.Id", row_number)
    _required_text(row, "Modified.Sequence", row_number)
    _required_text(row, "Stripped.Sequence", row_number)
    charge = _integer(row, "Precursor.Charge", row_number)
    if charge <= 0:
        raise DiaclipLayoutError(f"DIA-CLIP FDR row {row_number}: Precursor.Charge must be positive.")
    decoy = _integer(row, "Decoy", row_number)
    if decoy not in {0, 1}:
        raise DiaclipLayoutError(f"DIA-CLIP FDR row {row_number}: Decoy must be 0 or 1.")
    precursor_mz = _finite_float(row, "Precursor.Mz", row_number)
    if precursor_mz <= 0:
        raise DiaclipLayoutError(f"DIA-CLIP FDR row {row_number}: Precursor.Mz must be positive.")
    rt = _finite_float(row, "RT", row_number)
    if rt < 0:
        raise DiaclipLayoutError(f"DIA-CLIP FDR row {row_number}: RT must be non-negative.")
    rt_start = _finite_float(row, "RT.Start", row_number)
    rt_stop = _finite_float(row, "RT.Stop", row_number)
    if rt_start > rt_stop:
        raise DiaclipLayoutError(f"DIA-CLIP FDR row {row_number}: RT.Start must be <= RT.Stop.")
    score = _finite_float(row, "DIAClip.Score", row_number)
    if not 0.0 <= score <= 1.0:
        raise DiaclipLayoutError(f"DIA-CLIP FDR row {row_number}: DIAClip.Score must be between 0 and 1.")
    q_value = _finite_float(row, "DIAClip.Q.Value", row_number)
    if not 0.0 <= q_value <= 1.0:
        raise DiaclipLayoutError(f"DIA-CLIP FDR row {row_number}: DIAClip.Q.Value must be between 0 and 1.")
    quantity = _finite_float(row, "DIAClip.Quantity", row_number)
    if quantity < 0:
        raise DiaclipLayoutError(f"DIA-CLIP FDR row {row_number}: DIAClip.Quantity must be non-negative.")
    passed = _bool_value(row, "DIAClip.Passed", row_number)
    return decoy == 1, passed


def _report_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "Run": row.get("Run"),
        "Precursor.Id": row.get("Precursor.Id"),
        "Modified.Sequence": row.get("Modified.Sequence"),
        "Stripped.Sequence": row.get("Stripped.Sequence"),
        "Precursor.Charge": row.get("Precursor.Charge"),
        "Decoy": row.get("Decoy"),
        "Precursor.Mz": row.get("Precursor.Mz"),
        "Protein.Ids": _optional_value(row.get("Protein.Ids")),
        "Protein.Group": _optional_value(row.get("Protein.Group")),
        "Protein.Names": _optional_value(row.get("Protein.Names")),
        "Genes": _optional_value(row.get("Genes")),
        "RT": row.get("RT"),
        "IM": row.get("IM"),
        "RT.Start": row.get("RT.Start"),
        "RT.Stop": row.get("RT.Stop"),
    }


def prepare_diaclip_fdr_source(
    root: Path,
    *,
    q_value_cutoff: float = Q_VALUE_CUTOFF,
) -> PreparedDiaclipFdrSource:
    """Prepare direct DIA-CLIP FDR parquet identifications for the shared writer."""
    bundle = inspect_diaclip_fdr_bundle(root)
    expected_run = next(iter(bundle.report_info.run_names))
    identifications: list[BottomUpIdentification] = []
    decoy_rows = 0
    failed_rows = 0

    for source_row, row in enumerate(_iter_rows(bundle.result_path), start=1):
        is_decoy, passed = _validate_row(row, expected_run=expected_run, row_number=source_row)
        q_value = _finite_float(row, "DIAClip.Q.Value", source_row)
        if is_decoy:
            decoy_rows += 1
        if not passed:
            failed_rows += 1
        if is_decoy or not passed or q_value >= q_value_cutoff:
            continue
        identifications.append(
            BottomUpIdentification(
                report_row=_report_row(row),
                score=_finite_float(row, "DIAClip.Score", source_row),
                q_value=q_value,
                intensity=_finite_float(row, "DIAClip.Quantity", source_row),
                pep=None,
                search_engine=DIACLIP_SOFTWARE,
                extra_metadata={
                    "diaclip": {
                        "schema_version": DIACLIP_FDR_SCHEMA_VERSION,
                        "source_format": "fdr_parquet",
                        "source_row": source_row,
                        "precursor_id": row.get("Precursor.Id"),
                        "feature_distance": _finite_float(row, "DIAClip.Feature.Distance", source_row),
                        "cos_similarity": _finite_float(row, "DIAClip.Cosine.Similarity", source_row),
                        "quant_result": _finite_float(row, "DIAClip.Quantity", source_row),
                        "passed": passed,
                        "fdr_method": DIACLIP_FDR_METHOD,
                    }
                },
            )
        )

    stats = DiaclipFdrImportStats(
        parquet_total_rows=bundle.report_info.total_rows,
        accepted_targets=len(identifications),
        decoy_rows=decoy_rows,
        failed_rows=failed_rows,
        q_value_cutoff=q_value_cutoff,
    )
    source = BottomUpSource(
        software=DIACLIP_SOFTWARE,
        import_mode=DIACLIP_FDR_IMPORT_MODE,
        dataset_description="DIA-CLIP Bottom-Up DIA dataset imported from FDR parquet and mzML",
        identifications=identifications,
        source_total_rows=bundle.report_info.total_rows,
        skipped_matches=max(bundle.report_info.total_rows - len(identifications), 0),
        extra_metadata={
            "diaclip_schema_version": DIACLIP_FDR_SCHEMA_VERSION,
            "diaclip_fdr": {
                "method": DIACLIP_FDR_METHOD,
                "q_value_column": "DIAClip.Q.Value",
                "q_value_cutoff": q_value_cutoff,
                "comparison": "<",
                "decoy_filter": "Decoy == 0",
                "passed_filter": "DIAClip.Passed == true",
            },
            "diaclip_import_stats": {
                "parquet_total_rows": stats.parquet_total_rows,
                "accepted_targets": stats.accepted_targets,
                "decoy_rows": stats.decoy_rows,
                "failed_rows": stats.failed_rows,
            },
        },
    )
    return PreparedDiaclipFdrSource(bundle=bundle, source=source, stats=stats)
