"""DIA-CLIP source layout detection shared by selection and import jobs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.ingest.bu.diaclip_fdr_result_reader import detect_diaclip_fdr_parquet, inspect_diaclip_fdr_bundle
from app.ingest.bu.diaclip_result_reader import DiaclipBundle, inspect_diaclip_bundle
from app.ingest.bu.diann_parquet_reader import DiannReportInfo

DiaclipSourceKind = Literal["legacy_tsv_context", "fdr_parquet"]


@dataclass(frozen=True)
class DiaclipSourceInspection:
    kind: DiaclipSourceKind
    root: Path
    result_path: Path
    report_info: DiannReportInfo
    context_report_path: Path | None = None


def inspect_diaclip_source(root: Path) -> DiaclipSourceInspection:
    """Validate either supported DIA-CLIP import contract."""
    resolved = root.resolve()
    fdr_path = detect_diaclip_fdr_parquet(resolved)
    if fdr_path is not None:
        bundle = inspect_diaclip_fdr_bundle(resolved)
        return DiaclipSourceInspection(
            kind="fdr_parquet",
            root=bundle.root,
            result_path=bundle.result_path,
            report_info=bundle.report_info,
            context_report_path=None,
        )

    legacy: DiaclipBundle = inspect_diaclip_bundle(resolved)
    return DiaclipSourceInspection(
        kind="legacy_tsv_context",
        root=legacy.root,
        result_path=legacy.result_path,
        report_info=legacy.report_info,
        context_report_path=legacy.report_path,
    )
