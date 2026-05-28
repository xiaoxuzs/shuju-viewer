/** HTTP client for backend `/api/v1` (proxied by Vite in development). */
import axios from "axios";
import type {
  DatasetDeletedOut,
  DatasetOut,
  ImportEnqueueIn,
  ImportJobCreatedOut,
  ImportJobOut,
  ImportPickFolderOut,
  Page,
  PrsmDetailOut,
  PrsmListItemOut,
  ProteinDetailOut,
  ProteinListItemOut,
  ProteoformDetailOut,
  ProteoformListItemOut,
} from "./types";

export const api = axios.create({
  baseURL: "/api/v1",
  timeout: 30_000,
});

export interface ListParams {
  page?: number;
  page_size?: number;
  sort?: string;
  order?: "asc" | "desc";
  search?: string;
  protein_id?: number;
  proteoform_id?: number;
}

export async function fetchDatasets(): Promise<DatasetOut[]> {
  const { data } = await api.get<DatasetOut[]>("/datasets");
  return data;
}

export async function enqueueImport(body: ImportEnqueueIn): Promise<ImportJobCreatedOut> {
  const { data } = await api.post<ImportJobCreatedOut>("/imports", body, {
    timeout: 600_000,
    headers: { "Content-Type": "application/json" },
  });
  return data;
}

export async function pickImportFolder(): Promise<ImportPickFolderOut> {
  const { data } = await api.post<ImportPickFolderOut>(
    "/imports/pick-folder",
    {},
    { timeout: 0, headers: { "Content-Type": "application/json" } },
  );
  return data;
}

export async function fetchImportJob(jobId: string): Promise<ImportJobOut> {
  const { data } = await api.get<ImportJobOut>(`/imports/${jobId}`);
  return data;
}

export async function fetchDataset(slug: string): Promise<DatasetOut> {
  const { data } = await api.get<DatasetOut>(`/datasets/${slug}`);
  return data;
}

export async function deleteDataset(slug: string): Promise<DatasetDeletedOut> {
  const { data } = await api.delete<DatasetDeletedOut>(`/datasets/${slug}`);
  return data;
}

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

export async function fetchMs1Spectrum(slug: string, specId: number): Promise<Record<string, unknown>> {
  const { data } = await api.get(`/datasets/${slug}/spectra/ms1/${specId}`);
  return data;
}

export async function fetchMs2Spectrum(slug: string, specId: number): Promise<Record<string, unknown>> {
  const { data } = await api.get(`/datasets/${slug}/spectra/ms2/${specId}`);
  return data;
}

export async function fetchMzmlSpectrum(
  datasetId: number,
  runId: number,
  scanNumber: number,
): Promise<Record<string, unknown>> {
  const { data } = await api.get(`/datasets/${datasetId}/runs/${runId}/spectra/${scanNumber}`);
  return data;
}
