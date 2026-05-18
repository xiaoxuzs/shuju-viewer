import { api } from "@/api/client";
import type { Lcms3DMap, Lcms3DParams } from "./types";

export const LCMS3D_STALE_TIME_MS = 10 * 60_000;

export interface Lcms3DLocator {
  spectraSource: string | null | undefined;
  ms1Scan: number | null | undefined;
  ms1SpecId: number | null | undefined;
  precursorMz: number | null | undefined;
}

export function buildLcms3DParams(locator: Lcms3DLocator): Lcms3DParams {
  const out: Lcms3DParams = {
    ms_level: 1,
    rt_window_seconds: 300,
    mz_window: 90,
    frame_radius: locator.spectraSource === "topfd_js" ? 18 : 28,
    rt_bins: 108,
    mz_bins: 180,
    max_points: 50_000,
  };
  if (isFiniteNumber(locator.ms1Scan)) out.center_scan = locator.ms1Scan;
  if (isFiniteNumber(locator.ms1SpecId)) out.center_spec_id = locator.ms1SpecId;
  if (isFiniteNumber(locator.precursorMz)) out.precursor_mz = locator.precursorMz;
  return out;
}

export function hasLcmsLocator(locator: Lcms3DLocator): boolean {
  if (locator.spectraSource === "mzml_memory") {
    return isFiniteNumber(locator.ms1Scan);
  }
  if (locator.spectraSource === "topfd_js") {
    return isFiniteNumber(locator.ms1SpecId);
  }
  return false;
}

export function lcms3DQueryKey(
  datasetId: number,
  runId: number,
  spectraSource: string,
  params: Lcms3DParams,
) {
  return ["lcms-3d", datasetId, runId, spectraSource, params] as const;
}

export async function fetchLcms3DMap(
  datasetId: number,
  runId: number,
  params: Lcms3DParams,
): Promise<Lcms3DMap> {
  const { data } = await api.get<Lcms3DMap>(
    `/datasets/${datasetId}/runs/${runId}/lcms-3d`,
    { params, timeout: 120_000 },
  );
  return data;
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
