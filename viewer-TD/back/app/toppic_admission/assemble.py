"""Assemble viewer ``prsm{id}.json`` from TopPIC XML metadata + PFMB egress peaks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .cleavage import build_cleavage
from .msalign_header import MsalignSpectrumHeader, load_msalign_header_index
from .toppic_xml_source import ToppicXmlPrsmRecord

_PROTON_MASS = 1.00727646688


def _ion_type(series: str) -> str:
    mapping = {
        "b": "B",
        "y": "Y",
        "c": "C",
        "z_dot": "Z_DOT",
    }
    return mapping.get(series.lower(), series.upper())


def _str_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _build_residues(seq: str, *, first_position: int) -> list[dict[str, str]]:
    _ = first_position
    residues: list[dict[str, str]] = []
    for offset, acid in enumerate(seq):
        residues.append(
            {
                "position": _str_value(offset),
                "acid": acid,
            }
        )
    return residues


def _build_annotated_protein(
    record: ToppicXmlPrsmRecord,
    *,
    peaks: list[dict[str, Any]],
) -> dict[str, Any]:
    first_pos = record.start_pos or 1
    last_pos = record.end_pos or (first_pos + len(record.annotated_seq) - 1 if record.annotated_seq else first_pos)
    protein_length = max(last_pos - first_pos + 1, len(record.annotated_seq))
    return {
        "sequence_id": _str_value(record.sequence_id),
        "proteoform_id": _str_value(record.proteoform_id),
        "sequence_name": record.sequence_name,
        "sequence_description": record.sequence_description,
        "proteoform_mass": _str_value(record.adjusted_prec_mass or record.ori_prec_mass),
        "n_acetylation": "1" if record.n_acetylation else "0",
        "unexpected_shift_number": "0",
        "protein_length": _str_value(protein_length),
        "first_residue_position": _str_value(first_pos),
        "last_residue_position": _str_value(last_pos),
        "annotated_seq": record.annotated_seq,
        "annotation": {
            "residue": _build_residues(record.annotated_seq, first_position=first_pos),
            "cleavage": build_cleavage(peaks, protein_length=protein_length),
            "mass_shift": [],
        },
    }


def _rows_to_peaks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    peaks: list[dict[str, Any]] = []
    for row in rows:
        peak_id = row.get("peak_id")
        matched = bool(row.get("matched"))
        matched_ions: list[dict[str, str]] = []
        if matched:
            series = str(row.get("fragment_series") or "")
            ordinal = row.get("fragment_ordinal")
            matched_ions.append(
                {
                    "ion_type": _ion_type(series),
                    "ion_position": _str_value(ordinal),
                    "ion_display_position": _str_value(ordinal),
                    "theoretical_mass": _str_value(row.get("neutral_mass")),
                    "mass_error": _str_value(row.get("mass_error_da")),
                    "ppm": _str_value(row.get("mass_error_ppm")),
                }
            )
        peak: dict[str, Any] = {
            "peak_id": _str_value(peak_id),
            "spec_id": _str_value(row.get("spec_id")),
            "monoisotopic_mass": _str_value(row.get("neutral_mass")),
            "intensity": _str_value(row.get("intensity")),
            "charge": _str_value(row.get("charge")),
            "matched_ions": {"matched_ion": matched_ions},
        }
        if row.get("mz") is not None:
            peak["monoisotopic_mz"] = _str_value(row.get("mz"))
        peaks.append(peak)
    return peaks


def _compute_precursor_mz(*, mono_mass: float | None, charge: int | None) -> float | None:
    if mono_mass is None or charge is None or charge <= 0:
        return None
    return (mono_mass + charge * _PROTON_MASS) / charge


def _build_ms_header(
    *,
    record: ToppicXmlPrsmRecord,
    rows: list[dict[str, Any]],
    mzml_file_name: str,
    msalign_header: MsalignSpectrumHeader | None,
) -> dict[str, str]:
    ms2_scan = record.spectrum_scan or int(rows[0].get("scan") or 0)
    spec_id = record.spectrum_id or int(rows[0].get("spec_id") or 0)
    ms1_scan = ms2_scan
    ms1_id = spec_id
    precursor_charge = ""
    precursor_mz = ""
    target_mass = record.adjusted_prec_mass or record.ori_prec_mass

    if msalign_header is not None:
        selected_mass, selected_charge, selected_mz = msalign_header.select_precursor(target_mass)
        if msalign_header.ms_one_scan is not None:
            ms1_scan = msalign_header.ms_one_scan
        if msalign_header.ms_one_id is not None:
            ms1_id = msalign_header.ms_one_id
        if selected_charge is not None:
            precursor_charge = _str_value(selected_charge)
        if selected_mz is not None:
            precursor_mz = _str_value(selected_mz)
        elif selected_mass is not None and selected_charge is not None:
            computed = _compute_precursor_mz(mono_mass=selected_mass, charge=selected_charge)
            if computed is not None:
                precursor_mz = _str_value(computed)

    if not precursor_mz and target_mass is not None and precursor_charge:
        computed = _compute_precursor_mz(
            mono_mass=target_mass,
            charge=int(float(precursor_charge)),
        )
        if computed is not None:
            precursor_mz = _str_value(computed)

    return {
        "spectrum_file_name": mzml_file_name,
        "ms1_scans": _str_value(ms1_scan),
        "scans": _str_value(ms2_scan),
        "ms1_ids": _str_value(ms1_id),
        "ids": _str_value(spec_id),
        "precursor_mono_mass": _str_value(target_mass),
        "precursor_charge": precursor_charge,
        "precursor_mz": precursor_mz,
        "feature_inte": _str_value(record.frac_feature_inte),
    }


def assemble_prsm_document(
    *,
    record: ToppicXmlPrsmRecord,
    peaks_doc: dict[str, Any],
    mzml_file_name: str,
    provenance: dict[str, Any] | None = None,
    msalign_header: MsalignSpectrumHeader | None = None,
) -> dict[str, Any]:
    """Build one viewer-compatible PrSM JSON document."""
    rows = peaks_doc.get("rows")
    if not isinstance(rows, list):
        raise ValueError("egress peaks document missing rows[]")

    matched_peak_count = int(peaks_doc.get("matched_peak_count") or sum(1 for r in rows if r.get("matched")))
    matched_fragment_count = sum(int(r.get("match_hits") or 0) for r in rows if r.get("matched"))

    peaks = _rows_to_peaks(rows)
    ms_header = _build_ms_header(
        record=record,
        rows=rows,
        mzml_file_name=mzml_file_name,
        msalign_header=msalign_header,
    )
    ms2_scan = int(ms_header["scans"] or 0)
    ms1_scan = int(ms_header["ms1_scans"] or ms2_scan)

    prsm_body: dict[str, Any] = {
        "prsm_id": _str_value(record.prsm_id),
        "p_value": _str_value(record.p_value),
        "e_value": _str_value(record.e_value),
        "fdr": _str_value(record.fdr if record.fdr is not None and record.fdr >= 0 else ""),
        "matched_fragment_number": _str_value(matched_fragment_count or record.match_fragment_num),
        "matched_peak_number": _str_value(matched_peak_count or record.match_peak_num),
        "ms": {
            "ms_header": ms_header,
            "peaks": {"peak": peaks},
        },
        "annotated_protein": _build_annotated_protein(record, peaks=peaks),
        "spectrum_map": {
            "source_type": "mzml",
            "mzml_file": mzml_file_name,
            "default_ms1_scan": ms1_scan,
            "default_ms2_scan": ms2_scan,
            "all_ms1_scans": [ms1_scan],
            "all_ms2_scans": [ms2_scan],
        },
    }

    doc: dict[str, Any] = {"prsm_data": {"prsm": prsm_body}}
    if provenance:
        doc["viewer_provenance"] = provenance
    return doc


def write_prsm_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")


def assemble_all_from_egress(
    *,
    xml_records: list[ToppicXmlPrsmRecord],
    egress_dir: Path,
    prsms_dir: Path,
    mzml_file_name: str,
    provenance: dict[str, Any] | None = None,
    ms2_msalign: Path | None = None,
) -> list[Path]:
    """Write ``prsm{id}.json`` for every egress peaks file."""
    index_path = egress_dir / "_index.json"
    if not index_path.is_file():
        raise FileNotFoundError(f"missing egress index: {index_path}")
    index_doc = json.loads(index_path.read_text(encoding="utf-8"))
    items = index_doc.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError(f"egress index missing items[]: {index_path}")

    msalign_index: dict[int, MsalignSpectrumHeader] = {}
    if ms2_msalign is not None:
        msalign_index = load_msalign_header_index(ms2_msalign)

    written: list[Path] = []
    for item in items:
        prsm_index = int(item["prsm_index"])
        peaks_path = egress_dir / f"prsm{prsm_index}_peaks.json"
        if not peaks_path.is_file():
            output_file = item.get("output_file")
            if output_file:
                candidate = Path(str(output_file))
                if candidate.is_file():
                    peaks_path = candidate
        if not peaks_path.is_file():
            raise FileNotFoundError(f"missing egress peaks for prsm_index={prsm_index}: {peaks_path}")
        if prsm_index >= len(xml_records):
            raise ValueError(
                f"prsm_index {prsm_index} out of range for TopPIC XML ({len(xml_records)} records)"
            )
        peaks_doc = json.loads(peaks_path.read_text(encoding="utf-8"))
        record = xml_records[prsm_index]
        msalign_header = msalign_index.get(record.spectrum_id)
        doc = assemble_prsm_document(
            record=record,
            peaks_doc=peaks_doc,
            mzml_file_name=mzml_file_name,
            provenance=provenance,
            msalign_header=msalign_header,
        )
        out_path = prsms_dir / f"prsm{record.prsm_id}.json"
        write_prsm_json(out_path, doc)
        written.append(out_path)
    return written
