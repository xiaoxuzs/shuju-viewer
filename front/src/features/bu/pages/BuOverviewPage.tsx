import { useOutletContext } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchBuOverview } from "@/features/bu/api/buClient";
import { BuSummaryCards } from "@/features/bu/components/BuSummaryCards";
import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";
import { formatCount } from "@/features/bu/utils";

export function BuOverviewPage() {
  const { dataset } = useOutletContext<BuDatasetContext>();
  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, "overview"],
    queryFn: () => fetchBuOverview(dataset.slug),
  });

  if (isLoading) return <Skeleton className="h-64" />;
  if (error) return <p className="text-destructive">{(error as Error).message}</p>;
  if (!data) return null;

  return (
    <div className="space-y-5">
      <BuSummaryCards overview={data} />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Runs</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {data.runs.map((run) => (
            <div key={run.run_id} className="rounded-md border border-border/60 bg-muted/30 p-3">
              <div className="break-all font-medium">{run.file_name}</div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <span>Format: {run.raw_format ?? "-"}</span>
                <span>Matches: {formatCount(run.match_count)}</span>
                <span className="col-span-2 break-all">DIA-NN: {run.diann_run_name ?? "-"}</span>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
