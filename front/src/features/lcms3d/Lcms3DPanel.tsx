import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatNumber } from "@/lib/utils";
import {
  LCMS3D_STALE_TIME_MS,
  buildLcms3DParams,
  fetchLcms3DMap,
  hasLcmsLocator,
  lcms3DQueryKey,
} from "./api";
import { ThreeLcmsScene } from "./ThreeLcmsScene";

interface Props {
  datasetId: number;
  runId: number;
  spectraSource: string | null;
  ms1Scan: number | null;
  ms1SpecId: number | null;
  precursorMz: number | null;
}

export function Lcms3DPanel({
  datasetId,
  runId,
  spectraSource,
  ms1Scan,
  ms1SpecId,
  precursorMz,
}: Props) {
  const params = useMemo(
    () => buildLcms3DParams({ spectraSource, ms1Scan, ms1SpecId, precursorMz }),
    [ms1Scan, ms1SpecId, precursorMz, spectraSource],
  );
  const sourceReady = typeof spectraSource === "string" && spectraSource.length > 0;
  const hasLocator = hasLcmsLocator({ spectraSource, ms1Scan, ms1SpecId, precursorMz });

  const query = useQuery({
    queryKey: lcms3DQueryKey(datasetId, runId, spectraSource ?? "pending", params),
    queryFn: () => fetchLcms3DMap(datasetId, runId, params),
    enabled: sourceReady && datasetId > 0 && runId > 0 && hasLocator,
    staleTime: LCMS3D_STALE_TIME_MS,
    gcTime: 30 * 60_000,
    refetchOnMount: false,
  });

  const data = query.data;
  const pointCount = data?.meta.returnedPointCount ?? 0;

  return (
    <Card className="mb-6">
      <CardHeader className="flex flex-row items-baseline justify-between gap-3">
        <div>
          <CardTitle className="text-base">LC-MS 3D map</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            RT x m/z x intensity around the current precursor region
          </p>
        </div>
        {data && (
          <span className="font-mono text-xs text-muted-foreground">
            {data.source} · {data.meta.frameCount} frames · {pointCount.toLocaleString()} points
          </span>
        )}
      </CardHeader>
      <CardContent>
        {!sourceReady ? (
          <Skeleton className="h-[420px] w-full" />
        ) : !hasLocator ? (
          <p className="text-sm text-muted-foreground">LC-MS locator is unavailable for this PrSM.</p>
        ) : query.isLoading ? (
          <Skeleton className="h-[420px] w-full" />
        ) : query.isError ? (
          <div className="text-sm text-destructive">{(query.error as Error).message}</div>
        ) : !data || pointCount === 0 ? (
          <p className="text-sm text-muted-foreground">No LC-MS points found near this PrSM.</p>
        ) : (
          <div className="space-y-2">
            <ThreeLcmsScene data={data} height={420} />
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>RT {formatNumber(data.axes.x.min, 1)}-{formatNumber(data.axes.x.max, 1)} s</span>
              <span>m/z {formatNumber(data.axes.y.min, 4)}-{formatNumber(data.axes.y.max, 4)}</span>
              <span>base {formatNumber(data.axes.z.max, 2)}</span>
              {data.meta.mzWindowFallback && <span>full local m/z range</span>}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
