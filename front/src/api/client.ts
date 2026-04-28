/**
 * 前端 HTTP 客户端：通过 Vite 代理访问后端 `/api/v1`，与 FastAPI 路由一一对应。
 * `slug` 为数据集标识；`cutoff` 为 `prsm` / `proteoform` 等 cutoff 种类。
 */
import axios from "axios";
import type {
  DatasetOut,
  Page,
  PrsmDetailOut,
  PrsmListItemOut,
  ProteinDetailOut,
  ProteinListItemOut,
  ProteoformDetailOut,
  ProteoformListItemOut,
} from "./types";

/** 已配置 baseURL 与超时的 axios 实例（开发环境由 vite 将 `/api` 转发到后端）。 */
export const api = axios.create({
  baseURL: "/api/v1",
  timeout: 30_000,
});

/** 列表接口通用查询参数，字段名与后端 Query 一致。 */
export interface ListParams {
  page?: number;
  page_size?: number;
  sort?: string;
  order?: "asc" | "desc";
  search?: string;
  protein_id?: number;
  proteoform_id?: number;
}

/** 获取全部已注册数据集（含各 cutoff 统计）。 */
export async function fetchDatasets(): Promise<DatasetOut[]> {
  const { data } = await api.get<DatasetOut[]>("/datasets");
  return data;
}

/** 按 slug 获取单个数据集详情。 */
export async function fetchDataset(slug: string): Promise<DatasetOut> {
  const { data } = await api.get<DatasetOut>(`/datasets/${slug}`);
  return data;
}

/** 分页列出某 cutoff 下的蛋白质；支持搜索与排序。 */
export async function fetchProteins(
  slug: string,
  cutoff: string,
  params: ListParams = {},
): Promise<Page<ProteinListItemOut>> {
  const { data } = await api.get<Page<ProteinListItemOut>>(
    `/datasets/${slug}/cutoffs/${cutoff}/proteins`,
    { params },
  );
  return data;
}

/** 蛋白质详情（含下属 proteoform 列表）；`proteinId` 为库表主键 `proteins.id`。 */
export async function fetchProtein(
  slug: string,
  cutoff: string,
  proteinId: number,
): Promise<ProteinDetailOut> {
  const { data } = await api.get<ProteinDetailOut>(
    `/datasets/${slug}/cutoffs/${cutoff}/proteins/${proteinId}`,
  );
  return data;
}

/** 分页列出某 cutoff 下的 proteoform。 */
export async function fetchProteoforms(
  slug: string,
  cutoff: string,
  params: ListParams = {},
): Promise<Page<ProteoformListItemOut>> {
  const { data } = await api.get<Page<ProteoformListItemOut>>(
    `/datasets/${slug}/cutoffs/${cutoff}/proteoforms`,
    { params },
  );
  return data;
}

/** Proteoform 详情（含 PrSM 列表）；`proteoformId` 为库表主键 `proteoforms.id`。 */
export async function fetchProteoform(
  slug: string,
  cutoff: string,
  proteoformId: number,
): Promise<ProteoformDetailOut> {
  const { data } = await api.get<ProteoformDetailOut>(
    `/datasets/${slug}/cutoffs/${cutoff}/proteoforms/${proteoformId}`,
  );
  return data;
}

/** 分页列出某 cutoff 下的 PrSM。 */
export async function fetchPrsms(
  slug: string,
  cutoff: string,
  params: ListParams = {},
): Promise<Page<PrsmListItemOut>> {
  const { data } = await api.get<Page<PrsmListItemOut>>(
    `/datasets/${slug}/cutoffs/${cutoff}/prsms`,
    { params },
  );
  return data;
}

/**
 * PrSM 详情。路径中的 `prsmId` 为 TopPIC 业务 id（`prsms.prsm_id`），非库表自增主键，
 * 与列表页、最佳 PrSM 链接一致。
 */
export async function fetchPrsm(
  slug: string,
  cutoff: string,
  prsmId: number,
): Promise<PrsmDetailOut> {
  const { data } = await api.get<PrsmDetailOut>(
    `/datasets/${slug}/cutoffs/${cutoff}/prsms/${prsmId}`,
  );
  return data;
}

/** 从磁盘缓存读取 MS1 谱原始 JSON（与 TopFD `spectrum{n}.js` 结构一致）。 */
export async function fetchMs1Spectrum(slug: string, specId: number): Promise<Record<string, unknown>> {
  const { data } = await api.get(`/datasets/${slug}/spectra/ms1/${specId}`);
  return data;
}

/** 从磁盘缓存读取 MS2 谱原始 JSON。 */
export async function fetchMs2Spectrum(slug: string, specId: number): Promise<Record<string, unknown>> {
  const { data } = await api.get(`/datasets/${slug}/spectra/ms2/${specId}`);
  return data;
}
