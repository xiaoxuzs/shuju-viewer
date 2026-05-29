"""Parse TopFD MS2 msalign spectrum headers for viewer PrSM assembly."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MsalignSpectrumHeader:
    spectrum_id: int
    scan: int
    ms_one_id: int | None
    ms_one_scan: int | None
    precursor_mass_text: str
    precursor_charge_text: str
    precursor_mz_text: str

    def select_precursor(
        self,
        target_mass: float | None,
    ) -> tuple[float | None, int | None, float | None]:
        return select_precursor_from_fields(
            precursor_mass_text=self.precursor_mass_text,
            precursor_charge_text=self.precursor_charge_text,
            precursor_mz_text=self.precursor_mz_text,
            target_mass=target_mass,
        )


def _parse_int(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _parse_colon_floats(text: str) -> list[float]:
    if not text.strip():
        return []
    out: list[float] = []
    for part in text.split(":"):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out


def _parse_colon_ints(text: str) -> list[int]:
    if not text.strip():
        return []
    out: list[int] = []
    for part in text.split(":"):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(float(part)))
        except ValueError:
            continue
    return out


def pick_precursor_feature_index(masses: list[float], target_mass: float | None) -> int:
    """Pick the colon-separated precursor feature closest to ``target_mass``."""
    if not masses:
        return 0
    if target_mass is None:
        return 0
    best_index = 0
    best_distance = float("inf")
    for index, mass in enumerate(masses):
        distance = abs(mass - target_mass)
        if distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index


def _select_feature(values: list[float] | list[int], *, index: int) -> float | int | None:
    if not values:
        return None
    if index < 0 or index >= len(values):
        return values[0]
    return values[index]


def select_precursor_from_fields(
    *,
    precursor_mass_text: str,
    precursor_charge_text: str,
    precursor_mz_text: str,
    target_mass: float | None,
) -> tuple[float | None, int | None, float | None]:
    """Select one precursor feature from msalign colon-separated fields."""
    masses = _parse_colon_floats(precursor_mass_text)
    charges = _parse_colon_ints(precursor_charge_text)
    mzs = _parse_colon_floats(precursor_mz_text)
    feature_index = pick_precursor_feature_index(masses, target_mass)

    mass = _select_feature(masses, index=feature_index)
    charge = _select_feature(charges, index=feature_index)
    mz = _select_feature(mzs, index=feature_index)
    return (
        float(mass) if mass is not None else None,
        int(charge) if charge is not None else None,
        float(mz) if mz is not None else None,
    )


def parse_msalign_block(lines: list[str]) -> MsalignSpectrumHeader | None:
    """Parse one ``BEGIN IONS`` block (without the sentinel lines)."""
    fields: dict[str, str] = {}
    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip()] = value.strip()

    spectrum_id = _parse_int(fields.get("SPECTRUM_ID", ""))
    scan = _parse_int(fields.get("SCANS", ""))
    if spectrum_id is None or scan is None:
        return None

    return MsalignSpectrumHeader(
        spectrum_id=spectrum_id,
        scan=scan,
        ms_one_id=_parse_int(fields.get("MS_ONE_ID", "")),
        ms_one_scan=_parse_int(fields.get("MS_ONE_SCAN", "")),
        precursor_mass_text=fields.get("PRECURSOR_MASS", ""),
        precursor_charge_text=fields.get("PRECURSOR_CHARGE", ""),
        precursor_mz_text=fields.get("PRECURSOR_MZ", ""),
    )


def load_msalign_header_index(msalign_path: Path) -> dict[int, MsalignSpectrumHeader]:
    """Index msalign spectrum headers by ``SPECTRUM_ID``."""
    if not msalign_path.is_file():
        raise FileNotFoundError(f"msalign file not found: {msalign_path}")

    index: dict[int, MsalignSpectrumHeader] = {}
    block: list[str] = []
    in_block = False

    with msalign_path.open(encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line == "BEGIN IONS":
                block = []
                in_block = True
                continue
            if line == "END IONS":
                if in_block:
                    header = parse_msalign_block(block)
                    if header is not None:
                        index[header.spectrum_id] = header
                in_block = False
                block = []
                continue
            if in_block:
                block.append(line)

    return index
