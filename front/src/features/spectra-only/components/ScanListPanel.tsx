import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";

import { PlotStatus } from "@/components/common/plot-status";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { SpectraScanIndexItem } from "@/features/spectra-only/types";
import {
  filterScansByMsLevel,
  type ScanLevelFilter,
} from "@/features/spectra-only/utils/scanRelations";
import { parseApiError } from "@/lib/apiError";
import { cn, formatNumber } from "@/lib/utils";

const SCAN_LIST_DISPLAY_LIMIT = 250;

export function ScanListPanel({
  runId,
  scans,
  total,
  isLoading,
  error,
  selectedScan,
  onSelectScan,
}: {
  runId: number | null;
  scans: SpectraScanIndexItem[];
  total: number;
  isLoading: boolean;
  error: unknown;
  selectedScan: number | null;
  onSelectScan: (scan: number) => void;
}) {
  const [scanInput, setScanInput] = useState("");
  const [levelFilter, setLevelFilter] = useState<ScanLevelFilter>("all");
  const filteredScans = useMemo(
    () => filterScansByMsLevel(scans, levelFilter),
    [levelFilter, scans],
  );
  const visibleScans = useMemo(
    () => filteredScans.slice(0, SCAN_LIST_DISPLAY_LIMIT),
    [filteredScans],
  );
  const selected = useMemo(
    () => scans.find((scan) => scan.scan_number === selectedScan) ?? null,
    [scans, selectedScan],
  );

  useEffect(() => {
    setLevelFilter("all");
  }, [runId]);

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
        ) : isLoading ? (
          <PlotStatus kind="loading" title="Loading scan index..." className="min-h-48" />
        ) : error ? (
          <ScanIndexErrorState error={error} />
        ) : scans.length === 0 ? (
          <PlotStatus kind="empty" title="No scans found in the scan index." className="min-h-48" />
        ) : filteredScans.length === 0 ? (
          <>
            <ScanLevelFilterControl value={levelFilter} onChange={setLevelFilter} />
            <PlotStatus kind="empty" title="No scans match the current filter." className="min-h-48" />
          </>
        ) : (
          <>
            <ScanLevelFilterControl value={levelFilter} onChange={setLevelFilter} />
            <div className="text-xs text-muted-foreground">
              {formatShowingCount(visibleScans.length, filteredScans.length, total, levelFilter)}
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
                  {visibleScans.map((scan) => (
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

function ScanLevelFilterControl({
  value,
  onChange,
}: {
  value: ScanLevelFilter;
  onChange: (value: ScanLevelFilter) => void;
}) {
  const options: Array<{ value: ScanLevelFilter; label: string }> = [
    { value: "all", label: "All" },
    { value: "ms1", label: "MS1" },
    { value: "ms2", label: "MS2" },
  ];
  return (
    <div className="flex rounded-md border border-border bg-muted/30 p-1 text-xs">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded px-3 py-1 transition-colors",
            value === option.value
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
          aria-pressed={value === option.value}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function formatShowingCount(
  visibleCount: number,
  filteredCount: number,
  total: number,
  filter: ScanLevelFilter,
): string {
  if (filter === "ms1") {
    return `Showing ${visibleCount.toLocaleString()} of ${filteredCount.toLocaleString()} MS1 scans.`;
  }
  if (filter === "ms2") {
    return `Showing ${visibleCount.toLocaleString()} of ${filteredCount.toLocaleString()} MS2 scans.`;
  }
  return `Showing ${visibleCount.toLocaleString()} of ${total.toLocaleString()} scans.`;
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
