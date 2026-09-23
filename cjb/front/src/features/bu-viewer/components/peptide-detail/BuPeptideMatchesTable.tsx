import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { BuPeptideDetailOut } from "@/features/bu-viewer/types";
import { formatCount, formatDecimal } from "@/features/bu-viewer/utils";

export function BuPeptideMatchesTable({ slug, peptide }: { slug: string; peptide: BuPeptideDetailOut }) {
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Proteins</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="py-2 text-left">Accession</th>
                  <th className="py-2 text-left">Gene</th>
                  <th className="py-2 text-left">Group</th>
                  <th className="py-2 text-right">Unique</th>
                </tr>
              </thead>
              <tbody>
                {peptide.proteins.map((protein) => (
                  <tr key={protein.protein_id} className="border-b border-border/60 last:border-0">
                    <td className="py-2">
                      <Link
                        className="font-medium text-primary hover:underline"
                        to={`/datasets/${slug}/proteins/${protein.protein_id}`}
                      >
                        {protein.accession}
                      </Link>
                    </td>
                    <td className="py-2">{protein.gene_name ?? "-"}</td>
                    <td className="max-w-[220px] truncate py-2" title={protein.protein_group ?? undefined}>
                      {protein.protein_group ?? "-"}
                    </td>
                    <td className="py-2 text-right">
                      <Badge variant={protein.is_unique ? "default" : "secondary"}>
                        {protein.is_unique ? "unique" : "shared"}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Best matches ({formatCount(peptide.matches_summary.total)})</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="py-2 text-left">Match</th>
                  <th className="py-2 text-left">Run</th>
                  <th className="py-2 text-right">m/z</th>
                  <th className="py-2 text-right">z</th>
                  <th className="py-2 text-right">RT</th>
                  <th className="py-2 text-right">Q</th>
                  <th className="py-2 text-right">Intensity</th>
                </tr>
              </thead>
              <tbody>
                {peptide.matches_summary.items.map((match) => (
                  <tr key={match.id} className="border-b border-border/60 last:border-0">
                    <td className="py-2">
                      <Link className="font-medium text-primary hover:underline" to={`/datasets/${slug}/matches/${match.id}`}>
                        #{match.id}
                      </Link>
                    </td>
                    <td className="max-w-[180px] truncate py-2" title={match.run_name}>
                      {match.run_name}
                    </td>
                    <td className="py-2 text-right font-mono text-xs">{formatDecimal(match.precursor_mz)}</td>
                    <td className="py-2 text-right">{match.precursor_charge ? `${match.precursor_charge}+` : "-"}</td>
                    <td className="py-2 text-right font-mono text-xs">{formatDecimal(match.retention_time)}</td>
                    <td className="py-2 text-right font-mono text-xs">{formatDecimal(match.q_value)}</td>
                    <td className="py-2 text-right font-mono text-xs">{formatCount(match.intensity)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
