import { Navigate, useLocation, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { fetchDataset } from "@/api/client";
import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
import { PageLoading } from "@/components/common/page-loading";
import { DatasetPage } from "@/pages/DatasetPage";
import { BuDatasetLayout } from "@/features/bu/layout/BuDatasetLayout";
import { SpectraOnlyPage } from "@/features/spectra-only/pages/SpectraOnlyPage";
import { isSpectraOnlyDataset } from "@/features/spectra-only/utils";
import { usePageTransitionReady } from "@/features/page-transition";

export function DatasetModeGate() {
  const { slug = "" } = useParams();
  const location = useLocation();
  const { data, isLoading, error } = useQuery({
    queryKey: ["dataset", slug],
    queryFn: () => fetchDataset(slug),
    enabled: !!slug,
  });
  usePageTransitionReady(!isLoading && Boolean(error || !data));

  if (isLoading) return <PageLoading />;
  if (error && !data) return <DataLoadError />;
  if (!data) return <DataEmptyState />;

  const datasetHome = `/datasets/${slug}`;
  if (isSpectraOnlyDataset(data)) {
    if (location.pathname !== datasetHome) {
      return <Navigate to={datasetHome} replace />;
    }
    return <SpectraOnlyPage dataset={data} />;
  }

  if (data.analysis_mode === "BOTTOM_UP") {
    return <BuDatasetLayout dataset={data} />;
  }

  if (location.pathname !== datasetHome) {
    return <Navigate to={datasetHome} replace />;
  }
  return <DatasetPage />;
}
