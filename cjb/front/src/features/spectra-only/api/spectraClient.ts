import { api } from "@/api/client";
import type {
  SpectraChromatogramOut,
  SpectraScanIndexOut,
  SpectraSpectrumOut,
} from "@/features/spectra-only/types";

export async function fetchSpectraChromatogram(
  datasetId: number,
  runId: number,
  type: "tic" | "bpc" = "tic",
): Promise<SpectraChromatogramOut> {
  const { data } = await api.get<SpectraChromatogramOut>(`/datasets/${datasetId}/runs/${runId}/chromatogram`, {
    params: { type },
  });
  return data;
}

export async function fetchSpectraScanIndex(
  datasetId: number,
  runId: number,
  params: { ms_level?: number; offset?: number; limit?: number } = {},
  signal?: AbortSignal,
): Promise<SpectraScanIndexOut> {
  const { data } = await api.get<SpectraScanIndexOut>(`/datasets/${datasetId}/runs/${runId}/scan-index`, {
    params,
    signal,
  });
  return data;
}

const SCAN_INDEX_PAGE_LIMIT = 2000;

export async function fetchSpectraFullScanIndex(
  datasetId: number,
  runId: number,
  signal?: AbortSignal,
): Promise<SpectraScanIndexOut> {
  const firstPage = await fetchSpectraScanIndex(
    datasetId,
    runId,
    { offset: 0, limit: SCAN_INDEX_PAGE_LIMIT },
    signal,
  );
  if (firstPage.items.length >= firstPage.total) {
    return {
      ...firstPage,
      limit: firstPage.items.length,
      scans: firstPage.items,
    };
  }

  const offsets: number[] = [];
  for (let offset = firstPage.items.length; offset < firstPage.total; offset += SCAN_INDEX_PAGE_LIMIT) {
    offsets.push(offset);
  }
  const pages = await Promise.all(
    offsets.map((offset) =>
      fetchSpectraScanIndex(datasetId, runId, { offset, limit: SCAN_INDEX_PAGE_LIMIT }, signal),
    ),
  );
  const items = firstPage.items.concat(pages.flatMap((page) => page.items));
  return {
    ...firstPage,
    limit: items.length,
    items,
    scans: items,
  };
}

export async function fetchSpectraSpectrum(
  datasetId: number,
  runId: number,
  scanNumber: number,
): Promise<SpectraSpectrumOut> {
  const { data } = await api.get<SpectraSpectrumOut>(
    `/datasets/${datasetId}/runs/${runId}/spectra/${scanNumber}`,
  );
  return data;
}
