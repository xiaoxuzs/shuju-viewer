import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { BuProteinDetailOut } from "@/features/bu/types";
import { formatCount, formatDecimal } from "@/features/bu/utils";

export function BuProteinHeader({ slug, protein }: { slug: string; protein: BuProteinDetailOut }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="text-xl">{protein.accession}</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">{protein.description ?? "No description"}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {protein.gene_name && <Badge variant="secondary">{protein.gene_name}</Badge>}
            {protein.is_decoy && <Badge variant="outline">decoy</Badge>}
            <Button asChild size="sm" variant="outline">
              <Link to={`/datasets/${slug}/matches?protein_id=${protein.id}`}>View all matches</Link>
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
        <Field label="Peptides" value={formatCount(protein.peptide_count)} />
        <Field label="Matches" value={formatCount(protein.match_count)} />
        <Field label="Best Q" value={formatDecimal(protein.best_q_value)} />
        <Field label="PG Q" value={formatDecimal(protein.pg_q_value)} />
        <Field label="PG MaxLFQ" value={formatDecimal(protein.pg_max_lfq)} />
        <Field label="Sequence" value={protein.base_sequence ? `${protein.base_sequence.length.toLocaleString()} aa` : "-"} />
        <Field label="Source" value={String(protein.extra_metadata.sequence_source ?? "-")} />
        <Field label="Protein group" value={protein.protein_group ?? "-"} />
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
