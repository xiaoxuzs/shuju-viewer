import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { BuPeptideDetailOut } from "@/features/bu/types";
import { formatCount, formatDecimal } from "@/features/bu/utils";
import { formatModifiedSequenceForDisplay } from "@/features/bu/utils/modifiedSequenceFormatting";

export function BuPeptideHeader({ peptide }: { peptide: BuPeptideDetailOut }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="font-mono text-xl">{peptide.sequence}</CardTitle>
            <p
              className="mt-1 max-w-3xl break-all font-mono text-sm text-muted-foreground"
              title={peptide.example_modified ?? undefined}
            >
              {peptide.example_modified
                ? formatModifiedSequenceForDisplay(peptide.example_modified)
                : "No modified sequence example"}
            </p>
          </div>
          {peptide.best_charge && <Badge variant="secondary">best z {peptide.best_charge}+</Badge>}
        </div>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
        <Field label="Length" value={formatCount(peptide.length)} />
        <Field label="Matches" value={formatCount(peptide.match_count)} />
        <Field label="Proteins" value={formatCount(peptide.protein_count)} />
        <Field label="Best Q" value={formatDecimal(peptide.best_q_value)} />
        <Field label="Best m/z" value={formatDecimal(peptide.best_precursor_mz)} />
        <Field label="Mass" value={formatDecimal(peptide.theoretical_mass)} />
        <Field label="Missed cleavages" value={formatCount(peptide.missed_cleavages)} />
        <Field label="Genes" value={peptide.genes ?? "-"} />
      </CardContent>
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/60 bg-muted/30 p-3">
      <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 break-words font-medium">{value}</div>
    </div>
  );
}
