"""蛋白质、proteoform、PrSM 相关 API 输出模型（与 ORM 字段对齐）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ProteinListItemOut(BaseModel):
    """蛋白质列表行。"""

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
    """蛋白质详情：附带嵌套 proteoform 摘要列表。"""

    proteoforms: list["ProteoformListItemOut"] = []


class ProteoformListItemOut(BaseModel):
    """Proteoform 列表行。"""

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
    """Proteoform 详情：附带 PrSM 摘要列表。"""

    protein_id: int
    prsms: list["PrsmListItemOut"] = []


class PrsmListItemOut(BaseModel):
    """PrSM 列表行（不含大 JSON 字段）。"""

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
    """PrSM 详情：附加谱图元数据及 ``annotated_protein`` / ``ms_peaks`` 原始 JSON。"""

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


# 解析前向引用的嵌套类型（ProteinDetailOut ↔ ProteoformListItemOut 等）。
ProteinDetailOut.model_rebuild()
ProteoformDetailOut.model_rebuild()
