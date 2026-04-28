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

/** 已导入的数据集元数据及下属 cutoff 列表。 */
export interface DatasetOut {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  source_path: string;
  created_at: string;
  updated_at: string;
  cutoffs: CutoffOut[];
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
  proteoform_id: number;
  spectrum_file_name: string | null;
  ms1_ids: string | null;
  ms2_ids: string | null;
  feature_inte: number | null;
  ms_header: Record<string, unknown> | null;
  annotated_protein: Record<string, unknown> | null;
  ms_peaks: Record<string, unknown> | null;
}
