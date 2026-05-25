import type { Page } from "@/api/types";

export interface BuOverviewCounts {
  matches: number;
  peptides: number;
  proteins: number;
  protein_groups: number;
  runs: number;
  decoy_matches: number;
}

export interface BuQcBlock {
  by_run: Record<string, unknown>[];
  aggregated: Record<string, unknown>;
}

export interface BuRunSummary {
  run_id: number;
  file_name: string;
  raw_format: string | null;
  diann_run_name: string | null;
  match_count: number | null;
  has_im: boolean | null;
}

export interface BuOverviewOut {
  dataset_id: number;
  slug: string;
  name: string;
  analysis_mode: "BOTTOM_UP";
  source_software: string | null;
  status: string;
  source_root: string;
  q_value_cutoff: number | null;
  counts: BuOverviewCounts;
  qc: BuQcBlock;
  runs: BuRunSummary[];
  capabilities: Record<string, unknown>;
  import_stats: Record<string, unknown>;
  created_at: string;
}

export interface BuProteinListItemOut {
  id: number;
  accession: string;
  gene_name: string | null;
  description: string | null;
  is_decoy: boolean;
  protein_group: string | null;
  peptide_count: number;
  match_count: number;
  best_q_value: number | null;
  pg_max_lfq: number | null;
  pg_q_value: number | null;
  pg_quantity: number | null;
}

export type BuCoverageMode = "full" | "partial" | "list_only" | "decoy";

export interface BuCoverageSegment {
  peptide_id: number;
  sequence: string;
  start: number | null;
  end: number | null;
  match_count: number;
  best_q_value: number | null;
  is_ambiguous: boolean;
  occurrence_index: number;
}

export interface BuProteinPeptideRef {
  peptide_id: number;
  sequence: string;
  modified_sequence: string | null;
  match_count: number;
  best_q_value: number | null;
  best_match_id: number | null;
}

export interface BuProteinDetailOut extends BuProteinListItemOut {
  base_sequence: string | null;
  coverage_mode: BuCoverageMode;
  coverage_percent: number | null;
  coverage_segments: BuCoverageSegment[];
  peptides: BuProteinPeptideRef[];
  extra_metadata: Record<string, unknown>;
}

export interface BuPeptideListItemOut {
  id: number;
  sequence: string;
  length: number | null;
  theoretical_mass: number | null;
  missed_cleavages: number | null;
  match_count: number;
  protein_count: number;
  best_q_value: number | null;
  best_precursor_mz: number | null;
  best_charge: number | null;
  best_match_id: number | null;
  protein_groups: string | null;
  genes: string | null;
  example_modified: string | null;
}

export interface BuMatchListItemOut {
  id: number;
  run_id: number;
  run_name: string;
  peptide_id: number;
  sequence: string;
  modified_sequence: string | null;
  precursor_mz: number | null;
  precursor_charge: number | null;
  retention_time: number | null;
  experimental_mass: number | null;
  q_value: number | null;
  score: number | null;
  intensity: number | null;
  is_decoy_match: boolean;
  scan_number: number;
  protein_group: string | null;
  protein_accessions: string[];
  genes: string | null;
  search_engine: string | null;
}

export interface BuRunDetail {
  run_id: number;
  file_name: string;
  raw_format: string | null;
  file_path: string;
  diann_run_name: string | null;
}

export interface BuRtWindow {
  rt_start: number | null;
  rt_stop: number | null;
  rt_apex: number | null;
  unit: string;
}

export interface BuProteinMini {
  protein_id: number;
  accession: string;
  gene_name: string | null;
  description: string | null;
}

export interface BuMatchDetailOut extends BuMatchListItemOut {
  spectrum_native_id: string | null;
  ms_level: number;
  entity_type: "PEPTIDE";
  run: BuRunDetail;
  rt_window: BuRtWindow;
  proteins: BuProteinMini[];
  diann: Record<string, unknown>;
  spectrum_links: Record<string, string | null>;
  extra_metadata: Record<string, unknown>;
}

export interface BuSpectrumPrecursor {
  selected_mz: number | null;
  charge: number | null;
  isolation_target_mz: number | null;
  isolation_lower: number | null;
  isolation_upper: number | null;
}

export interface BuMatchedIon {
  ion_type: "b" | "y";
  position: number;
  charge: number;
  theo_mz: number;
  exp_mz: number;
  ppm: number;
  intensity: number;
}

export interface BuSpectrumMarker {
  mz: number;
  label: string;
  charge: number | null;
}

export interface BuSpectrumV1 {
  scan: number;
  native_id: string | null;
  ms_level: 1 | 2;
  rt_seconds: number;
  rt_minutes: number;
  mz: number[];
  intensity: number[];
  precursor: BuSpectrumPrecursor | null;
  matched_ions: BuMatchedIon[];
  markers: BuSpectrumMarker[];
}

export interface BuXicOut {
  rt: number[];
  intensity: number[];
  precursor_mz: number;
  ppm: number;
  rt_apex: number | null;
  rt_start: number | null;
  rt_stop: number | null;
  unit_rt: "min";
}

export interface BuChromatogramOut {
  type: "tic" | "bpc";
  unit_rt: "min";
  rt: number[];
  intensity: number[];
  downsampled: boolean;
  point_count_original: number;
}

export interface BuDiaWindowItem {
  mz: number;
  width: number;
  label: string;
}

export interface BuDiaWindowsOut {
  run_id: number;
  window_count: number;
  windows: BuDiaWindowItem[];
}

export interface BuMobilitySliceOut {
  mz: number[];
  one_over_k0: number[];
  intensity: number[];
  frame_id: number | null;
  rt_min: number | null;
  unit_rt: "min";
}

export interface BuListParams {
  page?: number;
  page_size?: number;
  search?: string;
  sort?: string;
  order?: "asc" | "desc";
  q_max?: number;
  run_id?: number;
  peptide_id?: number;
  protein_id?: number;
  charge?: number;
  decoy?: boolean;
}

export type BuProteinPage = Page<BuProteinListItemOut>;
export type BuPeptidePage = Page<BuPeptideListItemOut>;
export type BuMatchPage = Page<BuMatchListItemOut>;
