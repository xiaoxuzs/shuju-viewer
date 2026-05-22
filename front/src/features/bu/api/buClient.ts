import { api } from "@/api/client";
import type {
  BuListParams,
  BuMatchDetailOut,
  BuMatchPage,
  BuOverviewOut,
  BuPeptidePage,
  BuProteinPage,
} from "@/features/bu/types";

export async function fetchBuOverview(slug: string): Promise<BuOverviewOut> {
  const { data } = await api.get<BuOverviewOut>(`/datasets/${slug}/overview`);
  return data;
}

export async function fetchBuProteins(
  slug: string,
  params: BuListParams = {},
): Promise<BuProteinPage> {
  const { data } = await api.get<BuProteinPage>(`/datasets/${slug}/proteins`, { params });
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
