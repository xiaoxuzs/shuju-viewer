"""In-memory mzML bundle for one dataset (dedupe paths, map run_id -> scans)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.spectrum_memory.contracts import MzmlBundleSpec
from app.spectrum_memory.mzml_spectrum_extract import approximate_scan_map_bytes, load_mzml_path_to_scan_map


@dataclass
class DatasetMzmlBundle:
    dataset_id: int
    run_to_spectra: dict[int, dict[int, dict]]
    _path_to_spectra: dict[str, dict[int, dict]]
    accounted_bytes: int

    @classmethod
    def load(cls, spec: MzmlBundleSpec) -> DatasetMzmlBundle:
        path_key_to_scans: dict[str, dict[int, dict]] = {}
        run_to_spectra: dict[int, dict[int, dict]] = {}

        for r in spec.runs:
            key = str(r.mzml_path.resolve())
            if key not in path_key_to_scans:
                path_key_to_scans[key] = load_mzml_path_to_scan_map(Path(r.mzml_path))
            run_to_spectra[r.run_id] = path_key_to_scans[key]

        inst = cls(
            dataset_id=spec.dataset_id,
            run_to_spectra=run_to_spectra,
            _path_to_spectra=path_key_to_scans,
            accounted_bytes=0,
        )
        accounted = max(inst._approximate_bytes_internal(), 4096)
        inst.accounted_bytes = accounted
        return inst

    def _approximate_bytes_internal(self) -> int:
        total = 0
        for scans in self._path_to_spectra.values():
            total += approximate_scan_map_bytes(scans)
        total += 64 * 1024
        return max(total, 4096)
