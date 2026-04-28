/**
 * Proteoform 详情：展示质量、修饰相关统计及该形式下 PrSM 列表。
 */
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { fetchProteoform } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/common/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { Stat } from "@/components/common/stat";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatEValue, formatNumber } from "@/lib/utils";

export function ProteoformDetailPage() {
  const { slug = "", cutoff = "", proteoformId = "" } = useParams();
  const { data, isLoading } = useQuery({
    queryKey: ["proteoform", slug, cutoff, proteoformId],
    queryFn: () => fetchProteoform(slug, cutoff, Number(proteoformId)),
  });

  if (isLoading) return <Skeleton className="h-96" />;
  if (!data) return null;

  return (
    <>
      <PageHeader
        title={`Proteoform #${data.proteoform_id}`}
        description={data.sequence_name}
        crumbs={[
          { label: "Datasets", to: "/datasets" },
          { label: slug, to: `/datasets/${slug}` },
          { label: "Proteoforms", to: `/datasets/${slug}/${cutoff}/proteoforms` },
          { label: `Proteoform #${data.proteoform_id}` },
        ]}
        actions={
          <Badge variant="outline">
            <Link to={`/datasets/${slug}/${cutoff}/proteins/${data.protein_id}`}>
              ← back to protein
            </Link>
          </Badge>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Mass" value={formatNumber(data.proteoform_mass, 4)} />
        <Stat label="PrSMs" value={data.prsm_number} />
        <Stat label="Best e-value" value={formatEValue(data.best_prsm_e_value)} />
        <Stat
          label="N-acetylations"
          value={data.n_acetylation ?? "—"}
          hint={data.unexpected_shift_number != null ? `${data.unexpected_shift_number} unexpected shifts` : undefined}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">PrSMs ({data.prsms.length})</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>PrSM ID</TableHead>
                <TableHead className="text-right">e-value</TableHead>
                <TableHead className="text-right">Matched frag / peak</TableHead>
                <TableHead className="text-right">Precursor m/z</TableHead>
                <TableHead className="text-right">Charge</TableHead>
                <TableHead className="text-right">Mono mass</TableHead>
                <TableHead>MS2 scan</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.prsms.map((p) => (
                <TableRow key={p.id}>
                  <TableCell>
                    <Link
                      to={`/datasets/${slug}/${cutoff}/prsms/${p.prsm_id}`}
                      className="font-medium text-primary hover:underline"
                    >
                      #{p.prsm_id}
                    </Link>
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {formatEValue(p.e_value)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {p.matched_fragment_number ?? "—"} / {p.matched_peak_number ?? "—"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {formatNumber(p.precursor_mz, 4)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{p.precursor_charge ?? "—"}</TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {formatNumber(p.precursor_mono_mass, 4)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{p.ms2_scans ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}
