"""Thin DIA-CLIP source adapter over the shared DIA-NN-context Bottom-Up writer."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.ingest.bu.diaclip_result_reader import prepare_diaclip_source
from app.ingest.bu.field_mapping import Q_VALUE_CUTOFF
from app.ingest.bu.universal_diann_adapter import (
    ProgressCallback,
    UniversalDiannImportStats,
    ingest_universal_bottom_up,
)


def _relative_or_abs(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def ingest_universal_diaclip(
    *,
    root: Path,
    database_url: str,
    slug: str,
    name: str,
    replace: bool = False,
    q_value_cutoff: float = Q_VALUE_CUTOFF,
    spectra_source: str | None = None,
    extra_mzml_roots: Sequence[Path] | None = None,
    raw_conversion_by_mzml_key: dict[str, dict[str, Any]] | None = None,
    pfmb_sidecar_dir: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> UniversalDiannImportStats:
    """Import DIA-CLIP identifications using DIA-NN report and spectra context."""
    resolved = root.resolve()
    prepared = prepare_diaclip_source(resolved, q_value_cutoff=q_value_cutoff)
    source = replace(
        prepared.source,
        extra_metadata={
            **prepared.source.extra_metadata,
            "diaclip_result_path": _relative_or_abs(prepared.bundle.result_path, resolved),
        },
    )
    return ingest_universal_bottom_up(
        root=resolved,
        database_url=database_url,
        slug=slug,
        name=name,
        report_path=prepared.bundle.report_path,
        report_info=prepared.bundle.report_info,
        source=source,
        replace=replace,
        q_value_cutoff=q_value_cutoff,
        spectra_source=spectra_source,
        extra_mzml_roots=extra_mzml_roots,
        raw_conversion_by_mzml_key=raw_conversion_by_mzml_key,
        pfmb_sidecar_dir=pfmb_sidecar_dir,
        progress_callback=progress_callback,
    )
