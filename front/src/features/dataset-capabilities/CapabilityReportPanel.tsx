import { Database } from "lucide-react";

import type { DatasetCapabilityReport } from "@/api/types";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function CapabilityReportPanel({ report }: { report: DatasetCapabilityReport }) {
  const recognizedCount = report.entities.filter(
    ({ state }) => state === "DIRECT" || state === "DERIVED",
  ).length;

  return (
    <Card data-testid="dataset-capability-report">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <Database className="h-5 w-5 text-primary" aria-hidden="true" />
          Dataset capability report
        </CardTitle>
        <CardDescription>A brief summary of the content and views available for this dataset.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {report.enforcement === "ADVISORY" && (
          <div
            className="rounded-md border border-warning/40 bg-warning/10 p-3 text-warning-foreground"
            data-testid="capability-report-advisory"
            role="status"
          >
            This summary comes from legacy metadata and does not disable existing Viewer pages.
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="Recognized entities" value={recognizedCount} />
          <Metric label="Available views" value={report.views.filter((view) => view.availability === "AVAILABLE").length} />
          <Metric label="Partial views" value={report.views.filter((view) => view.availability === "PARTIAL").length} />
          <Metric label="Disabled views" value={report.views.filter((view) => view.availability === "DISABLED").length} />
        </div>
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-border/60 bg-muted/20 p-3" data-testid="capability-summary-metric">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value.toLocaleString()}</div>
    </div>
  );
}
