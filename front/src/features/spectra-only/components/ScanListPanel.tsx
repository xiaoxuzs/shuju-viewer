import { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";

import { PlotStatus } from "@/components/common/plot-status";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { SpectraScanIndexItem } from "@/features/spectra-only/types";
import {
  filterScansByMsLevel,
  getMsLevel,
  getScanNumber,
  type ScanLevelFilter,
} from "@/features/spectra-only/utils/scanRelations";
import { clampPage, findPageForScan, paginateScans } from "@/features/spectra-only/utils/scanPagination";
import { parseApiError } from "@/lib/apiError";
import { cn, formatNumber } from "@/lib/utils";

const SCAN_LIST_PAGE_SIZE = 250;

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
  const [pageInput, setPageInput] = useState("");
  const [levelFilter, setLevelFilter] = useState<ScanLevelFilter>("all");
  const [currentPage, setCurrentPage] = useState(1);
  const [scanSearchMessage, setScanSearchMessage] = useState<string | null>(null);
  const previousSelectedScanRef = useRef<number | null>(selectedScan);
  const filteredScans = useMemo(
    () => filterScansByMsLevel(scans, levelFilter),
    [levelFilter, scans],
  );
  const scanPage = useMemo(
    () => paginateScans(filteredScans, currentPage, SCAN_LIST_PAGE_SIZE),
    [currentPage, filteredScans],
  );
  const visibleScans = scanPage.items;
  const selected = useMemo(
    () => scans.find((scan) => getScanNumber(scan) === selectedScan) ?? null,
    [scans, selectedScan],
  );
  const selectedPage = selectedScan == null ? null : findPageForScan(filteredScans, selectedScan, SCAN_LIST_PAGE_SIZE);
  const selectedHiddenByFilter = selected != null && selectedPage == null;

  useEffect(() => {
    setLevelFilter("all");
    setCurrentPage(1);
    setScanSearchMessage(null);
  }, [runId]);

  useEffect(() => {
    if (selectedScan == null && scans.length > 0) {
      const firstScanNumber = getScanNumber(scans[0]);
      if (firstScanNumber != null) onSelectScan(firstScanNumber);
    }
  }, [onSelectScan, scans, selectedScan]);

  useEffect(() => {
    setCurrentPage((page) => clampPage(page, scanPage.totalPages));
  }, [scanPage.totalPages]);

  useEffect(() => {
    if (selectedScan === previousSelectedScanRef.current) return;
    previousSelectedScanRef.current = selectedScan;
    setScanSearchMessage(null);
    if (selectedScan == null) return;
    const nextPage = findPageForScan(filteredScans, selectedScan, SCAN_LIST_PAGE_SIZE);
    if (nextPage != null) setCurrentPage(nextPage);
  }, [filteredScans, selectedScan]);

  const changeLevelFilter = (value: ScanLevelFilter) => {
    setLevelFilter(value);
    setCurrentPage(1);
    setScanSearchMessage(null);
  };

  const submitScan = () => {
    const parsed = Number(scanInput);
    if (!Number.isInteger(parsed) || parsed <= 0) {
      setScanSearchMessage("Scan number was not found.");
      return;
    }

    const scanExists = scans.some((scan) => getScanNumber(scan) === parsed);
    if (!scanExists) {
      setScanSearchMessage("Scan number was not found.");
      return;
    }

    const nextPage = findPageForScan(filteredScans, parsed, SCAN_LIST_PAGE_SIZE);
    if (nextPage != null) {
      setCurrentPage(nextPage);
    }
    setScanSearchMessage(null);
    onSelectScan(parsed);
  };

  const submitPage = () => {
    const parsed = Number(pageInput);
    if (!Number.isInteger(parsed)) return;
    setCurrentPage(clampPage(parsed, scanPage.totalPages));
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
            <ScanLevelFilterControl value={levelFilter} onChange={changeLevelFilter} />
            <PlotStatus kind="empty" title="No scans match the current filter." className="min-h-48" />
          </>
        ) : (
          <>
            <ScanLevelFilterControl value={levelFilter} onChange={changeLevelFilter} />
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>{formatShowingRange(scanPage.pageStart, scanPage.pageEnd, filteredScans.length, total, levelFilter)}</span>
              <span>
                Page {scanPage.currentPage.toLocaleString()} of {scanPage.totalPages.toLocaleString()}
              </span>
            </div>
            {selected && (
              <div className="rounded-md border border-border/60 bg-muted/30 p-2 text-xs text-muted-foreground">
                Selected scan {selected.scan_number} - MS{getMsLevel(selected) ?? selected.ms_level} - RT {formatNumber(selected.retention_time, 2)} min
              </div>
            )}
            {selectedHiddenByFilter && (
              <div className="rounded-md border border-border/60 bg-muted/30 p-2 text-xs text-muted-foreground">
                Selected scan is hidden by the current filter.
              </div>
            )}
            {scanSearchMessage && (
              <div className="rounded-md border border-border/60 bg-muted/30 p-2 text-xs text-muted-foreground">
                {scanSearchMessage}
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
                      key={String(getScanNumber(scan) ?? scan.native_id)}
                      scan={scan}
                      active={getScanNumber(scan) === selectedScan}
                      onSelect={() => {
                        const scanNumber = getScanNumber(scan);
                        if (scanNumber != null) onSelectScan(scanNumber);
                      }}
                    />
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={scanPage.currentPage <= 1}
                onClick={() => setCurrentPage((page) => clampPage(page - 1, scanPage.totalPages))}
              >
                Previous
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={scanPage.currentPage >= scanPage.totalPages}
                onClick={() => setCurrentPage((page) => clampPage(page + 1, scanPage.totalPages))}
              >
                Next
              </Button>
              <div className="ml-auto flex min-w-0 items-center gap-2">
                <Input
                  inputMode="numeric"
                  aria-label="Go to page"
                  placeholder="Go to page"
                  value={pageInput}
                  className="h-9 w-28"
                  onChange={(event) => setPageInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") submitPage();
                  }}
                />
                <Button type="button" variant="outline" size="sm" onClick={submitPage}>
                  Go
                </Button>
              </div>
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

function formatShowingRange(
  pageStart: number,
  pageEnd: number,
  filteredCount: number,
  total: number,
  filter: ScanLevelFilter,
): string {
  if (filter === "ms1") {
    return `Showing ${pageStart.toLocaleString()}-${pageEnd.toLocaleString()} of ${filteredCount.toLocaleString()} MS1 scans.`;
  }
  if (filter === "ms2") {
    return `Showing ${pageStart.toLocaleString()}-${pageEnd.toLocaleString()} of ${filteredCount.toLocaleString()} MS2 scans.`;
  }
  return `Showing ${pageStart.toLocaleString()}-${pageEnd.toLocaleString()} of ${total.toLocaleString()} scans.`;
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
      <td className="px-2 py-1.5">MS{getMsLevel(scan) ?? scan.ms_level}</td>
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
