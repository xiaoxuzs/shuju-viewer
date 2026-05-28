/** TypeScript types aligned with backend Pydantic outputs. */
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface CutoffOut {
  id: number;
  kind: "prsm" | "proteoform" | string;
  label: string;
  protein_count: number;
  proteoform_count: number;
  prsm_count: number;
}

export interface DatasetDeletedOut {
  slug: string;
  deleted_db: boolean;
  deleted_disk: boolean;
  folder: string | null;
  folder_existed: boolean;
}

export interface DatasetOut {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  source_path: string;
  capabilities: Record<string, unknown>;
  analysis_mode: "TOP_DOWN" | "BOTTOM_UP" | string | null;
  status: string | null;
  source_software: string | null;
  extra_metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string | null;
  cutoffs: CutoffOut[];
}

export interface ImportEnqueueIn {
  source_path: string;
  slug: string;
  name: string;
  description?: string | null;
}

export interface ImportJobOut {
  job_id: string;
  status: "queued" | "running" | "success" | "failed" | string;
  message: string | null;
  error: string | null;
  dataset_slug: string | null;
  progress: number;
  stage: string | null;
  stage_label: string | null;
  stage_detail: string | null;
  created_at: string;
  updated_at: string;
}

export interface ImportJobCreatedOut {
  job_id: string;
  status: string;
}

export interface ImportPickFolderOut {
  path: string | null;
  cancelled: boolean;
}

export interface ProteinListItemOut {
  id: number;
  sequence_id: number;
  sequence_name: string;
  sequence_description: string | null;
  compatible_proteoform_number: number;
  prsm_number: number;
  best_prsm_id: number | null;
  best_prsm_e_value: number | null;
}

export interface ProteoformListItemOut {
  id: number;
  proteoform_id: number;
  sequence_id: number;
  sequence_name: string;
  proteoform_mass: number | null;
  prsm_number: number;
  best_prsm_id: number | null;
  best_prsm_e_value: number | null;
  n_acetylation: number | null;
  unexpected_shift_number: number | null;
}

export interface PrsmListItemOut {
  id: number;
  prsm_id: number;
  sequence_id: number;
  p_value: number | null;
  e_value: number | null;
  fdr: number | null;
  matched_fragment_number: number | null;
  matched_peak_number: number | null;
  precursor_mono_mass: number | null;
  precursor_charge: number | null;
  precursor_mz: number | null;
  proteoform_mass: number | null;
  ms1_scans: string | null;
  ms2_scans: string | null;
}

export interface ProteinDetailOut extends ProteinListItemOut {
  proteoforms: ProteoformListItemOut[];
}

export interface ProteoformDetailOut extends ProteoformListItemOut {
  protein_id: number;
  prsms: PrsmListItemOut[];
}

export interface PrsmDetailOut extends PrsmListItemOut {
  dataset_id: number;
  run_id: number;
  proteoform_id: number;
  spectrum_file_name: string | null;
  ms1_ids: string | null;
  ms2_ids: string | null;
  feature_inte: number | null;
  ms_header: Record<string, unknown> | null;
  annotated_protein: Record<string, unknown> | null;
  ms_peaks: Record<string, unknown> | null;
}
