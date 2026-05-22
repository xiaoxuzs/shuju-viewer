import { Navigate, Outlet, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { fetchDataset } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";

export function TdCutoffModeGate() {
  const { slug = "" } = useParams();
  const { data, isLoading, error } = useQuery({
    queryKey: ["dataset", slug],
    queryFn: () => fetchDataset(slug),
    enabled: !!slug,
  });

  if (isLoading) return <Skeleton className="h-64" />;
  if (error) return <p className="text-destructive">{(error as Error).message}</p>;
  if (data?.analysis_mode === "BOTTOM_UP") {
    return <Navigate to={`/datasets/${slug}`} replace />;
  }
  return <Outlet />;
}
