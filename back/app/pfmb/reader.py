"""Random-access reader over the PFMB binary sidecar (``results.pfmb``).

Thin wrapper around the external ``pfm`` module's ``PfmbReader`` (PFMB v3:
binary bundle header + uint64 offset table + PFM2 records). Responsibilities:

* manage the mmap/file-handle lifecycle (context manager + explicit ``close``);
* expose a narrow ``read(prsm_index)`` that returns a decoupled dataclass.

No FastAPI / SQLAlchemy / ingest dependency. The ``pfm`` module ships with the
dia-ms2-pipei delivery (``pfm.py``, pure Python + numpy) and is imported lazily,
so importing ``app.pfmb`` never fails when the binary side is absent. Override
the ``pfm.py`` location with the ``VIEWER_PFM_DIR`` environment variable.

``prsm_index`` equals the record write order (record_index) in this bundle, so
reads are O(1) via the offset table; a header check falls back to the slower
prsm→record map only if that assumption ever breaks.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.config import BACKEND_ROOT

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pfm import PfmbReader as _PfmbReader

# pfm.py is committed alongside the dia-ms2-pipei delivery (data files are not).
_DEFAULT_PFM_DIR = BACKEND_ROOT.parent / "dia-ms2-pipei" / "Hela_DIA_v2_for_frontend"


@dataclass(frozen=True, slots=True)
class MatchedIon:
    """One matched peak↔fragment pair from a PFMB record."""

    ion_type: str  # b / y / c / z_dot
    fragment_ordinal: int
    charge: int
    intensity: float
    observed_neutral_mass: float
    theoretical_neutral_mass: float
    mass_error_ppm: float
    mass_error_da: float
    peak_id: int


@dataclass(frozen=True, slots=True)
class PfmbAnnotation:
    """Decoded annotation for one ``prsm_index`` (one RT slot of a precursor)."""

    prsm_index: int
    scan: int
    peptide: str
    matched_peak_count: int
    matched_ions: list[MatchedIon]


def _ensure_pfm_importable() -> None:
    try:
        import pfm  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    pfm_dir = Path(os.environ.get("VIEWER_PFM_DIR", _DEFAULT_PFM_DIR))
    if (pfm_dir / "pfm.py").exists():
        sys.path.insert(0, str(pfm_dir))


class PfmbAnnotationReader:
    """Owns one open ``PfmbReader`` over a ``results.pfmb`` file."""

    def __init__(self, pfmb_path: Path | str) -> None:
        _ensure_pfm_importable()
        from pfm import PfmbReader

        self.path = Path(pfmb_path)
        self._reader: _PfmbReader = PfmbReader(self.path)

    def __len__(self) -> int:
        return len(self._reader)

    def read(self, prsm_index: int) -> PfmbAnnotation:
        """Return the annotation for *prsm_index* (O(1) when prsm==record order)."""

        record = self._reader.read_record(prsm_index)
        if record.prsm_index != prsm_index:
            # Fallback: bundle not in prsm order — use the (slower) prsm→record map.
            record = self._reader.read_by_prsm_index(prsm_index)
        ions = [_to_matched_ion(m) for m in record.matches]
        return PfmbAnnotation(
            prsm_index=record.prsm_index,
            scan=record.scan,
            peptide=record.peptide,
            matched_peak_count=len({ion.peak_id for ion in ions}),
            matched_ions=ions,
        )

    def close(self) -> None:
        self._reader.close()

    def __enter__(self) -> "PfmbAnnotationReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _to_matched_ion(match: dict) -> MatchedIon:
    return MatchedIon(
        ion_type=str(match["fragment_series"]),
        fragment_ordinal=int(match["fragment_ordinal"]),
        charge=int(match["charge"]),
        intensity=float(match["intensity"]),
        observed_neutral_mass=float(match["observed_neutral_mass"]),
        theoretical_neutral_mass=float(match["theoretical_neutral_mass"]),
        mass_error_ppm=float(match["mass_error_ppm"]),
        mass_error_da=float(match["mass_error_da"]),
        peak_id=int(match["peak_id"]),
    )
