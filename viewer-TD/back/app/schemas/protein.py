"""Pydantic output models for protein, proteoform, and PrSM APIs (aligned with ORM columns)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ProteinListItemOut(BaseModel):
    """One row in the protein list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sequence_id: int
    sequence_name: str
    sequence_description: str | None
    compatible_proteoform_number: int
    prsm_number: int
    best_prsm_id: int | None
    best_prsm_e_value: float | None


class ProteinDetailOut(ProteinListItemOut):
    """Protein detail with nested proteoform summary rows."""

    proteoforms: list["ProteoformListItemOut"] = []


class ProteoformListItemOut(BaseModel):
    """One row in the proteoform list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    proteoform_id: int
    sequence_id: int
    sequence_name: str
    proteoform_mass: float | None
    prsm_number: int
    best_prsm_id: int | None
    best_prsm_e_value: float | None
    n_acetylation: int | None
    unexpected_shift_number: int | None


class ProteoformDetailOut(ProteoformListItemOut):
    """Proteoform detail with PrSM summary rows."""

    protein_id: int
    prsms: list["PrsmListItemOut"] = []


class PrsmListItemOut(BaseModel):
    """One row in the PrSM list (no heavy JSON blobs)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    prsm_id: int
    sequence_id: int
    p_value: float | None
    e_value: float | None
    fdr: float | None
    matched_fragment_number: int | None
    matched_peak_number: int | None
    precursor_mono_mass: float | None
    precursor_charge: int | None
    precursor_mz: float | None
    proteoform_mass: float | None
    ms1_scans: str | None
    ms2_scans: str | None


class PrsmDetailOut(PrsmListItemOut):
    """PrSM detail: spectrum metadata plus raw ``annotated_protein`` / ``ms_peaks`` JSON."""

    dataset_id: int
    run_id: int
    proteoform_id: int
    spectrum_file_name: str | None
    ms1_ids: str | None
    ms2_ids: str | None
    feature_inte: float | None
    ms_header: dict[str, Any] | None
    annotated_protein: dict[str, Any] | None
    ms_peaks: dict[str, Any] | None


# Resolve forward references among nested models (ProteinDetailOut ↔ ProteoformListItemOut, etc.).
ProteinDetailOut.model_rebuild()
ProteoformDetailOut.model_rebuild()
