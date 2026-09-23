"""DIA-CLIP v1 result validation, FDR control, and DIA-NN context enrichment."""

from __future__ import annotations

import csv
import math
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from app.ingest.bu.bottom_up_identification import BottomUpIdentification, BottomUpSource
from app.ingest.bu.diann_parquet_reader import REPORT_COLUMNS, DiannReportInfo, inspect_report
from app.ingest.bu.field_mapping import Q_VALUE_CUTOFF, as_float, as_int


DIACLIP_SCHEMA_VERSION = "dia_clip_tsv_v1"
DIACLIP_REQUIRED_COLUMNS = (
    "label",
    "score",
    "feature_distance",
    "cos_similarity",
    "modified_peptide",
    "charge",
    "quant_result",
)
DIACLIP_SOFTWARE = "DIA-CLIP"
DIACLIP_IMPORT_MODE = "diaclip_tsv_diann_context"
FDR_METHOD = "target_decoy_tie_aware_v1"

PrecursorKey = tuple[str, int, int]


class DiaclipLayoutError(ValueError):
    """Raised when a user-selected DIA-CLIP bundle does not meet the v1 contract."""


@dataclass(frozen=True)
class DiaclipBundle:
    root: Path
    result_path: Path
    report_path: Path
    report_info: DiannReportInfo


@dataclass(frozen=True)
class DiaclipCandidate:
    key: PrecursorKey
    label: int
    score: float
    feature_distance: float
    cos_similarity: float
    modified_peptide: str
    normalized_modified_peptide: str
    charge: int
    quant_result: float
    source_row: int
    duplicate_count: int = 1


@dataclass(frozen=True)
class DiaclipImportStats:
    tsv_total_rows: int
    unique_candidates: int
    duplicate_rows_removed: int
    target_candidates: int
    decoy_candidates: int
    accepted_targets: int
    q_value_cutoff: float
    fdr_method: str = FDR_METHOD


@dataclass(frozen=True)
class PreparedDiaclipSource:
    bundle: DiaclipBundle
    source: BottomUpSource
    stats: DiaclipImportStats


def normalize_modified_peptide(value: str) -> str:
    """Normalize the DIA-CLIP v1 fixed carbamidomethyl notation to DIA-NN notation."""
    return value.replace("C(Carbamidomethyl)", "C(UniMod:4)")


def _normalized_header(path: Path) -> tuple[str, ...]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            row = next(csv.reader(handle, delimiter="\t"), None)
    except (OSError, UnicodeError) as exc:
        raise DiaclipLayoutError(f"Could not read DIA-CLIP TSV header: {path}") from exc
    if row is None:
        return ()
    return tuple(value.strip() for value in row)


def _is_diaclip_header(header: tuple[str, ...]) -> bool:
    return set(DIACLIP_REQUIRED_COLUMNS).issubset(header)


def find_diaclip_result(root: Path) -> Path:
    """Find exactly one TSV whose header satisfies the supported DIA-CLIP schema."""
    matches: list[Path] = []
    candidates = (
        path
        for path in root.resolve().rglob("*")
        if path.name.casefold().endswith(".tsv")
    )
    for path in sorted(candidates, key=lambda item: str(item).casefold()):
        if path.is_file() and _is_diaclip_header(_normalized_header(path)):
            matches.append(path.resolve())
    if not matches:
        required = ", ".join(DIACLIP_REQUIRED_COLUMNS)
        raise DiaclipLayoutError(
            "No supported DIA-CLIP result TSV was found. "
            f"Supported schema {DIACLIP_SCHEMA_VERSION} requires: {required}."
        )
    if len(matches) > 1:
        preview = ", ".join(path.name for path in matches[:5])
        raise DiaclipLayoutError(
            "Multiple DIA-CLIP result TSV files match the supported header; "
            f"keep exactly one in the selected dataset folder. Found: {preview}."
        )
    return matches[0]


def find_all_report(root: Path) -> Path:
    """Find the single DIA-NN all_report required for DIA-CLIP enrichment."""
    matches = sorted(
        (
            path.resolve()
            for path in root.resolve().rglob("*")
            if path.name.casefold() == "all_report.parquet" and path.is_file()
        ),
        key=lambda item: str(item).casefold(),
    )
    if not matches:
        raise DiaclipLayoutError(
            "DIA-CLIP import requires DIA-NN all_report.parquet; target_report.parquet is not sufficient."
        )
    if len(matches) > 1:
        raise DiaclipLayoutError(
            "Multiple DIA-NN all_report.parquet files were found; "
            "DIA-CLIP v1 requires one unambiguous single-run report."
        )
    return matches[0]


def inspect_diaclip_bundle(root: Path) -> DiaclipBundle:
    """Validate the inexpensive, import-selection-specific DIA-CLIP contract."""
    resolved = root.resolve()
    result_path = find_diaclip_result(resolved)
    report_path = find_all_report(resolved)
    try:
        report_info = inspect_report(report_path)
    except Exception as exc:  # noqa: BLE001 - convert parser details to a stable layout error
        raise DiaclipLayoutError(f"Could not inspect DIA-NN all_report.parquet: {report_path}") from exc
    if len(report_info.run_names) != 1:
        raise DiaclipLayoutError(
            "DIA-CLIP v1 supports exactly one DIA-NN Run because the current TSV schema has no Run column; "
            f"found {len(report_info.run_names)}."
        )
    return DiaclipBundle(
        root=resolved,
        result_path=result_path,
        report_path=report_path,
        report_info=report_info,
    )


def _finite_float(raw: Any, *, field: str, row_number: int) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise DiaclipLayoutError(f"DIA-CLIP row {row_number}: {field} must be numeric.") from exc
    if not math.isfinite(value):
        raise DiaclipLayoutError(f"DIA-CLIP row {row_number}: {field} must be finite.")
    return value


def _integer(raw: Any, *, field: str, row_number: int) -> int:
    value = _finite_float(raw, field=field, row_number=row_number)
    if not value.is_integer():
        raise DiaclipLayoutError(f"DIA-CLIP row {row_number}: {field} must be an integer.")
    return int(value)


def read_diaclip_candidates(path: Path) -> tuple[list[DiaclipCandidate], int]:
    """Read and deterministically collapse duplicate logical precursor candidates."""
    best_by_key: dict[PrecursorKey, DiaclipCandidate] = {}
    duplicate_count_by_key: Counter[PrecursorKey] = Counter()
    total_rows = 0
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise DiaclipLayoutError(f"Could not open DIA-CLIP result TSV: {path}") from exc
    with handle:
        reader = csv.reader(handle, delimiter="\t")
        raw_header = next(reader, None)
        header = tuple(value.strip() for value in raw_header) if raw_header else ()
        if not _is_diaclip_header(header):
            required = ", ".join(DIACLIP_REQUIRED_COLUMNS)
            raise DiaclipLayoutError(
                f"Unsupported DIA-CLIP TSV header in {path.name}; required columns: {required}."
            )
        positions = {name: header.index(name) for name in DIACLIP_REQUIRED_COLUMNS}
        for row_number, values in enumerate(reader, start=2):
            if not values or all(not value.strip() for value in values):
                continue
            if len(values) != len(header):
                raise DiaclipLayoutError(
                    f"DIA-CLIP row {row_number}: expected {len(header)} columns, found {len(values)}."
                )
            total_rows += 1
            label = _integer(values[positions["label"]], field="label", row_number=row_number)
            if label not in {0, 1}:
                raise DiaclipLayoutError(f"DIA-CLIP row {row_number}: label must be 0 or 1.")
            score = _finite_float(values[positions["score"]], field="score", row_number=row_number)
            if not 0.0 <= score <= 1.0:
                raise DiaclipLayoutError(f"DIA-CLIP row {row_number}: score must be between 0 and 1.")
            feature_distance = _finite_float(
                values[positions["feature_distance"]],
                field="feature_distance",
                row_number=row_number,
            )
            cos_similarity = _finite_float(
                values[positions["cos_similarity"]],
                field="cos_similarity",
                row_number=row_number,
            )
            quant_result = _finite_float(
                values[positions["quant_result"]],
                field="quant_result",
                row_number=row_number,
            )
            if quant_result < 0:
                raise DiaclipLayoutError(f"DIA-CLIP row {row_number}: quant_result must be non-negative.")
            modified_peptide = values[positions["modified_peptide"]].strip()
            if not modified_peptide:
                raise DiaclipLayoutError(f"DIA-CLIP row {row_number}: modified_peptide is required.")
            charge = _integer(values[positions["charge"]], field="charge", row_number=row_number)
            if charge <= 0:
                raise DiaclipLayoutError(f"DIA-CLIP row {row_number}: charge must be positive.")
            normalized = normalize_modified_peptide(modified_peptide)
            key = (normalized, charge, 1 - label)
            candidate = DiaclipCandidate(
                key=key,
                label=label,
                score=score,
                feature_distance=feature_distance,
                cos_similarity=cos_similarity,
                modified_peptide=modified_peptide,
                normalized_modified_peptide=normalized,
                charge=charge,
                quant_result=quant_result,
                source_row=row_number,
            )
            previous = best_by_key.get(key)
            duplicate_count_by_key[key] += 1
            if previous is not None and not math.isclose(
                previous.quant_result,
                candidate.quant_result,
                rel_tol=1e-9,
                abs_tol=0.0,
            ):
                raise DiaclipLayoutError(
                    "DIA-CLIP duplicate logical precursor has inconsistent quant_result "
                    f"at rows {previous.source_row} and {row_number}: {normalized}/{charge}."
                )
            if previous is None or candidate.score > previous.score:
                best_by_key[key] = candidate

    candidates = [
        replace(candidate, duplicate_count=duplicate_count_by_key[key])
        for key, candidate in best_by_key.items()
    ]
    return candidates, total_rows


def calculate_q_values(candidates: list[DiaclipCandidate]) -> dict[PrecursorKey, float]:
    """Calculate order-independent, score-tie-aware target/decoy q-values."""
    counts = Counter((candidate.score, candidate.label) for candidate in candidates)
    scores = sorted({candidate.score for candidate in candidates}, reverse=True)
    target_total = 0
    decoy_total = 0
    raw_fdr: list[float] = []
    for score in scores:
        target_total += counts[(score, 1)]
        decoy_total += counts[(score, 0)]
        raw_fdr.append(decoy_total / (target_total + decoy_total))

    q_by_score: dict[float, float] = {}
    running_min = 1.0
    for score, fdr in zip(reversed(scores), reversed(raw_fdr), strict=True):
        running_min = min(running_min, fdr)
        q_by_score[score] = running_min
    return {candidate.key: q_by_score[candidate.score] for candidate in candidates}


def _report_key(row: dict[str, Any]) -> PrecursorKey | None:
    modified = str(row.get("Modified.Sequence") or "").strip()
    charge = as_int(row.get("Precursor.Charge"))
    decoy = as_int(row.get("Decoy"))
    if not modified or charge is None or decoy is None:
        return None
    return modified, charge, decoy


def _accepted_report_rows(
    report_path: Path,
    accepted_keys: set[PrecursorKey],
    *,
    batch_size: int = 8192,
) -> dict[PrecursorKey, dict[str, Any]]:
    parquet = pq.ParquetFile(report_path)
    available = set(parquet.schema_arrow.names)
    required = {"Run", "Modified.Sequence", "Stripped.Sequence", "Precursor.Charge", "Decoy"}
    missing = sorted(required - available)
    if missing:
        raise DiaclipLayoutError(
            "DIA-NN all_report.parquet is missing columns required for DIA-CLIP enrichment: "
            + ", ".join(missing)
        )
    columns = [name for name in REPORT_COLUMNS if name in available]
    matched: dict[PrecursorKey, dict[str, Any]] = {}
    for batch in parquet.iter_batches(columns=columns, batch_size=batch_size):
        names = batch.schema.names
        column_values = [batch.column(index).to_pylist() for index in range(len(names))]
        for row_index in range(batch.num_rows):
            row = {
                name: column_values[column_index][row_index]
                for column_index, name in enumerate(names)
            }
            key = _report_key(row)
            if key not in accepted_keys:
                continue
            if key in matched:
                raise DiaclipLayoutError(
                    "An accepted DIA-CLIP precursor maps to multiple DIA-NN all_report rows: "
                    f"{key[0]}/{key[1]}."
                )
            matched[key] = row
    missing_keys = accepted_keys - matched.keys()
    if missing_keys:
        preview = ", ".join(f"{key[0]}/{key[1]}" for key in sorted(missing_keys)[:5])
        raise DiaclipLayoutError(
            f"{len(missing_keys)} accepted DIA-CLIP precursor(s) were not found in all_report.parquet: {preview}."
        )
    return matched


def prepare_diaclip_source(
    root: Path,
    *,
    q_value_cutoff: float = Q_VALUE_CUTOFF,
) -> PreparedDiaclipSource:
    """Prepare accepted DIA-CLIP identifications with DIA-NN display context."""
    bundle = inspect_diaclip_bundle(root)
    candidates, total_rows = read_diaclip_candidates(bundle.result_path)
    q_by_key = calculate_q_values(candidates)
    accepted = [
        candidate
        for candidate in candidates
        if candidate.label == 1 and q_by_key[candidate.key] < q_value_cutoff
    ]
    report_rows = _accepted_report_rows(
        bundle.report_path,
        {candidate.key for candidate in accepted},
    )
    identifications: list[BottomUpIdentification] = []
    for candidate in accepted:
        report_row = report_rows[candidate.key]
        identifications.append(
            BottomUpIdentification(
                report_row=report_row,
                score=candidate.score,
                q_value=q_by_key[candidate.key],
                intensity=candidate.quant_result,
                pep=None,
                search_engine=DIACLIP_SOFTWARE,
                extra_metadata={
                    "diaclip": {
                        "schema_version": DIACLIP_SCHEMA_VERSION,
                        "feature_distance": candidate.feature_distance,
                        "cos_similarity": candidate.cos_similarity,
                        "quant_result": candidate.quant_result,
                        "source_row": candidate.source_row,
                        "duplicate_count": candidate.duplicate_count,
                        "original_modified_peptide": candidate.modified_peptide,
                        "fdr_method": FDR_METHOD,
                        "diann_q_value": as_float(report_row.get("Q.Value")),
                        "diann_global_q_value": as_float(report_row.get("Global.Q.Value")),
                        "diann_precursor_quantity": as_float(report_row.get("Precursor.Quantity")),
                    }
                },
            )
        )

    target_count = sum(candidate.label == 1 for candidate in candidates)
    decoy_count = sum(candidate.label == 0 for candidate in candidates)
    stats = DiaclipImportStats(
        tsv_total_rows=total_rows,
        unique_candidates=len(candidates),
        duplicate_rows_removed=total_rows - len(candidates),
        target_candidates=target_count,
        decoy_candidates=decoy_count,
        accepted_targets=len(identifications),
        q_value_cutoff=q_value_cutoff,
    )
    source = BottomUpSource(
        software=DIACLIP_SOFTWARE,
        import_mode=DIACLIP_IMPORT_MODE,
        dataset_description="DIA-CLIP Bottom-Up DIA dataset with DIA-NN report context",
        identifications=identifications,
        source_total_rows=total_rows,
        skipped_matches=max(total_rows - len(identifications), 0),
        extra_metadata={
            "context_software": "DIA-NN",
            "diaclip_schema_version": DIACLIP_SCHEMA_VERSION,
            "diaclip_fdr": {
                "method": FDR_METHOD,
                "score_order": "descending",
                "tie_handling": "grouped",
                "formula": "cumulative_decoy/(cumulative_target+cumulative_decoy)",
                "q_value_adjustment": "reverse_cumulative_minimum",
                "q_value_cutoff": q_value_cutoff,
                "comparison": "<",
            },
            "diaclip_import_stats": {
                "tsv_total_rows": stats.tsv_total_rows,
                "unique_candidates": stats.unique_candidates,
                "duplicate_rows_removed": stats.duplicate_rows_removed,
                "target_candidates": stats.target_candidates,
                "decoy_candidates": stats.decoy_candidates,
                "accepted_targets": stats.accepted_targets,
            },
        },
    )
    return PreparedDiaclipSource(bundle=bundle, source=source, stats=stats)
