import { api } from "@/api/client";
import type {
  BuListParams,
  BuChromatogramOut,
  BuDiaWindowsOut,
  BuMatchDetailOut,
  BuMobilitySliceOut,
  BuMatchPage,
  BuOverviewOut,
  BuPeptidePage,
  BuProteinDetailOut,
  BuProteinPage,
  BuRtMzHeatmapOut,
  BuSpectrumV1,
  BuXicOut,
} from "@/features/bu/types";

export async function fetchBuOverview(slug: string): Promise<BuOverviewOut> {
  const { data } = await api.get<BuOverviewOut>(`/datasets/${slug}/overview`);
  return data;
}

export async function fetchBuRtMzHeatmap(
  slug: string,
  params: {
    run_id?: number;
    q_max?: number;
    bins_rt?: number;
    bins_mz?: number;
    decoy?: boolean;
  } = {},
): Promise<BuRtMzHeatmapOut> {
  const { data } = await api.get<BuRtMzHeatmapOut>(`/datasets/${slug}/overview/rt-mz`, { params });
  return data;
}

export async function fetchBuProteins(
  slug: string,
  params: BuListParams = {},
): Promise<BuProteinPage> {
  const { data } = await api.get<BuProteinPage>(`/datasets/${slug}/proteins`, { params });
  return data;
}

export async function fetchBuProtein(slug: string, proteinId: number): Promise<BuProteinDetailOut> {
  const { data } = await api.get<BuProteinDetailOut>(`/datasets/${slug}/proteins/${proteinId}`);
  return data;
}

export async function fetchBuPeptides(
  slug: string,
  params: BuListParams = {},
): Promise<BuPeptidePage> {
  const { data } = await api.get<BuPeptidePage>(`/datasets/${slug}/peptides`, { params });
  return data;
}

export async function fetchBuMatches(
  slug: string,
  params: BuListParams = {},
): Promise<BuMatchPage> {
  const { data } = await api.get<BuMatchPage>(`/datasets/${slug}/matches`, { params });
  return data;
}

export async function fetchBuMatch(slug: string, matchId: number): Promise<BuMatchDetailOut> {
  const { data } = await api.get<BuMatchDetailOut>(`/datasets/${slug}/matches/${matchId}`);
  return data;
}

export async function fetchBuMatchMs2(
  slug: string,
  matchId: number,
  ppm = 20,
): Promise<BuSpectrumV1> {
  const { data } = await api.get<BuSpectrumV1>(`/datasets/${slug}/matches/${matchId}/spectrum/ms2`, {
    params: { ppm },
  });
  return data;
}

export async function fetchBuMatchMs1(slug: string, matchId: number): Promise<BuSpectrumV1> {
  const { data } = await api.get<BuSpectrumV1>(`/datasets/${slug}/matches/${matchId}/spectrum/ms1`);
  return data;
}

export async function fetchBuMatchXic(
  slug: string,
  matchId: number,
  ppm = 10,
): Promise<BuXicOut> {
  const { data } = await api.get<BuXicOut>(`/datasets/${slug}/matches/${matchId}/xic`, {
    params: { ppm },
  });
  return data;
}

export async function fetchBuMatchMobilitySlice(slug: string, matchId: number): Promise<BuMobilitySliceOut> {
  const { data } = await api.get<BuMobilitySliceOut>(`/datasets/${slug}/matches/${matchId}/mobility-slice`);
  return data;
}

export async function fetchBuRunChromatogram(
  slug: string,
  runId: number,
  type: "tic" | "bpc" = "tic",
): Promise<BuChromatogramOut> {
  const { data } = await api.get<BuChromatogramOut>(`/datasets/${slug}/runs/${runId}/chromatogram`, {
    params: { type },
  });
  return data;
}

export async function fetchBuRunDiaWindows(slug: string, runId: number): Promise<BuDiaWindowsOut> {
  const { data } = await api.get<BuDiaWindowsOut>(`/datasets/${slug}/runs/${runId}/dia-windows`);
  return data;
}
