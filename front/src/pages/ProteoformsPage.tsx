/**
 * Proteoform 列表：按 cutoff 分页，默认按 PrSM 数量降序。
 */
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { fetchProteoforms } from "@/api/client";
import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
import { PageLoading } from "@/components/common/page-loading";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatEValue, formatNumber } from "@/lib/utils";

export function ProteoformsPage() {
  const { slug = "", cutoff = "" } = useParams();
  const [page, setPage] = useState(1);
  const pageSize = 50;

  const { data, isLoading, error } = useQuery({
    queryKey: ["proteoforms", slug, cutoff, page],
    queryFn: () =>
      fetchProteoforms(slug, cutoff, {
        page,
        page_size: pageSize,
        sort: "prsm_number",
        order: "desc",
      }),
  });

  if (error && !data) return <DataLoadError />;

  return (
    <>
      <PageHeader
        title="Proteoforms"
        description={`Proteoforms in ${cutoff} cutoff.`}
        crumbs={[
          { label: "Datasets", to: "/datasets" },
          { label: slug, to: `/datasets/${slug}` },
          { label: "Proteoforms" },
        ]}
      />

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <PageLoading className="min-h-48" />
          ) : data?.items.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">ID</TableHead>
                  <TableHead>Protein</TableHead>
                  <TableHead>Proteoform</TableHead>
                  <TableHead className="text-right">Mass</TableHead>
                  <TableHead className="text-right">PrSMs</TableHead>
                  <TableHead className="text-right">Best e-value</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.items.map((pf) => (
                  <TableRow key={pf.id}>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {pf.sequence_id}
                    </TableCell>
                    <TableCell className="truncate text-foreground">{pf.sequence_name}</TableCell>
                    <TableCell>
                      <Link
                        to={`/datasets/${slug}/${cutoff}/proteoforms/${pf.id}`}
                        className="font-medium text-foreground hover:text-primary"
                      >
                        Proteoform #{pf.proteoform_id}
                      </Link>
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
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <DataEmptyState compact />
          )}
        </CardContent>
      </Card>

      <div className="mt-4">
        <Pagination
          page={page}
          pageSize={pageSize}
          total={data?.total ?? 0}
          onPageChange={setPage}
        />
      </div>
    </>
  );
}
