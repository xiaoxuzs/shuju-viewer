/**
 * 与后端 Pydantic 输出对应的 TypeScript 类型。
 *
 * 注意区分：
 * - 列表/详情里常见的 `id`：多为 PostgreSQL 主键（如 `proteins.id`、`proteoforms.id`）。
 * - `sequence_id`、`proteoform_id`、`prsm_id`：TopPIC / 业务侧标识，用于展示与 URL 中的 PrSM 编号。
 */
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

/** 某一 FDR 或结果层级下的 cutoff（如 prsm / proteoform）。 */
export interface CutoffOut {
  id: number;
  kind: "prsm" | "proteoform" | string;
  label: string;
  protein_count: number;
  proteoform_count: number;
  prsm_count: number;
}

/** ``DELETE /datasets/{slug}`` 应答：库 / 磁盘各自的清理结果。 */
export interface DatasetDeletedOut {
  slug: string;
  deleted_db: boolean;
  deleted_disk: boolean;
  folder: string | null;
  folder_existed: boolean;
}

/** 已导入的数据集元数据及下属 cutoff 列表。 */
export interface DatasetOut {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  source_path: string;
  capabilities: Record<string, unknown>;
  analysis_mode: "TOP_DOWN" | "BOTTOM_UP" | string | null;
  dataset_mode: "top_down" | "bottom_up" | "spectra_only" | string;
  status: string | null;
  source_software: string | null;
  extra_metadata: Record<string, unknown> | null;
  runs: DatasetRunSummary[] | null;
  bu_runs: BuRunSummary[] | null;
  created_at: string;
  /** universal schema 没有 updated_at 列；后端总是返回 null。 */
  updated_at: string | null;
  cutoffs: CutoffOut[];
}

export interface DatasetRunSummary {
  run_id: number;
  run_name: string;
  raw_format: string | null;
  mzml_file_path: string | null;
  raw_path: string | null;
  metadata: Record<string, unknown>;
}

export interface BuRunSummary {
  run_id: number;
  file_name: string;
  raw_format: string | null;
  diann_run_name: string | null;
  match_count: number | null;
  has_im: boolean | null;
}

export type ImportUploadType =
  | "TD_RAW"
  | "TD_MZML"
  | "TD_TOPPIC_HTML"
  | "TD_PRSM_BUNDLE"
  | "TD_TOPPIC_NATIVE"
  | "BU_DIA_NN"
  | "BU_DIA_CLIP"
  | "DDA_RAW"
  // Legacy values remain readable for restored jobs created before the hierarchy change.
  | "RAW_ONLY"
  | "MZML_ONLY"
  | "TOPPIC"
  | "PRSM"
  | "DIA_NN"
  | "DIA_CLIP";

/** ``POST /imports`` JSON body: path-based import on the server. */
export interface ImportEnqueueIn {
  source_path: string;
  slug: string;
  name: string;
  description?: string | null;
  import_type?: ImportUploadType | null;
}

/** Background import job status from ``POST /imports`` / ``GET /imports/{job_id}``. */
export interface ImportJobOut {
  job_id: string;
  status: "queued" | "running" | "success" | "failed" | string;
  message: string | null;
  error: string | null;
  dataset_slug: string | null;
  /** Real progress 0..100. 100 only when status === 'success'. */
  progress: number;
  /** Phase code: queued | fingerprint | raw_conversion | init | proteins | matches | finalize | success | failed. */
  stage: string | null;
  /** Human-readable label for the current phase. */
  stage_label: string | null;
  /** Free-form detail line, e.g. "1234/4567 PrSM details". */
  stage_detail: string | null;
  created_at: string;
  updated_at: string;
}

export interface ImportJobCreatedOut {
  job_id: string;
  status: string;
}

/** ``POST /imports/pick-folder`` — native dialog on the API host (local). */
export interface ImportPickFolderOut {
  path: string | null;
  cancelled: boolean;
}

export type ImportUploadState = "CREATED" | "UPLOADING" | "READY" | "STARTED" | "FAILED";

export interface ImportUploadCreated {
  upload_id: string;
  import_type: ImportUploadType;
  state: ImportUploadState;
  created_at: string;
}

export interface ImportUploadStatus {
  upload_id: string;
  import_type: ImportUploadType;
  state: ImportUploadState;
  file_count: number;
  total_size_bytes: number;
  job_id: string | null;
  created_at: string;
  started_at: string | null;
}

export interface ImportUploadFileResult {
  upload_id: string;
  relative_path: string;
  size_bytes: number;
  state: ImportUploadState;
  total_size_bytes: number;
  file_count: number;
}

export interface ImportUploadStartParameters {
  slug: string;
  name: string;
  description?: string | null;
}

export type ImportUploadStartResult = ImportJobCreatedOut;

export interface ImportUploadError {
  code: string | null;
  message: string;
  status: number | null;
}

/** 蛋白质列表行（某 cutoff 下一条记录）。 */
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

/** Proteoform 列表行。 */
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

/** PrSM 列表行（摘要字段）。 */
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

/** 蛋白质详情：在列表行基础上附带 proteoform 子表。 */
export interface ProteinDetailOut extends ProteinListItemOut {
  proteoforms: ProteoformListItemOut[];
}

/** Proteoform 详情：附带该形式下 PrSM 列表。 */
export interface ProteoformDetailOut extends ProteoformListItemOut {
  protein_id: number;
  prsms: PrsmListItemOut[];
}

/**
 * PrSM 详情：含原始 `annotated_protein` / `ms_peaks` JSON，
 * 由前端 `parse.ts` 再解析为作图与表格结构。
 */
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
