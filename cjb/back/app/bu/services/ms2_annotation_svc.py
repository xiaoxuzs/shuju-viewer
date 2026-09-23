"""Serve PFMB MS2 annotations for Bottom-Up matches.

Runtime is fully O(1): RT slots are baked into ``match.extra_metadata.pfmb`` at
import time, so this service never loads ``index.json``. It only opens the
binary ``results.pfmb`` (mmap) and caches one reader per file for the process
lifetime.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.pfmb import PfmbAnnotationReader
from app.pfmb.locator import resolve_sidecar
from app.schemas import (
    BuMs2AnnotationMatrixOut,
    BuMs2AnnotationOut,
    BuMs2FragmentRow,
    BuMs2SlotItem,
    BuMs2SlotListOut,
    BuMs2SlotSummary,
    BuPfmbMatchedIon,
)

# One open PFMB reader per file path, reused across requests.
_readers: dict[str, PfmbAnnotationReader] = {}


def _has_pfmb(dataset: dict[str, Any]) -> bool:
    return bool((dataset.get("capabilities") or {}).get("has_ms2_pfmb"))


def _pfmb_block(match: dict[str, Any]) -> dict[str, Any] | None:
    return (match.get("extra_metadata") or {}).get("pfmb")


def _unique_peak_intensity(ions: list[Any]) -> float:
    by_peak: dict[int, float] = {}
    for ion in ions:
        peak_id = int(ion.peak_id)
        by_peak[peak_id] = max(by_peak.get(peak_id, 0.0), float(ion.intensity))
    return sum(by_peak.values())


def get_slots(dataset: dict[str, Any], match: dict[str, Any]) -> BuMs2SlotListOut:
    """Return the RT slots baked into the match (empty when no PFMB annotation)."""

    has_pfmb = _has_pfmb(dataset)
    block = _pfmb_block(match)
    if not has_pfmb or not block:
        return BuMs2SlotListOut(has_pfmb=has_pfmb)

    slots = [
        BuMs2SlotItem(
            prsm_index=int(slot["prsm_index"]),
            slot_index=int(slot["slot_index"]),
            slot_rt_seconds=float(slot["slot_rt"]),
            rt_minutes=float(slot["slot_rt"]) / 60.0,
        )
        for slot in block.get("slots", [])
    ]
    return BuMs2SlotListOut(
        has_pfmb=True,
        source_row=block.get("source_row"),
        apex_slot=block.get("apex_slot"),
        slots=slots,
    )


def get_annotation(dataset: dict[str, Any], match: dict[str, Any], prsm_index: int) -> BuMs2AnnotationOut:
    """Read one PFMB record, restricted to prsm indices that belong to *match*."""

    block = _pfmb_block(match)
    if not block:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no_pfmb_for_match")
    valid = {int(slot["prsm_index"]) for slot in block.get("slots", [])}
    if prsm_index not in valid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="prsm_index_not_in_match")

    sidecar = resolve_sidecar(dataset.get("extra_metadata"))
    if sidecar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="pfmb_sidecar_unavailable")

    annotation = _reader(str(sidecar.pfmb_path)).read(prsm_index)
    return BuMs2AnnotationOut(
        prsm_index=annotation.prsm_index,
        peptide=annotation.peptide,
        matched_peak_count=annotation.matched_peak_count,
        matched_ions=[
            BuPfmbMatchedIon(
                ion_type=ion.ion_type,
                fragment_ordinal=ion.fragment_ordinal,
                charge=ion.charge,
                intensity=ion.intensity,
                observed_neutral_mass=ion.observed_neutral_mass,
                theoretical_neutral_mass=ion.theoretical_neutral_mass,
                mass_error_ppm=ion.mass_error_ppm,
                mass_error_da=ion.mass_error_da,
                peak_id=ion.peak_id,
            )
            for ion in annotation.matched_ions
        ],
    )


def get_annotation_matrix(dataset: dict[str, Any], match: dict[str, Any]) -> BuMs2AnnotationMatrixOut:
    """Build the RT x fragment intensity matrix for *match* in one pass.

    Reads every slot's PFMB record once (single reader, no index.json), merges
    charges per ``(ion_type, fragment_ordinal)``, and returns a dense matrix so
    the heatmap loads without an N+1 fan-out over slots.
    """

    block = _pfmb_block(match)
    if not _has_pfmb(dataset) or not block:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no_pfmb_for_match")

    raw_slots = block.get("slots", [])
    slots = [
        BuMs2SlotItem(
            prsm_index=int(slot["prsm_index"]),
            slot_index=int(slot["slot_index"]),
            slot_rt_seconds=float(slot["slot_rt"]),
            rt_minutes=float(slot["slot_rt"]) / 60.0,
        )
        for slot in raw_slots
    ]
    if not slots:
        return BuMs2AnnotationMatrixOut(peptide="", apex_slot=block.get("apex_slot"), slots=[])

    sidecar = resolve_sidecar(dataset.get("extra_metadata"))
    if sidecar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="pfmb_sidecar_unavailable")
    reader = _reader(str(sidecar.pfmb_path))

    # column index per slot, and per-slot summed intensity per fragment family.
    peptide = ""
    # fragment key -> (ion_type, ordinal); fragment key -> {col -> summed intensity}
    fragment_meta: dict[str, tuple[str, int]] = {}
    fragment_cells: dict[str, dict[int, float]] = {}
    fragment_detected: dict[str, set[int]] = {}
    slot_summary: list[BuMs2SlotSummary] = []
    for col, slot in enumerate(slots):
        annotation = reader.read(slot.prsm_index)
        if not peptide:
            peptide = annotation.peptide
        for ion in annotation.matched_ions:
            key = f"{ion.ion_type}{ion.fragment_ordinal}"
            fragment_meta.setdefault(key, (ion.ion_type, ion.fragment_ordinal))
            cells = fragment_cells.setdefault(key, {})
            cells[col] = cells.get(col, 0.0) + float(ion.intensity)
            fragment_detected.setdefault(key, set()).add(col)
        slot_summary.append(
            BuMs2SlotSummary(
                prsm_index=slot.prsm_index,
                slot_index=slot.slot_index,
                rt_minutes=slot.rt_minutes,
                matched_peak_count=annotation.matched_peak_count,
                matched_ion_count=len(annotation.matched_ions),
                total_intensity=_unique_peak_intensity(annotation.matched_ions),
            )
        )

    rows = [
        BuMs2FragmentRow(
            key=key,
            ion_type=meta[0],  # type: ignore[arg-type]
            fragment_ordinal=meta[1],
            occurrence=sum(1 for v in fragment_cells[key].values() if v > 0),
            total_intensity=sum(fragment_cells[key].values()),
        )
        for key, meta in fragment_meta.items()
    ]
    # Most informative first: by slot occurrence, then total intensity.
    rows.sort(key=lambda r: (-r.occurrence, -r.total_intensity, r.ion_type, r.fragment_ordinal))

    intensity = [
        [fragment_cells[row.key].get(col, 0.0) for col in range(len(slots))]
        for row in rows
    ]
    detected = [
        [col in fragment_detected[row.key] for col in range(len(slots))]
        for row in rows
    ]

    return BuMs2AnnotationMatrixOut(
        peptide=peptide,
        apex_slot=block.get("apex_slot"),
        slots=slots,
        fragments=rows,
        intensity=intensity,
        detected=detected,
        slot_summary=slot_summary,
    )


def _reader(pfmb_path: str) -> PfmbAnnotationReader:
    reader = _readers.get(pfmb_path)
    if reader is None:
        reader = PfmbAnnotationReader(pfmb_path)
        _readers[pfmb_path] = reader
    return reader
