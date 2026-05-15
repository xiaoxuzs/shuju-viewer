import { api } from "@/api/client";
import type { Lcms3DMap, Lcms3DParams } from "./types";

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
