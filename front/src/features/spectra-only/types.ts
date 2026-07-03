export interface SpectraChromatogramOut {
  type: "tic" | "bpc";
  unit_rt: "min";
  rt: number[];
  intensity: number[];
  downsampled: boolean;
  point_count_original: number;
}

export interface SpectraScanIndexItem {
  scan_number: number;
  native_id: string;
  ms_level: number;
  retention_time: number;
  tic: number;
  bpc: number;
  precursor_mz: number | null;
  isolation_target_mz: number | null;
  isolation_lower_mz: number | null;
  isolation_upper_mz: number | null;
}

export interface SpectraRunSummary {
  total_scans: number;
  ms1_count: number;
  ms2_count: number;
  other_count: number;
  ms_level_counts: Record<string, number>;
  rt_min: number | null;
  rt_max: number | null;
  scan_min: number | null;
  scan_max: number | null;
  max_tic: number | null;
  max_bpc: number | null;
  ms2_fraction: number | null;
  precursor_linked_ms2_count: number;
}

export interface SpectraScanIndexOut {
  dataset_id: number;
  run_id: number;
  total: number;
  offset: number;
  limit: number;
  items: SpectraScanIndexItem[];
  scans?: SpectraScanIndexItem[];
  summary: SpectraRunSummary;
}

export interface SpectraSpectrumOut {
  dataset_id: number;
  run_id: number;
  scan: number;
  native_id: string | null;
  ms_level: number;
  rt_seconds: number;
  mz: number[];
  intensity: number[];
  precursor: Record<string, unknown> | null;
}
