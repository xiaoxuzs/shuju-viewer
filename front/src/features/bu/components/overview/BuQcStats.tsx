import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { BuOverviewOut } from "@/features/bu/types";
import { formatCount, formatDecimal, isDiaclipSourceSoftware } from "@/features/bu/utils";

const QC_FIELDS: { key: string; label: string; unit?: string }[] = [
  { key: "precursors_identified", label: "Precursors" },
  { key: "proteins_identified", label: "Proteins identified" },
  { key: "peptides_identified", label: "Peptides identified" },
  { key: "median_mass_acc_ms1", label: "Median mass acc. MS1", unit: "ppm" },
  { key: "median_mass_acc_ms2", label: "Median mass acc. MS2", unit: "ppm" },
  { key: "fwhm_rt", label: "FWHM RT", unit: "min" },
  { key: "median_rt_prediction_acc", label: "Median RT pred. acc." },
  { key: "average_peptide_length", label: "Avg peptide length" },
  { key: "average_peptide_charge", label: "Avg peptide charge" },
  { key: "normalisation_instability", label: "Normalisation instability" },
];

export function BuQcStats({ overview }: { overview: BuOverviewOut }) {
  const qc = overview.qc.aggregated ?? {};
  const importedMatches = overview.import_stats.imported_matches ?? overview.import_stats.matches_imported;
  const isDiaclip = isDiaclipSourceSoftware(overview.source_software);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{isDiaclip ? "DIA-CLIP QC" : "DIA-NN QC"}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
          <Metric
            label={isDiaclip ? "DIA-CLIP q-value cutoff" : "Q.Value cutoff"}
            value={formatDecimal(overview.q_value_cutoff)}
          />
          <Metric label="Imported matches" value={formatMetric(importedMatches)} />
          {QC_FIELDS.map((field) => (
            <Metric key={field.key} label={field.label} value={formatMetric(qc[field.key], field.unit)} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/60 bg-muted/30 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 font-medium">{value}</div>
    </div>
  );
}

function formatMetric(value: unknown, unit?: string): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") {
    const rendered = Number.isInteger(value) && Math.abs(value) >= 1000 ? formatCount(value) : formatDecimal(value);
    return unit ? `${rendered} ${unit}` : rendered;
  }
  if (typeof value === "string") {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return formatMetric(numeric, unit);
    return value;
  }
  return "-";
}
