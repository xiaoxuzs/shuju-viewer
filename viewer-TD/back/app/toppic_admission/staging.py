"""Resolve staging directory layout for PFMB adaptation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StagingLayout:
    """On-disk layout under ``<data_root>/adapted/<job_id>/``."""

    staging_root: Path
    work_dir: Path
    cache_path: Path
    manifest_path: Path
    engine_dir: Path
    pfmb_path: Path
    egress_dir: Path
    prsms_dir: Path

    @classmethod
    def under_data_root(cls, data_root: Path, job_id: str) -> StagingLayout:
        root = (data_root / "adapted" / job_id).resolve()
        work = root / "work"
        engine = work / "engine_out"
        return cls(
            staging_root=root,
            work_dir=work,
            cache_path=work / "prsm.cache",
            manifest_path=work / "cache_build.manifest.json",
            engine_dir=engine,
            pfmb_path=engine / "results.pfmb",
            egress_dir=work / "egress",
            prsms_dir=root / "data" / "prsms",
        )

    def ensure_dirs(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.engine_dir.mkdir(parents=True, exist_ok=True)
        self.egress_dir.mkdir(parents=True, exist_ok=True)
        self.prsms_dir.mkdir(parents=True, exist_ok=True)
