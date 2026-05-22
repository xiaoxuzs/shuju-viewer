import { useOutletContext, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchBuMatch } from "@/features/bu/api/buClient";
import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";
import { formatDecimal } from "@/features/bu/utils";

export function BuMatchDetailPage() {
  const { dataset } = useOutletContext<BuDatasetContext>();
  const { matchId = "" } = useParams();
  const parsedMatchId = Number(matchId);
  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, "matches", parsedMatchId],
    queryFn: () => fetchBuMatch(dataset.slug, parsedMatchId),
    enabled: Number.isFinite(parsedMatchId),
  });

  if (isLoading) return <Skeleton className="h-64" />;
  if (error) return <p className="text-destructive">{(error as Error).message}</p>;
  if (!data) return null;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>{data.modified_sequence ?? data.sequence}</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <Field label="Run" value={data.run.file_name} />
          <Field label="Charge" value={data.precursor_charge ? `${data.precursor_charge}+` : "-"} />
          <Field label="m/z" value={formatDecimal(data.precursor_mz)} />
          <Field label="Q.Value" value={formatDecimal(data.q_value)} />
          <Field label="RT apex" value={formatDecimal(data.rt_window.rt_apex)} />
          <Field label="Scan" value={String(data.scan_number)} />
          <Field label="Proteins" value={data.proteins.map((p) => p.accession).join(", ") || "-"} />
          <Field label="Spectrum" value="即将支持" />
        </CardContent>
      </Card>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/60 bg-muted/30 p-3">
      <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 break-words font-medium">{value}</div>
    </div>
  );
}
