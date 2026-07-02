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
): Promise<SpectraScanIndexOut> {
  const { data } = await api.get<SpectraScanIndexOut>(`/datasets/${datasetId}/runs/${runId}/scan-index`, {
    params,
  });
  return data;
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
