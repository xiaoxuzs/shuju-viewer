"""Small b/y theoretical fragment matcher for Bottom-Up spectra."""

from __future__ import annotations

from dataclasses import dataclass

from pyteomics import mass

from app.schemas import BuMatchedIon


@dataclass(frozen=True)
class _TheoIon:
    ion_type: str
    position: int
    charge: int
    mz: float


def _strip_sequence(sequence: str) -> str:
    return "".join(ch for ch in sequence.upper() if "A" <= ch <= "Z")


def _theoretical_ions(sequence: str) -> list[_TheoIon]:
    stripped = _strip_sequence(sequence)
    ions: list[_TheoIon] = []
    for pos in range(1, len(stripped)):
        prefix = stripped[:pos]
        suffix = stripped[-pos:]
        for charge in (1, 2):
            ions.append(
                _TheoIon(
                    ion_type="b",
                    position=pos,
                    charge=charge,
                    mz=float(mass.fast_mass(prefix, ion_type="b", charge=charge)),
                )
            )
            ions.append(
                _TheoIon(
                    ion_type="y",
                    position=pos,
                    charge=charge,
                    mz=float(mass.fast_mass(suffix, ion_type="y", charge=charge)),
                )
            )
    return ions


def match_by_ions(
    *,
    sequence: str,
    mz: list[float],
    intensity: list[float],
    ppm: float,
) -> list[BuMatchedIon]:
    """Return one best experimental peak per theoretical b/y ion."""
    if not sequence or not mz or not intensity:
        return []

    used_peak_indexes: set[int] = set()
    matches: list[BuMatchedIon] = []
    peak_pairs = list(enumerate(zip(mz, intensity, strict=False)))
    for ion in _theoretical_ions(sequence):
        tolerance = ion.mz * ppm * 1e-6
        candidates: list[tuple[float, float, int, float]] = []
        for idx, (exp_mz, exp_intensity) in peak_pairs:
            if idx in used_peak_indexes:
                continue
            delta = abs(float(exp_mz) - ion.mz)
            if delta <= tolerance:
                candidates.append((float(exp_intensity), delta, idx, float(exp_mz)))
        if not candidates:
            continue
        candidates.sort(key=lambda item: (-item[0], item[1]))
        exp_intensity, _delta, idx, exp_mz = candidates[0]
        used_peak_indexes.add(idx)
        matches.append(
            BuMatchedIon(
                ion_type=ion.ion_type,  # type: ignore[arg-type]
                position=ion.position,
                charge=ion.charge,
                theo_mz=ion.mz,
                exp_mz=exp_mz,
                ppm=(exp_mz - ion.mz) / ion.mz * 1e6,
                intensity=exp_intensity,
            )
        )
    return matches
