/**
 * 蛋白质详情：展示统计信息及下属 proteoform 表格与跳转链接。
 */
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { fetchProtein } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
import { PageHeader } from "@/components/common/page-header";
import { PageLoading } from "@/components/common/page-loading";
import { Stat } from "@/components/common/stat";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatEValue, formatNumber } from "@/lib/utils";
import { TransitionLink, usePageTransitionReady } from "@/features/page-transition";

export function ProteinDetailPage() {
  const { slug = "", cutoff = "", proteinId = "" } = useParams();
  const { data, isLoading, error } = useQuery({
    queryKey: ["protein", slug, cutoff, proteinId],
    queryFn: () => fetchProtein(slug, cutoff, Number(proteinId)),
  });
  usePageTransitionReady(!isLoading);

  if (isLoading) return <PageLoading />;
  if (error && !data) return <DataLoadError />;
  if (!data) return <DataEmptyState />;

  return (
    <>
      <PageHeader
        title={data.sequence_name}
        description={data.sequence_description ?? undefined}
        crumbs={[
          { label: "Datasets", to: "/datasets" },
          { label: slug, to: `/datasets/${slug}` },
          { label: `Proteins (${cutoff})`, to: `/datasets/${slug}/${cutoff}/proteins` },
          { label: data.sequence_name },
        ]}
        actions={<Badge variant="outline">sequence_id = {data.sequence_id}</Badge>}
      />

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Proteoforms" value={data.compatible_proteoform_number} />
        <Stat label="PrSMs" value={data.prsm_number} />
        <Stat label="Best e-value" value={formatEValue(data.best_prsm_e_value)} />
        <Stat
          label="Best PrSM"
          value={
            data.best_prsm_id != null ? (
              <TransitionLink
                to={`/datasets/${slug}/${cutoff}/prsms/${data.best_prsm_id}`}
                className="text-primary hover:underline"
              >
                #{data.best_prsm_id}
              </TransitionLink>
            ) : (
              "—"
            )
          }
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Proteoforms ({data.proteoforms.length})</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Proteoform ID</TableHead>
                <TableHead className="text-right">Mass</TableHead>
                <TableHead className="text-right">PrSMs</TableHead>
                <TableHead className="text-right">Best e-value</TableHead>
                <TableHead className="text-right">Best PrSM</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.proteoforms.map((pf) => (
                <TableRow key={pf.id}>
                  <TableCell>
                    <TransitionLink
                      to={`/datasets/${slug}/${cutoff}/proteoforms/${pf.id}`}
                      className="font-medium text-foreground hover:text-primary"
                    >
                      Proteoform #{pf.proteoform_id}
                    </TransitionLink>
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {formatNumber(pf.proteoform_mass, 4)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    <Badge>{pf.prsm_number}</Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {formatEValue(pf.best_prsm_e_value)}
                  </TableCell>
                  <TableCell className="text-right">
                    {pf.best_prsm_id != null ? (
                      <TransitionLink
                        to={`/datasets/${slug}/${cutoff}/prsms/${pf.best_prsm_id}`}
                        className="text-primary hover:underline"
                      >
                        #{pf.best_prsm_id}
                      </TransitionLink>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}
