import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatNumber } from "@/lib/utils";
import { fetchLcms3DMap } from "./api";
import { ThreeLcmsScene } from "./ThreeLcmsScene";
import type { Lcms3DParams } from "./types";

interface Props {
  datasetId: number;
  runId: number;
  spectraSource: string;
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
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = rootRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "320px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const params = useMemo<Lcms3DParams>(() => {
    const out: Lcms3DParams = {
      ms_level: 1,
      rt_window_seconds: 300,
      mz_window: 90,
      frame_radius: spectraSource === "topfd_js" ? 18 : 28,
      rt_bins: 108,
      mz_bins: 180,
      max_points: 50_000,
    };
    if (isFiniteNumber(ms1Scan)) out.center_scan = ms1Scan;
    if (isFiniteNumber(ms1SpecId)) out.center_spec_id = ms1SpecId;
    if (isFiniteNumber(precursorMz)) out.precursor_mz = precursorMz;
    return out;
  }, [ms1Scan, ms1SpecId, precursorMz, spectraSource]);

  const hasLocator =
    spectraSource === "mzml_memory"
      ? isFiniteNumber(ms1Scan)
      : isFiniteNumber(ms1SpecId);

  const query = useQuery({
    queryKey: ["lcms-3d", datasetId, runId, spectraSource, params],
    queryFn: () => fetchLcms3DMap(datasetId, runId, params),
    enabled: visible && datasetId > 0 && runId > 0 && hasLocator,
    staleTime: 5 * 60_000,
  });

  const data = query.data;
  const pointCount = data?.meta.returnedPointCount ?? 0;

  return (
    <Card ref={rootRef} className="mb-6">
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
        {!hasLocator ? (
          <p className="text-sm text-muted-foreground">LC-MS locator is unavailable for this PrSM.</p>
        ) : query.isLoading || !visible ? (
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

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
