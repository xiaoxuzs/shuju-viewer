import { Navigate, Outlet, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { fetchDataset } from "@/api/client";
import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
import { PageLoading } from "@/components/common/page-loading";
import { isSpectraOnlyDataset } from "@/features/spectra-only/utils";
import { usePageTransitionReady } from "@/features/page-transition";

export function TdCutoffModeGate() {
  const { slug = "" } = useParams();
  const { data, isLoading, error } = useQuery({
    queryKey: ["dataset", slug],
    queryFn: () => fetchDataset(slug),
    enabled: !!slug,
  });
  usePageTransitionReady(!isLoading && Boolean(error || !data));

  if (isLoading) return <PageLoading />;
  if (error && !data) return <DataLoadError />;
  if (!data) return <DataEmptyState />;
  if (data?.analysis_mode === "BOTTOM_UP" || isSpectraOnlyDataset(data)) {
    return <Navigate to={`/datasets/${slug}`} replace />;
  }
  return <Outlet />;
}
