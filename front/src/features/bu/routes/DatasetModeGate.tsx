import { Navigate, useLocation, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { fetchDataset, fetchDatasetCapabilityReport } from "@/api/client";
import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
import { PageLoading } from "@/components/common/page-loading";
import { DatasetPage } from "@/pages/DatasetPage";
import { BuDatasetLayout } from "@/features/bu/layout/BuDatasetLayout";
import { DatasetCapabilityProvider } from "@/features/dataset-capabilities/DatasetCapabilityProvider";
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
  const capabilityQuery = useQuery({
    queryKey: ["dataset-capability-report", slug, data?.revision_id ?? "legacy"],
    queryFn: () => fetchDatasetCapabilityReport(slug),
    enabled: !!slug && !!data,
    retry: false,
  });
  const gateLoading = isLoading || capabilityQuery.isLoading;
  const capabilityUnavailable = Boolean(capabilityQuery.error && !capabilityQuery.data);
  usePageTransitionReady(!gateLoading && Boolean(!data || capabilityUnavailable));

  if (gateLoading) return <PageLoading />;
  if (error && !data) return <DataLoadError />;
  if (capabilityUnavailable) {
    return (
      <DataLoadError message="Viewer could not load the dataset capability report. The data has not been treated as fully supported." />
    );
  }
  if (!data) return <DataEmptyState />;

  const datasetHome = `/datasets/${slug}`;
  let content: ReactNode;
  if (isSpectraOnlyDataset(data)) {
    if (location.pathname !== datasetHome) {
      content = <Navigate to={datasetHome} replace />;
    } else {
      content = <SpectraOnlyPage dataset={data} />;
    }
  } else if (data.analysis_mode === "BOTTOM_UP") {
    content = <BuDatasetLayout dataset={data} />;
  } else if (location.pathname !== datasetHome) {
    content = <Navigate to={datasetHome} replace />;
  } else {
    content = <DatasetPage />;
  }

  return (
    <DatasetCapabilityProvider report={capabilityQuery.data ?? null}>
      {content}
    </DatasetCapabilityProvider>
  );
}
