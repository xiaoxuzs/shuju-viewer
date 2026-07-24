"""Streaming reader for DIA-NN 2.0 parquet reports."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from app.ingest.bu.field_mapping import Q_VALUE_CUTOFF, should_import_match


REPORT_COLUMNS = [
    "Run",
    "Precursor.Id",
    "Modified.Sequence",
    "Stripped.Sequence",
    "Precursor.Charge",
    "Decoy",
    "Precursor.Mz",
    "Protein.Ids",
    "Protein.Group",
    "Protein.Names",
    "Genes",
    "RT",
    "IM",
    "Precursor.Quantity",
    "Ms2.Area",
    "Evidence",
    "Mass.Evidence",
    "RT.Start",
    "RT.Stop",
    "PG.MaxLFQ",
    "Q.Value",
    "PEP",
    "Global.Q.Value",
    "Lib.Q.Value",
    "PG.Q.Value",
]


@dataclass(frozen=True)
class DiannReportInfo:
    path: Path
    total_rows: int
    run_names: set[str]


def find_diann_report(root: Path) -> Path:
    """Prefer ``all_report.parquet`` and fall back to ``target_report.parquet``."""
    base = root.resolve()
    for name in ("all_report.parquet", "target_report.parquet"):
        matches = sorted(
            (
                p
                for p in base.rglob("*")
                if p.name.casefold() == name and p.is_file()
            ),
            key=lambda p: str(p).casefold(),
        )
        if matches:
            return matches[0].resolve()
    raise FileNotFoundError(f"no DIA-NN all_report.parquet or target_report.parquet under {base}")


def sibling_file(report_path: Path, suffix: str) -> Path | None:
    candidate = report_path.with_name(report_path.stem + suffix)
    return candidate if candidate.is_file() else None


def inspect_report(path: Path) -> DiannReportInfo:
    parquet = pq.ParquetFile(path)
    run_names: set[str] = set()
    for batch in parquet.iter_batches(columns=["Run"], batch_size=65_536):
        for value in batch.column("Run").to_pylist():
            if value:
                run_names.add(str(value))
    return DiannReportInfo(path=path.resolve(), total_rows=parquet.metadata.num_rows, run_names=run_names)


def iter_filtered_rows(
    path: Path,
    *,
    q_value_cutoff: float = Q_VALUE_CUTOFF,
    batch_size: int = 8192,
) -> Iterator[dict[str, Any]]:
    """Yield rows passing the v1 import filter: non-decoy and Q.Value < 0.01."""
    parquet = pq.ParquetFile(path)
    available = set(parquet.schema_arrow.names)
    columns = [name for name in REPORT_COLUMNS if name in available]
    for batch in parquet.iter_batches(columns=columns, batch_size=batch_size):
        names = batch.schema.names
        values = [batch.column(i).to_pylist() for i in range(len(names))]
        for idx in range(batch.num_rows):
            row = {name: values[col_idx][idx] for col_idx, name in enumerate(names)}
            if should_import_match(row, q_value_cutoff=q_value_cutoff):
                yield row
