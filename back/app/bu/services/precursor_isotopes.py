"""Precursor isotope target m/z helpers for Bottom-Up XIC."""

from __future__ import annotations

from dataclasses import dataclass

NEUTRON_MASS_DIFF_DA = 1.0033548378


@dataclass(frozen=True)
class PrecursorIsotopeTarget:
    label: str
    isotope_index: int
    target_mz: float


def build_precursor_isotope_targets(
    precursor_mz: float,
    charge: int | None,
    *,
    max_isotope: int = 2,
) -> list[PrecursorIsotopeTarget]:
    """Return M and, when charge is valid, M+n isotope XIC targets."""
    targets = [PrecursorIsotopeTarget(label="M", isotope_index=0, target_mz=precursor_mz)]
    if charge is None or charge <= 0:
        return targets

    for isotope_index in range(1, max_isotope + 1):
        targets.append(
            PrecursorIsotopeTarget(
                label=f"M+{isotope_index}",
                isotope_index=isotope_index,
                target_mz=precursor_mz + isotope_index * NEUTRON_MASS_DIFF_DA / charge,
            )
        )
    return targets
