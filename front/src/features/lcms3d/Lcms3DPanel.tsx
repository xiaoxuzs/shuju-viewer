import { useMemo } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/lib/utils";
import type { Peak } from "./types";
import { ThreeLcmsScene } from "./ThreeLcmsScene";

interface Props {
  peaks: Peak[] | null | undefined;
  scan: number | null;
  retentionTimeSeconds: number | null;
}

export function Lcms3DPanel({ peaks, scan, retentionTimeSeconds }: Props) {
  const cleanPeaks = useMemo<Peak[]>(() => {
    if (!peaks || peaks.length === 0) return [];
    return peaks.filter(
      (p) => Number.isFinite(p.mz) && Number.isFinite(p.intensity) && p.intensity > 0,
    );
  }, [peaks]);

  const rtMin = retentionTimeSeconds != null && Number.isFinite(retentionTimeSeconds)
    ? retentionTimeSeconds / 60
    : null;

  const subtitle = useMemo(() => {
    const parts: string[] = [];
    if (scan != null && Number.isFinite(scan)) parts.push(`Scan ${scan}`);
    if (rtMin != null) parts.push(`RT ${formatNumber(rtMin, 2)} min`);
    parts.push(`${cleanPeaks.length.toLocaleString()} peaks`);
    return parts.join(" · ");
  }, [scan, rtMin, cleanPeaks.length]);

  return (
    <Card className="mb-6">
      <CardHeader className="flex flex-row items-baseline justify-between gap-3">
        <div>
          <CardTitle className="text-base">LC-MS 单扫描 3D 谱图</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            选中 MS1 扫描的三维棒状谱图（X: m/z，Y: 强度，颜色: Viridis）
          </p>
        </div>
        <span className="font-mono text-xs text-muted-foreground">{subtitle}</span>
      </CardHeader>
      <CardContent>
        {cleanPeaks.length === 0 ? (
          <p className="text-sm text-muted-foreground">该扫描暂无可显示的峰。</p>
        ) : (
          <ThreeLcmsScene peaks={cleanPeaks} height={480} />
        )}
      </CardContent>
    </Card>
  );
}
