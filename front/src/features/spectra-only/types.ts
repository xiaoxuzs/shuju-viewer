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

export interface SpectraScanIndexOut {
  dataset_id: number;
  run_id: number;
  total: number;
  offset: number;
  limit: number;
  items: SpectraScanIndexItem[];
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
