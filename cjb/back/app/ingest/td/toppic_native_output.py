"""Prepare TopPIC native output for the existing PrSM-detail adapter.

TopPIC native output contains ``*_toppic_prsm.xml`` (or
``*.toppic_raw_prsm``) plus the matching TopFD ``*_ms2.msalign`` file.  The
viewer currently consumes one JSON detail document per PrSM, so this module
builds those documents in a managed derived directory.  It also expands
``*.mzML.gz`` because indexed spectrum access requires uncompressed mzML.

This is the replaceable boundary for the future binary implementation.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from app.services.mzml_mapping import (
    collect_mzml_files,
    normalize_spectrum_file_name,
)

AA_MASS: dict[str, float] = {
    "A": 71.03711,
    "R": 156.10111,
    "N": 114.04293,
    "D": 115.02694,
    "C": 103.00919,
    "E": 129.04259,
    "Q": 128.05858,
    "G": 57.02146,
    "H": 137.05891,
    "I": 113.08406,
    "L": 113.08406,
    "K": 128.09496,
    "M": 131.04049,
    "F": 147.06841,
    "P": 97.05276,
    "S": 87.03203,
    "T": 101.04768,
    "W": 186.07931,
    "Y": 163.06333,
    "V": 99.06841,
}
H2O = 18.0105646863
PROTON = 1.00727646677


class TopPicNativeOutputError(RuntimeError):
    """Raised when native TopPIC output is incomplete or inconsistent."""


@dataclass(frozen=True)
class TopPicNativeInput:
    prsm_path: Path
    msalign_path: Path


@dataclass(frozen=True)
class PreparedTopPicNativeOutput:
    root: Path
    prsm_count: int
    skipped_prsm_count: int
    mzml_files: tuple[Path, ...]


def _native_source_key(path: Path) -> str:
    name = path.name
    lower = name.lower()
    if lower.endswith("_toppic_prsm.xml"):
        return name[: -len("_toppic_prsm.xml")]
    if lower.endswith(".toppic_raw_prsm"):
        return name[: -len(".toppic_raw_prsm")]
    raise ValueError(path)


def discover_toppic_native_inputs(root: Path) -> tuple[TopPicNativeInput, ...]:
    """Return deterministic TopPIC PrSM/MSAlign pairs, preferring XML output."""
    source_root = root.resolve()
    xml_paths = sorted(
        (path.resolve() for path in source_root.rglob("*_toppic_prsm.xml") if path.is_file()),
        key=str,
    )
    raw_paths = sorted(
        (path.resolve() for path in source_root.rglob("*.toppic_raw_prsm") if path.is_file()),
        key=str,
    )

    selected: dict[str, Path] = {}
    for path in xml_paths:
        selected[_native_source_key(path).casefold()] = path
    for path in raw_paths:
        selected.setdefault(_native_source_key(path).casefold(), path)
    if not selected:
        return ()

    msalign_by_name: dict[str, list[Path]] = {}
    for path in source_root.rglob("*.msalign"):
        if path.is_file():
            msalign_by_name.setdefault(path.name.casefold(), []).append(path.resolve())

    pairs: list[TopPicNativeInput] = []
    for source_key, prsm_path in sorted(selected.items()):
        expected_name = f"{source_key}.msalign"
        candidates = msalign_by_name.get(expected_name, [])
        if not candidates:
            raise TopPicNativeOutputError(
                f"Missing matching MSAlign file for {prsm_path.name}: expected {expected_name}"
            )
        same_parent = [path for path in candidates if path.parent == prsm_path.parent]
        chosen_pool = same_parent or candidates
        if len(chosen_pool) != 1:
            rendered = ", ".join(str(path) for path in sorted(chosen_pool, key=str))
            raise TopPicNativeOutputError(
                f"Ambiguous MSAlign files for {prsm_path.name}: {rendered}"
            )
        pairs.append(TopPicNativeInput(prsm_path=prsm_path, msalign_path=chosen_pool[0]))
    return tuple(pairs)


def has_toppic_native_output(root: Path) -> bool:
    """Return whether a complete native PrSM/MSAlign pair is present."""
    try:
        return bool(discover_toppic_native_inputs(root))
    except TopPicNativeOutputError:
        return False


def parse_msalign(path: Path) -> dict[int, dict[str, Any]]:
    """Read TopFD MS2 MSAlign blocks keyed by ``SCANS``."""
    result: dict[int, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    peaks: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            if line == "BEGIN IONS":
                current = {}
                peaks = []
                continue
            if line == "END IONS":
                if current is not None:
                    current["peaks"] = peaks
                    scan = current.get("SCANS")
                    try:
                        if scan is not None:
                            result[int(scan)] = current
                    except (TypeError, ValueError):
                        pass
                current = None
                peaks = []
                continue
            if current is None:
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                current[key.strip()] = value.strip()
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                peaks.append(
                    {
                        "mass": float(parts[0]),
                        "intensity": float(parts[1]),
                        "charge": int(parts[2]),
                    }
                )
            except ValueError:
                continue
    return result


def parse_prsm_xml(path: Path) -> list[dict[str, Any]]:
    """Read native TopPIC PrSM records used by the Viewer detail contract."""
    root = ET.parse(path).getroot()
    entries: list[dict[str, Any]] = []
    for prsm in root.findall("prsm"):
        proteoform = prsm.find("proteoform")
        if proteoform is None:
            continue
        mass_shifts = []
        for shift in proteoform.findall("mass_shift_list/mass_shift"):
            mass_shifts.append(
                {
                    "left": int(shift.findtext("left_bp_pos", "0")),
                    "right": int(shift.findtext("right_bp_pos", "0")),
                    "shift": float(shift.findtext("shift", "0")),
                    "type": shift.findtext(
                        "alteration_list/alteration/alter_type/name",
                        "Unexpected",
                    ).lower(),
                }
            )
        entries.append(
            {
                "prsm_id": prsm.findtext("prsm_id", "0"),
                "spectrum_id": prsm.findtext("spectrum_id", "0"),
                "spectrum_scan": int(prsm.findtext("spectrum_scan", "0")),
                "p_value": prsm.findtext("extreme_value/p_value", "0"),
                "e_value": prsm.findtext("extreme_value/e_value", "0"),
                "fdr": prsm.findtext("fdr", "-1"),
                "start_pos": int(proteoform.findtext("start_pos", "0")),
                "end_pos": int(proteoform.findtext("end_pos", "0")),
                "proteo_db_seq": proteoform.findtext("proteo_db_seq", ""),
                "proteo_match_seq": proteoform.findtext("proteo_match_seq", ""),
                "seq_name": proteoform.findtext("fasta_seq/seq_name", ""),
                "seq_desc": proteoform.findtext("fasta_seq/seq_desc", ""),
                "sequence_id": proteoform.findtext("prot_id"),
                "proteoform_id": proteoform.findtext("proteo_cluster_id"),
                "unexpected_shift_number": proteoform.findtext(
                    "unexpected_ptm_num"
                ),
                "n_term_form": proteoform.findtext("prot_mod/name", "NONE"),
                "mass_shifts": mass_shifts,
            }
        )
    return entries


def theoretical_by(
    sequence: str,
    mass_shifts: list[dict[str, Any]],
) -> tuple[list[float], list[float]]:
    """Calculate neutral monoisotopic b/y masses for every cleavage."""
    prefix = [0.0] * (len(sequence) + 1)
    for index, amino_acid in enumerate(sequence):
        prefix[index + 1] = prefix[index] + AA_MASS.get(amino_acid, 0.0)
    total = prefix[len(sequence)]

    b_ions: list[float] = []
    y_ions: list[float] = []
    for index in range(1, len(sequence)):
        b_mass = prefix[index]
        y_mass = total - prefix[index] + H2O
        for shift in mass_shifts:
            if shift["right"] <= index:
                b_mass += shift["shift"]
            if shift["left"] >= index:
                y_mass += shift["shift"]
        b_ions.append(b_mass)
        y_ions.append(y_mass)
    return b_ions, y_ions


def match_peaks(
    peaks: list[dict[str, Any]],
    b_ions: list[float],
    y_ions: list[float],
    tolerance_ppm: float,
) -> dict[int, dict[str, Any]]:
    """Assign the closest b/y ion inside the configured ppm tolerance."""
    matches: dict[int, dict[str, Any]] = {}
    for peak_index, peak in enumerate(peaks):
        mass = peak["mass"]
        best: dict[str, Any] | None = None
        best_error = float("inf")
        for ion_type, ions in (("B", b_ions), ("Y", y_ions)):
            for ion_index, theoretical_mass in enumerate(ions):
                if theoretical_mass <= 0:
                    continue
                ppm = (mass - theoretical_mass) / theoretical_mass * 1e6
                if abs(ppm) <= tolerance_ppm and abs(ppm) < best_error:
                    best = {
                        "ion_type": ion_type,
                        "ion_position": ion_index + 1,
                        "theoretical_mass": theoretical_mass,
                        "mass_error": mass - theoretical_mass,
                        "ppm": ppm,
                    }
                    best_error = abs(ppm)
        if best is not None:
            matches[peak_index] = best
    return matches


def _formatted_matched_ion(ion: dict[str, Any]) -> dict[str, Any]:
    position = int(ion["ion_position"])
    return {
        "ion_type": ion["ion_type"],
        "match_shift": f"{0.0:.10f}",
        "theoretical_mass": f"{ion['theoretical_mass']:.4f}",
        "ion_position": str(position),
        "ion_display_position": str(position),
        "ion_sort_name": f"{ion['ion_type']}{position:05d}",
        "ion_left_position": str(position),
        "mass_error": f"{ion['mass_error']:.4f}",
        "ppm": f"{ion['ppm']:.2f}",
    }


def _float_text(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "0"


def build_prsm_document(
    entry: dict[str, Any],
    msalign: dict[str, Any],
    matched: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Build the canonical Viewer PrSM detail document."""
    sequence = entry["proteo_db_seq"]
    sequence_length = len(sequence)
    spectrum_id = msalign.get("SPECTRUM_ID", "0")

    peaks_out: list[dict[str, Any]] = []
    for peak_index, peak in enumerate(msalign["peaks"]):
        charge = peak["charge"]
        mass = peak["mass"]
        item: dict[str, Any] = {
            "spec_id": str(spectrum_id),
            "peak_id": str(peak_index),
            "monoisotopic_mass": f"{mass:.4f}",
            "monoisotopic_mz": f"{(mass + charge * PROTON) / charge:.4f}",
            "intensity": f"{peak['intensity']:.2f}",
            "charge": str(charge),
        }
        if peak_index in matched:
            item["matched_ions_num"] = "1"
            item["matched_ions"] = {
                "matched_ion": _formatted_matched_ion(matched[peak_index])
            }
        peaks_out.append(item)

    residues = [
        {"position": str(index), "acid": amino_acid}
        for index, amino_acid in enumerate(sequence)
    ]
    peak_charge_by_id = {
        str(index): str(peak["charge"])
        for index, peak in enumerate(msalign["peaks"])
    }
    b_by_position: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    y_by_position: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    for peak_id, ion in matched.items():
        position = int(ion["ion_position"])
        target = b_by_position if ion["ion_type"] == "B" else y_by_position
        cleavage_position = position if ion["ion_type"] == "B" else sequence_length - position
        target.setdefault(cleavage_position, []).append((peak_id, ion))

    cleavages: list[dict[str, Any]] = []
    for cleavage_position in range(sequence_length + 1):
        n_hits = b_by_position.get(cleavage_position, [])
        c_hits = y_by_position.get(cleavage_position, [])
        matched_peaks = []
        for peak_id, ion in n_hits + c_hits:
            matched_peaks.append(
                {
                    "ion_type": ion["ion_type"],
                    "ion_position": str(ion["ion_position"]),
                    "ion_display_position": str(ion["ion_position"]),
                    "spec_id": str(spectrum_id),
                    "peak_id": str(peak_id),
                    "peak_charge": peak_charge_by_id.get(str(peak_id), "0"),
                }
            )
        cleavages.append(
            {
                "position": str(cleavage_position),
                "exist_n_ion": "1" if n_hits else "0",
                "exist_c_ion": "1" if c_hits else "0",
                "matched_peaks": (
                    None
                    if not matched_peaks
                    else {
                        "matched_peak": (
                            matched_peaks[0]
                            if len(matched_peaks) == 1
                            else matched_peaks
                        )
                    }
                ),
            }
        )

    mass_shift_objects = [
        {
            "id": str(index),
            "left_position": str(shift["left"]),
            "right_position": str(shift["right"]),
            "shift": f"{shift['shift']:.10f}",
            "anno": f"{shift['shift']:+.4f}",
            "shift_type": shift.get("type", "unexpected"),
        }
        for index, shift in enumerate(entry["mass_shifts"])
    ]
    annotation: dict[str, Any] = {
        "protein_length": str(sequence_length),
        "first_residue_position": str(entry["start_pos"]),
        "last_residue_position": str(entry["end_pos"]),
        "annotated_seq": entry["proteo_match_seq"],
        "residue": residues,
        "cleavage": cleavages,
    }
    if len(mass_shift_objects) == 1:
        annotation["mass_shift"] = mass_shift_objects[0]
    elif mass_shift_objects:
        annotation["mass_shift"] = mass_shift_objects

    return {
        "prsm": {
            "prsm_id": str(entry["prsm_id"]),
            "p_value": str(entry.get("p_value", "0")),
            "e_value": str(entry.get("e_value", "0")),
            "fdr": str(entry.get("fdr", "-1")),
            "matched_fragment_number": str(len(matched)),
            "matched_peak_number": str(len(matched)),
            "ms": {
                "ms_header": {
                    "spectrum_file_name": msalign.get("FILE_NAME", ""),
                    "ms1_ids": msalign.get("MS_ONE_ID", "0"),
                    "ms1_scans": msalign.get("MS_ONE_SCAN", "0"),
                    "ids": str(spectrum_id),
                    "scans": msalign.get("SCANS", "0"),
                    "precursor_mono_mass": _float_text(msalign.get("PRECURSOR_MASS")),
                    "precursor_charge": msalign.get("PRECURSOR_CHARGE", "0") or "0",
                    "precursor_mz": _float_text(msalign.get("PRECURSOR_MZ")),
                    "feature_inte": msalign.get("PRECURSOR_INTENSITY", "0") or "0",
                },
                "peaks": {"peak": peaks_out},
            },
            "annotated_protein": {
                "sequence_id": str(entry.get("sequence_id") or entry["prsm_id"]),
                "proteoform_id": str(
                    entry.get("proteoform_id") or entry["prsm_id"]
                ),
                "sequence_name": entry["seq_name"],
                "sequence_description": entry["seq_desc"],
                "proteoform_mass": _float_text(msalign.get("PRECURSOR_MASS")),
                "n_acetylation": (
                    "1" if "ACETYLATION" in entry["n_term_form"] else "0"
                ),
                "unexpected_shift_number": str(
                    entry.get("unexpected_shift_number")
                    or len(entry["mass_shifts"])
                ),
                "annotation": annotation,
            },
        }
    }


def _decompress_mzml(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with gzip.open(source, "rb") as source_handle, temporary.open("wb") as output:
            shutil.copyfileobj(source_handle, output, length=8 * 1024 * 1024)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination.resolve()


def _place_mzml_in_output(source: Path, output_root: Path) -> Path:
    destination = output_root / "spectra" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.resolve(strict=False) == source.resolve(strict=False):
        return destination.resolve()
    if destination.exists() and destination.stat().st_size == source.stat().st_size:
        return destination.resolve()
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    try:
        try:
            os.link(source, temporary)
        except OSError:
            shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination.resolve()


def _write_minimal_proteoform_tsv(output_root: Path, mzml_files: Sequence[Path]) -> None:
    if not mzml_files:
        return
    run_key = normalize_spectrum_file_name(mzml_files[0].name)
    table = output_root / f"{run_key}_ms2_toppic_proteoform.tsv"
    table.write_text(
        "Generated by: Viewer TopPIC Native prepare\n"
        "Data file name\tProteoform ID\tProteoform mass\n",
        encoding="utf-8",
    )


def prepare_toppic_native_output(
    *,
    source_root: Path,
    output_root: Path,
    tolerance_ppm: float = 10.0,
    additional_mzml_files: Sequence[Path] = (),
) -> PreparedTopPicNativeOutput:
    """Generate every PrSM detail and return Viewer-ready mzML paths."""
    source = source_root.resolve()
    output = output_root.resolve()
    pairs = discover_toppic_native_inputs(source)
    if not pairs:
        raise TopPicNativeOutputError(
            "No TopPIC native PrSM XML or matching MSAlign files were found."
        )

    details_dir = output / "data" / "prsms"
    details_dir.mkdir(parents=True, exist_ok=True)
    for stale_detail in details_dir.glob("prsm*.json"):
        stale_detail.unlink()
    seen_prsm_ids: set[int] = set()
    generated = 0
    missing_scans: list[str] = []
    for pair in pairs:
        entries = parse_prsm_xml(pair.prsm_path)
        msalign_by_scan = parse_msalign(pair.msalign_path)
        for entry in entries:
            prsm_id = int(entry["prsm_id"])
            if prsm_id in seen_prsm_ids:
                raise TopPicNativeOutputError(
                    f"Duplicate PrSM id {prsm_id} across TopPIC native output files."
                )
            seen_prsm_ids.add(prsm_id)
            scan = int(entry["spectrum_scan"])
            msalign = msalign_by_scan.get(scan)
            if msalign is None:
                missing_scans.append(
                    f"PrSM {prsm_id} scan {scan} ({pair.msalign_path.name})"
                )
                continue
            b_ions, y_ions = theoretical_by(
                entry["proteo_db_seq"],
                entry["mass_shifts"],
            )
            matched = match_peaks(
                msalign["peaks"],
                b_ions,
                y_ions,
                tolerance_ppm,
            )
            document = build_prsm_document(entry, msalign, matched)
            destination = details_dir / f"prsm{prsm_id}.json"
            destination.write_text(
                json.dumps(document, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            generated += 1

    if missing_scans:
        preview = "; ".join(missing_scans[:10])
        suffix = (
            ""
            if len(missing_scans) <= 10
            else f"; and {len(missing_scans) - 10} more"
        )
        raise TopPicNativeOutputError(
            f"MSAlign does not cover every TopPIC PrSM: {preview}{suffix}"
        )
    if generated == 0:
        raise TopPicNativeOutputError("TopPIC native output contains no importable PrSM records.")

    uncompressed: list[Path] = []
    compressed: list[Path] = []
    for path in collect_mzml_files(source):
        if path.name.lower().endswith(".gz"):
            compressed.append(path)
        else:
            uncompressed.append(path.resolve())
    additional = [path.resolve() for path in additional_mzml_files]
    ready_keys = {
        normalize_spectrum_file_name(path.name)
        for path in [*uncompressed, *additional]
    }
    compressed_by_key: dict[str, list[Path]] = {}
    for path in compressed:
        compressed_by_key.setdefault(
            normalize_spectrum_file_name(path.name),
            [],
        ).append(path)
    spectra_dir = output / "spectra"
    expanded: list[Path] = []
    for key, candidates in sorted(compressed_by_key.items()):
        if key in ready_keys:
            continue
        if len(candidates) != 1:
            rendered = ", ".join(str(path) for path in sorted(candidates, key=str))
            raise TopPicNativeOutputError(
                f"Ambiguous compressed mzML files for spectrum key {key}: {rendered}"
            )
        source_path = candidates[0]
        expanded.append(
            _decompress_mzml(
                source_path,
                spectra_dir / source_path.name[: -len(".gz")],
            )
        )
    staged_uncompressed = [
        _place_mzml_in_output(path, output)
        for path in [*uncompressed, *additional]
    ]
    mzml_files = tuple(
        sorted(
            {
                *staged_uncompressed,
                *expanded,
            },
            key=str,
        )
    )
    if not mzml_files:
        raise TopPicNativeOutputError(
            "TopPIC native output requires mzML, mzML.gz, or converted RAW spectra."
        )
    _write_minimal_proteoform_tsv(output, mzml_files)

    return PreparedTopPicNativeOutput(
        root=output,
        prsm_count=generated,
        skipped_prsm_count=0,
        mzml_files=mzml_files,
    )
