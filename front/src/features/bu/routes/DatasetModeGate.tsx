import { Navigate, useLocation, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { fetchDataset } from "@/api/client";
import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
import { PageLoading } from "@/components/common/page-loading";
import { DatasetPage } from "@/pages/DatasetPage";
import { BuDatasetLayout } from "@/features/bu/layout/BuDatasetLayout";

export function DatasetModeGate() {
  const { slug = "" } = useParams();
  const location = useLocation();
  const { data, isLoading, error } = useQuery({
    queryKey: ["dataset", slug],
    queryFn: () => fetchDataset(slug),
    enabled: !!slug,
  });

  if (isLoading) return <PageLoading />;
  if (error && !data) return <DataLoadError />;
  if (!data) return <DataEmptyState />;

  const datasetHome = `/datasets/${slug}`;
  if (data.analysis_mode === "BOTTOM_UP") {
    return <BuDatasetLayout dataset={data} />;
  }

  if (location.pathname !== datasetHome) {
    return <Navigate to={datasetHome} replace />;
  }
  return <DatasetPage />;
}
