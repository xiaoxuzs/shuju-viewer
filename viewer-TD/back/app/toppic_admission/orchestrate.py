"""Orchestrate PFMB adaptation for Form B datasets."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

from .assemble import assemble_all_from_egress
from .pfmb_runner import PfmbRunner
from .staging import StagingLayout
from .toppic_xml_source import load_toppic_prsm_records
from .types import AdmissionDecision, RunTriple
from .validate import validate_adapted_staging


ProgressCallback = Callable[[str, str | None, float | None], None]


@dataclass(frozen=True)
class AdaptResult:
    staging_root: Path
    prsm_json_count: int
    record_count: int


def _default_progress(_stage: str, _detail: str | None, _progress: float | None) -> None:
    return None


def _copy_mzml_to_staging(staging_root: Path, triples: tuple[RunTriple, ...]) -> None:
    seen: set[str] = set()
    for triple in triples:
        name = triple.mzml.name
        if name in seen:
            continue
        seen.add(name)
        dest = staging_root / name
        if dest.exists():
            continue
        shutil.copy2(triple.mzml, dest)


def run_pfmb_adapt(
    decision: AdmissionDecision,
    *,
    job_id: str,
    progress: ProgressCallback | None = None,
    pfmb_exe: Path | None = None,
) -> AdaptResult:
    """Run ingest → run → egress → assemble into a staging root."""
    if not decision.run_triples:
        raise ValueError("PFMB adaptation requires at least one run triple.")

    report = progress or _default_progress
    layout = StagingLayout.under_data_root(settings.resolved_data_root, job_id)
    layout.ensure_dirs()

    report("adapt", "Preparing staging directory…", 0.0)
    _copy_mzml_to_staging(layout.staging_root, decision.run_triples)

    runner = PfmbRunner(
        exe=(pfmb_exe or settings.pfmb_bridge_exe).resolve(),
        cwd=layout.work_dir,
    )

    record_count = 0
    last_xml: Path | None = None
    last_mzml_name = ""
    last_msalign: Path | None = None
    for triple in decision.run_triples:
        report("adapt", f"PFMB ingest ({triple.run_key})…", 10.0)
        record_count = runner.ingest_xml_msalign(
            prsm_xml=triple.prsm_xml,
            ms2_msalign=triple.ms2_msalign,
            cache_path=layout.cache_path,
            manifest_path=layout.manifest_path,
        )
        last_xml = triple.prsm_xml
        last_mzml_name = triple.mzml.name
        last_msalign = triple.ms2_msalign

    report("adapt", "PFMB engine run…", 40.0)
    pfmb_path = runner.run_engine(cache_path=layout.cache_path, output_dir=layout.engine_dir)

    report("adapt", "PFMB egress (JSON)…", 65.0)
    runner.egress_all(cache_path=layout.cache_path, pfmb_path=pfmb_path, out_dir=layout.egress_dir)

    if last_xml is None:
        raise RuntimeError("internal error: missing TopPIC XML path after PFMB ingest")

    report("adapt", "Assembling viewer prsm*.json…", 80.0)
    xml_records = load_toppic_prsm_records(last_xml)
    if len(xml_records) != record_count:
        raise RuntimeError(
            f"TopPIC XML record count ({len(xml_records)}) != PFMB ingest records ({record_count})"
        )

    provenance = {
        "format": "viewer_prsm_json_v1",
        "egress_dir": str(layout.egress_dir),
        "cache_path": str(layout.cache_path),
        "engine_preset": "native_coverage",
        "delivery": "json",
    }
    written = assemble_all_from_egress(
        xml_records=xml_records,
        egress_dir=layout.egress_dir,
        prsms_dir=layout.prsms_dir,
        mzml_file_name=last_mzml_name,
        provenance=provenance,
        ms2_msalign=last_msalign,
    )

    validate_adapted_staging(layout.staging_root)
    if not settings.pfmb_keep_binary_after_adapt and layout.pfmb_path.is_file():
        layout.pfmb_path.unlink()
    report("adapt", f"Adaptation complete ({len(written)} PrSM JSON files).", 100.0)
    return AdaptResult(
        staging_root=layout.staging_root,
        prsm_json_count=len(written),
        record_count=record_count,
    )
