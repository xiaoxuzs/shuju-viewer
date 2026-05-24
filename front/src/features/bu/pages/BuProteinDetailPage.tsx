import { useOutletContext, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Skeleton } from "@/components/ui/skeleton";
import { fetchBuProtein } from "@/features/bu/api/buClient";
import { BuPeptideLinksTable } from "@/features/bu/components/protein-detail/BuPeptideLinksTable";
import { BuProteinHeader } from "@/features/bu/components/protein-detail/BuProteinHeader";
import { SequenceCoverage } from "@/features/bu/components/sequence/SequenceCoverage";
import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";

export function BuProteinDetailPage() {
  const { dataset } = useOutletContext<BuDatasetContext>();
  const { proteinId = "" } = useParams();
  const parsedProteinId = Number(proteinId);
  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, "protein", parsedProteinId],
    queryFn: () => fetchBuProtein(dataset.slug, parsedProteinId),
    enabled: Number.isFinite(parsedProteinId),
  });

  if (!Number.isFinite(parsedProteinId)) return <p className="text-destructive">Invalid protein id.</p>;
  if (isLoading) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">正在获取蛋白序列…</p>
        <Skeleton className="h-40" />
        <Skeleton className="h-64" />
        <Skeleton className="h-72" />
      </div>
    );
  }
  if (error) return <p className="text-destructive">{(error as Error).message}</p>;
  if (!data) return null;

  return (
    <div className="space-y-4">
      <BuProteinHeader protein={data} />
      <SequenceCoverage protein={data} />
      <BuPeptideLinksTable slug={dataset.slug} protein={data} />
    </div>
  );
}
