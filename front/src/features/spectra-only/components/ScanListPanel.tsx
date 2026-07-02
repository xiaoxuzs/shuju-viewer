import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";

import { PlotStatus } from "@/components/common/plot-status";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { fetchSpectraScanIndex } from "@/features/spectra-only/api/spectraClient";
import type { SpectraScanIndexItem } from "@/features/spectra-only/types";
import { chartQueryRetry, parseApiError } from "@/lib/apiError";
import { cn, formatNumber } from "@/lib/utils";

export function ScanListPanel({
  datasetId,
  runId,
  selectedScan,
  onSelectScan,
}: {
  datasetId: number;
  runId: number | null;
  selectedScan: number | null;
  onSelectScan: (scan: number) => void;
}) {
  const [scanInput, setScanInput] = useState("");
  const scanIndex = useQuery({
    queryKey: ["spectra-only", datasetId, runId, "scan-index"],
    queryFn: () => fetchSpectraScanIndex(datasetId, runId!, { limit: 250 }),
    enabled: runId != null,
    retry: chartQueryRetry,
  });
  const scans = scanIndex.data?.items ?? [];
  const selected = useMemo(
    () => scans.find((scan) => scan.scan_number === selectedScan) ?? null,
    [scans, selectedScan],
  );

  useEffect(() => {
    if (selectedScan == null && scans.length > 0) {
      onSelectScan(scans[0].scan_number);
    }
  }, [onSelectScan, scans, selectedScan]);

  const submitScan = () => {
    const parsed = Number(scanInput);
    if (Number.isInteger(parsed) && parsed > 0) {
      onSelectScan(parsed);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Scans</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-2">
          <Input
            inputMode="numeric"
            placeholder="Scan number"
            value={scanInput}
            onChange={(event) => setScanInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") submitScan();
            }}
          />
          <Button type="button" variant="outline" size="icon" aria-label="Load scan" onClick={submitScan}>
            <Search className="h-4 w-4" />
          </Button>
        </div>

        {runId == null ? (
          <PlotStatus kind="empty" title="No run selected." className="min-h-48" />
        ) : scanIndex.isLoading ? (
          <PlotStatus kind="loading" title="Loading scan index..." className="min-h-48" />
        ) : scanIndex.error ? (
          <ScanIndexErrorState error={scanIndex.error} />
        ) : scans.length === 0 ? (
          <PlotStatus kind="empty" title="No scans found in the scan index." className="min-h-48" />
        ) : (
          <>
            <div className="text-xs text-muted-foreground">
              Showing {scans.length.toLocaleString()} of {scanIndex.data?.total.toLocaleString() ?? "0"} scans.
            </div>
            {selected && (
              <div className="rounded-md border border-border/60 bg-muted/30 p-2 text-xs text-muted-foreground">
                Selected scan {selected.scan_number} - MS{selected.ms_level} - RT {formatNumber(selected.retention_time, 2)} min
              </div>
            )}
            <div className="max-h-[360px] overflow-auto rounded-md border border-border/60">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-background text-muted-foreground">
                  <tr>
                    <th className="px-2 py-2 font-medium">Scan</th>
                    <th className="px-2 py-2 font-medium">MS</th>
                    <th className="px-2 py-2 font-medium">RT min</th>
                    <th className="px-2 py-2 font-medium">TIC</th>
                  </tr>
                </thead>
                <tbody>
                  {scans.map((scan) => (
                    <ScanRow
                      key={scan.scan_number}
                      scan={scan}
                      active={scan.scan_number === selectedScan}
                      onSelect={() => onSelectScan(scan.scan_number)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function ScanRow({
  scan,
  active,
  onSelect,
}: {
  scan: SpectraScanIndexItem;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <tr
      className={cn(
        "cursor-pointer border-t border-border/50 transition-colors hover:bg-accent/50",
        active && "bg-primary/10 text-primary",
      )}
      onClick={onSelect}
    >
      <td className="px-2 py-1.5 font-mono">{scan.scan_number}</td>
      <td className="px-2 py-1.5">MS{scan.ms_level}</td>
      <td className="px-2 py-1.5">{formatNumber(scan.retention_time, 2)}</td>
      <td className="px-2 py-1.5">{formatNumber(scan.tic, 2)}</td>
    </tr>
  );
}

function ScanIndexErrorState({ error }: { error: unknown }) {
  const parsed = parseApiError(error);
  if (parsed.kind === "scan_index_missing") {
    return (
      <PlotStatus
        kind="derived_missing"
        title="Derived scan index is not ready."
        command={parsed.backfillCommand}
        className="min-h-48"
      />
    );
  }
  if (parsed.kind === "scan_index_stale") {
    return (
      <PlotStatus
        kind="derived_stale"
        title="Derived scan index is stale."
        command={parsed.backfillCommand}
        className="min-h-48"
      />
    );
  }
  return <PlotStatus kind="error" title="Failed to load scan index." className="min-h-48" />;
}
