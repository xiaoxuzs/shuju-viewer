import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import type { DatasetOut } from "@/api/types";
import { PageHeader } from "@/components/common/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { AcquisitionContextPanel } from "@/features/spectra-only/components/AcquisitionContextPanel";
import { ChromatogramPanel } from "@/features/spectra-only/components/ChromatogramPanel";
import { RunSelector } from "@/features/spectra-only/components/RunSelector";
import { RunSummaryCards } from "@/features/spectra-only/components/RunSummaryCards";
import { ScanListPanel } from "@/features/spectra-only/components/ScanListPanel";
import { SpectrumPanel } from "@/features/spectra-only/components/SpectrumPanel";
import { fetchSpectraFullScanIndex } from "@/features/spectra-only/api/spectraClient";
import {
  findChildMs2Scans,
  findParentMs1Scan,
} from "@/features/spectra-only/utils/scanRelations";
import { chartQueryRetry } from "@/lib/apiError";

export function SpectraOnlyPage({ dataset }: { dataset: DatasetOut }) {
  const runs = useMemo(() => dataset.runs ?? [], [dataset.runs]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(runs[0]?.run_id ?? null);
  const [selectedScan, setSelectedScan] = useState<number | null>(null);
  const selectedRun = runs.find((run) => run.run_id === selectedRunId) ?? runs[0] ?? null;
  const scanIndex = useQuery({
    queryKey: ["spectra-only", dataset.id, selectedRun?.run_id ?? null, "scan-index", "full"],
    queryFn: ({ signal }) => fetchSpectraFullScanIndex(dataset.id, selectedRun!.run_id, signal),
    enabled: selectedRun?.run_id != null,
    retry: chartQueryRetry,
  });
  const allScans = scanIndex.data?.items ?? [];
  const selectedScanItem = useMemo(
    () => allScans.find((scan) => scan.scan_number === selectedScan) ?? null,
    [allScans, selectedScan],
  );
  const parentMs1Scan = useMemo(
    () => findParentMs1Scan(allScans, selectedScanItem),
    [allScans, selectedScanItem],
  );
  const contextMs1Scan = selectedScanItem?.ms_level === 1 ? selectedScanItem : parentMs1Scan;
  const childMs2Scans = useMemo(
    () => findChildMs2Scans(allScans, contextMs1Scan),
    [allScans, contextMs1Scan],
  );

  useEffect(() => {
    if (!selectedRun && runs.length > 0) {
      setSelectedRunId(runs[0].run_id);
    }
  }, [runs, selectedRun]);

  const selectRun = (runId: number) => {
    setSelectedRunId(runId);
    setSelectedScan(null);
  };

  return (
    <>
      <PageHeader
        title={dataset.name}
        description={dataset.description ?? "Raw spectra dataset."}
        crumbs={[{ label: "Datasets", to: "/datasets" }, { label: dataset.name }]}
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Badge>Spectra</Badge>
            {dataset.status && <Badge variant="secondary">{dataset.status}</Badge>}
          </div>
        }
      />

      <div className="mb-5 grid grid-cols-1 gap-3 md:grid-cols-3">
        <SummaryCard label="Runs" value={runs.length.toLocaleString()} />
        <SummaryCard label="Format" value={selectedRun?.raw_format ?? "mzML"} />
        <SummaryCard label="Mode" value="mzML memory" />
      </div>

      <div className="mb-5 flex flex-wrap justify-end gap-2">
        <RunSelector runs={runs} selectedRunId={selectedRun?.run_id ?? null} onChange={selectRun} />
      </div>

      <RunSummaryCards datasetId={dataset.id} runId={selectedRun?.run_id ?? null} />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(320px,420px)_1fr]">
        <div className="space-y-5">
          <ScanListPanel
            runId={selectedRun?.run_id ?? null}
            scans={allScans}
            total={scanIndex.data?.total ?? allScans.length}
            isLoading={scanIndex.isLoading}
            error={scanIndex.error}
            selectedScan={selectedScan}
            onSelectScan={setSelectedScan}
          />
        </div>
        <div className="space-y-5">
          <ChromatogramPanel datasetId={dataset.id} runId={selectedRun?.run_id ?? null} />
          <AcquisitionContextPanel
            selectedScan={selectedScanItem}
            parentMs1Scan={parentMs1Scan}
            childMs2Scans={childMs2Scans}
            onSelectScan={setSelectedScan}
          />
          {selectedScanItem?.ms_level === 2 ? (
            <>
              {parentMs1Scan && (
                <SpectrumPanel
                  datasetId={dataset.id}
                  runId={selectedRun?.run_id ?? null}
                  scanNumber={parentMs1Scan.scan_number}
                  titlePrefix="Parent MS1 Spectrum"
                  highlight={{
                    targetMz: selectedScanItem.precursor_mz,
                    label: "precursor",
                    toleranceDa: 0.05,
                  }}
                />
              )}
              <SpectrumPanel
                datasetId={dataset.id}
                runId={selectedRun?.run_id ?? null}
                scanNumber={selectedScanItem.scan_number}
                titlePrefix="Selected MS2 Spectrum"
              />
            </>
          ) : selectedScanItem?.ms_level === 1 ? (
            <SpectrumPanel
              datasetId={dataset.id}
              runId={selectedRun?.run_id ?? null}
              scanNumber={selectedScanItem.scan_number}
              titlePrefix="MS1 Spectrum"
            />
          ) : (
            <SpectrumPanel
              datasetId={dataset.id}
              runId={selectedRun?.run_id ?? null}
              scanNumber={selectedScan}
            />
          )}
        </div>
      </div>
    </>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="p-3">
        <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="mt-1 truncate text-base font-semibold">{value}</div>
      </CardContent>
    </Card>
  );
}
