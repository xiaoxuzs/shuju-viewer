"""Bottom-Up DIA API DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BuRunSummary(BaseModel):
    """Run summary embedded in Bottom-Up dataset responses."""

    model_config = ConfigDict(from_attributes=True)

    run_id: int
    file_name: str
    raw_format: str | None = None
    diann_run_name: str | None = None
    match_count: int | None = None
    has_im: bool | None = None


class BuOverviewCounts(BaseModel):
    matches: int = 0
    peptides: int = 0
    proteins: int = 0
    protein_groups: int = 0
    runs: int = 0
    decoy_matches: int = 0


class BuQcBlock(BaseModel):
    by_run: list[dict[str, Any]] = Field(default_factory=list)
    aggregated: dict[str, Any] = Field(default_factory=dict)


class BuOverviewOut(BaseModel):
    dataset_id: int
    slug: str
    name: str
    analysis_mode: Literal["BOTTOM_UP"] = "BOTTOM_UP"
    source_software: str | None = None
    status: str
    source_root: str
    q_value_cutoff: float | None = None
    counts: BuOverviewCounts
    qc: BuQcBlock
    runs: list[BuRunSummary] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    import_stats: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class BuRtMzHeatmapOut(BaseModel):
    unit_rt: Literal["min"] = "min"
    unit_mz: Literal["Th"] = "Th"
    rt_edges: list[float] = Field(default_factory=list)
    mz_edges: list[float] = Field(default_factory=list)
    counts: list[list[int]] = Field(default_factory=list)
    max_count: int = 0
    total_points: int = 0
    run_id: int | None = None


class BuProteinListItemOut(BaseModel):
    id: int
    accession: str
    gene_name: str | None = None
    description: str | None = None
    is_decoy: bool = False
    protein_group: str | None = None
    peptide_count: int = 0
    match_count: int = 0
    best_q_value: float | None = None
    pg_max_lfq: float | None = None
    pg_q_value: float | None = None
    pg_quantity: float | None = None


class BuCoverageSegment(BaseModel):
    peptide_id: int
    sequence: str
    start: int | None = None
    end: int | None = None
    match_count: int = 0
    best_q_value: float | None = None
    is_ambiguous: bool = False
    occurrence_index: int = 0


class BuProteinPeptideRef(BaseModel):
    peptide_id: int
    sequence: str
    modified_sequence: str | None = None
    match_count: int = 0
    best_q_value: float | None = None
    best_match_id: int | None = None


class BuProteinDetailOut(BuProteinListItemOut):
    base_sequence: str | None = None
    coverage_mode: Literal["full", "partial", "list_only", "decoy"]
    coverage_percent: float | None = None
    coverage_segments: list[BuCoverageSegment] = Field(default_factory=list)
    peptides: list[BuProteinPeptideRef] = Field(default_factory=list)
    extra_metadata: dict[str, Any] = Field(default_factory=dict)


class BuPeptideListItemOut(BaseModel):
    id: int
    sequence: str
    length: int | None = None
    theoretical_mass: float | None = None
    missed_cleavages: int | None = None
    match_count: int = 0
    protein_count: int = 0
    best_q_value: float | None = None
    best_precursor_mz: float | None = None
    best_charge: int | None = None
    best_match_id: int | None = None
    protein_groups: str | None = None
    genes: str | None = None
    example_modified: str | None = None


class BuMatchListItemOut(BaseModel):
    id: int
    run_id: int
    run_name: str
    peptide_id: int
    sequence: str
    modified_sequence: str | None = None
    precursor_mz: float | None = None
    precursor_charge: int | None = None
    retention_time: float | None = None
    experimental_mass: float | None = None
    q_value: float | None = None
    score: float | None = None
    intensity: float | None = None
    is_decoy_match: bool = False
    scan_number: int
    protein_group: str | None = None
    protein_accessions: list[str] = Field(default_factory=list)
    genes: str | None = None
    search_engine: str | None = None


class BuRunDetail(BaseModel):
    run_id: int
    file_name: str
    raw_format: str | None = None
    file_path: str
    diann_run_name: str | None = None


class BuRtWindow(BaseModel):
    rt_start: float | None = None
    rt_stop: float | None = None
    rt_apex: float | None = None
    unit: str = "min"


class BuProteinMini(BaseModel):
    protein_id: int
    accession: str
    gene_name: str | None = None
    description: str | None = None


class BuMatchDetailOut(BuMatchListItemOut):
    spectrum_native_id: str | None = None
    ms_level: int = 2
    entity_type: Literal["PEPTIDE"] = "PEPTIDE"
    run: BuRunDetail
    rt_window: BuRtWindow
    proteins: list[BuProteinMini] = Field(default_factory=list)
    diann: dict[str, Any] = Field(default_factory=dict)
    spectrum_links: dict[str, str | None] = Field(default_factory=dict)
    extra_metadata: dict[str, Any] = Field(default_factory=dict)


class BuPeptideProteinRef(BaseModel):
    protein_id: int
    accession: str
    gene_name: str | None = None
    protein_group: str | None = None
    is_unique: bool = False


class BuPeptideMatchSummaryItem(BaseModel):
    id: int
    run_id: int
    run_name: str
    precursor_mz: float | None = None
    precursor_charge: int | None = None
    retention_time: float | None = None
    q_value: float | None = None
    intensity: float | None = None


class BuPeptideMatchesSummary(BaseModel):
    total: int = 0
    items: list[BuPeptideMatchSummaryItem] = Field(default_factory=list)


class BuPeptideDetailOut(BuPeptideListItemOut):
    proteins: list[BuPeptideProteinRef] = Field(default_factory=list)
    matches_summary: BuPeptideMatchesSummary = Field(default_factory=BuPeptideMatchesSummary)
    extra_metadata: dict[str, Any] = Field(default_factory=dict)


class BuSpectrumPrecursor(BaseModel):
    selected_mz: float | None = None
    charge: int | None = None
    isolation_target_mz: float | None = None
    isolation_lower: float | None = None
    isolation_upper: float | None = None


class BuMatchedIon(BaseModel):
    ion_type: Literal["b", "y"]
    position: int
    charge: int
    theo_mz: float
    exp_mz: float
    ppm: float
    intensity: float


class BuSpectrumMarker(BaseModel):
    mz: float
    label: str
    charge: int | None = None


class BuSpectrumV1(BaseModel):
    scan: int
    native_id: str | None = None
    ms_level: Literal[1, 2]
    rt_seconds: float
    rt_minutes: float
    mz: list[float] = Field(default_factory=list)
    intensity: list[float] = Field(default_factory=list)
    precursor: BuSpectrumPrecursor | None = None
    matched_ions: list[BuMatchedIon] = Field(default_factory=list)
    markers: list[BuSpectrumMarker] = Field(default_factory=list)


class BuXicTrace(BaseModel):
    label: str
    isotope_index: int
    target_mz: float
    intensity: list[float] = Field(default_factory=list)


class BuXicOut(BaseModel):
    rt: list[float] = Field(default_factory=list)
    intensity: list[float] = Field(default_factory=list)
    precursor_mz: float
    precursor_charge: int | None = None
    ppm: float
    rt_apex: float | None = None
    rt_start: float | None = None
    rt_stop: float | None = None
    traces: list[BuXicTrace] = Field(default_factory=list)
    unit_rt: Literal["min"] = "min"


class BuProductXicPoint(BaseModel):
    rt: float
    intensity: float
    scan: int


class BuProductXicOut(BaseModel):
    curve_type: Literal["PRODUCT_ION_XIC"] = "PRODUCT_ION_XIC"
    x_axis: Literal["rt"] = "rt"
    y_axis: Literal["intensity"] = "intensity"
    unit_rt: Literal["min"] = "min"
    product_mz: float
    ppm: float
    precursor_mz: float
    isolation_filter: bool = True
    points: list[BuProductXicPoint] = Field(default_factory=list)


class BuChromatogramOut(BaseModel):
    type: Literal["tic", "bpc"]
    unit_rt: Literal["min"] = "min"
    rt: list[float] = Field(default_factory=list)
    intensity: list[float] = Field(default_factory=list)
    downsampled: bool = False
    point_count_original: int = 0


class BuDiaWindowItem(BaseModel):
    mz: float
    width: float
    label: str


class BuDiaWindowsOut(BaseModel):
    run_id: int
    window_count: int
    windows: list[BuDiaWindowItem] = Field(default_factory=list)


class BuMobilitySliceOut(BaseModel):
    mz: list[float] = Field(default_factory=list)
    one_over_k0: list[float] = Field(default_factory=list)
    intensity: list[float] = Field(default_factory=list)
    frame_id: int | None = None
    rt_min: float | None = None
    unit_rt: Literal["min"] = "min"
