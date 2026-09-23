import { TransitionLink } from "@/features/page-transition";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { BuProteinDetailOut } from "@/features/bu/types";
import { formatCount, formatDecimal } from "@/features/bu/utils";
import { formatModifiedSequenceForDisplay } from "@/features/bu/utils/modifiedSequenceFormatting";

export function BuPeptideLinksTable({ slug, protein }: { slug: string; protein: BuProteinDetailOut }) {
  const mappedIds = new Set(
    protein.coverage_segments
      .filter((segment) => segment.start !== null && segment.end !== null)
      .map((segment) => segment.peptide_id),
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Peptides</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-border text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="py-2 text-left">Sequence</th>
                <th className="py-2 text-left">Modified</th>
                <th className="py-2 text-right">Matches</th>
                <th className="py-2 text-right">Best Q</th>
                <th className="py-2 text-left">Mapping</th>
                <th className="py-2 text-right">Best match</th>
              </tr>
            </thead>
            <tbody>
              {protein.peptides.map((peptide) => (
                <tr key={peptide.peptide_id} className="border-b border-border/60 last:border-0">
                  <td className="py-2 font-mono">
                    <TransitionLink
                      className="font-medium text-primary hover:underline"
                      to={`/datasets/${slug}/peptides/${peptide.peptide_id}`}
                    >
                      {peptide.sequence}
                    </TransitionLink>
                  </td>
                  <td
                    className="max-w-[260px] truncate py-2 text-muted-foreground"
                    title={peptide.modified_sequence ?? undefined}
                  >
                    {peptide.modified_sequence
                      ? formatModifiedSequenceForDisplay(peptide.modified_sequence)
                      : "-"}
                  </td>
                  <td className="py-2 text-right">{formatCount(peptide.match_count)}</td>
                  <td className="py-2 text-right font-mono text-xs">{formatDecimal(peptide.best_q_value)}</td>
                  <td className="py-2">
                    {protein.coverage_mode === "decoy" || protein.coverage_mode === "list_only" ? (
                      <Badge variant="secondary">not shown</Badge>
                    ) : mappedIds.has(peptide.peptide_id) ? (
                      <Badge>mapped</Badge>
                    ) : (
                      <Badge variant="outline">unmapped</Badge>
                    )}
                  </td>
                  <td className="py-2 text-right">
                    {peptide.best_match_id ? (
                      <TransitionLink className="font-medium text-primary hover:underline" to={`/datasets/${slug}/matches/${peptide.best_match_id}`}>
                        #{peptide.best_match_id}
                      </TransitionLink>
                    ) : (
                      "-"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
