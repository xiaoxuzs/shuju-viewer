import { useEffect, useMemo, useState } from "react";

import type { DatasetOut } from "@/api/types";
import { PageHeader } from "@/components/common/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ChromatogramPanel } from "@/features/spectra-only/components/ChromatogramPanel";
import { RunSelector } from "@/features/spectra-only/components/RunSelector";
import { RunSummaryCards } from "@/features/spectra-only/components/RunSummaryCards";
import { ScanListPanel } from "@/features/spectra-only/components/ScanListPanel";
import { SpectrumPanel } from "@/features/spectra-only/components/SpectrumPanel";

export function SpectraOnlyPage({ dataset }: { dataset: DatasetOut }) {
  const runs = useMemo(() => dataset.runs ?? [], [dataset.runs]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(runs[0]?.run_id ?? null);
  const [selectedScan, setSelectedScan] = useState<number | null>(null);
  const selectedRun = runs.find((run) => run.run_id === selectedRunId) ?? runs[0] ?? null;

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
            datasetId={dataset.id}
            runId={selectedRun?.run_id ?? null}
            selectedScan={selectedScan}
            onSelectScan={setSelectedScan}
          />
        </div>
        <div className="space-y-5">
          <ChromatogramPanel datasetId={dataset.id} runId={selectedRun?.run_id ?? null} />
          <SpectrumPanel
            datasetId={dataset.id}
            runId={selectedRun?.run_id ?? null}
            scanNumber={selectedScan}
          />
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
