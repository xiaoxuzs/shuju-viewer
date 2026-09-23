/**
 * PrSM 列表：按 cutoff 分页，默认按 e-value 升序（好的匹配在前）。
 */
import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { fetchPrsms } from "@/api/client";
import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
import { PageLoading } from "@/components/common/page-loading";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatEValue, formatNumber } from "@/lib/utils";
import { TransitionLink, usePageTransitionReady } from "@/features/page-transition";

export function PrsmsPage() {
  const { slug = "", cutoff = "" } = useParams();
  const [page, setPage] = useState(1);
  const pageSize = 50;

  const { data, isLoading, error } = useQuery({
    queryKey: ["prsms", slug, cutoff, page],
    queryFn: () =>
      fetchPrsms(slug, cutoff, { page, page_size: pageSize, sort: "e_value", order: "asc" }),
  });
  usePageTransitionReady(!isLoading);

  if (error && !data) return <DataLoadError />;

  return (
    <>
      <PageHeader
        title="PrSMs"
        description={`All protein–spectrum matches in ${cutoff} cutoff, sorted by e-value.`}
        crumbs={[
          { label: "Datasets", to: "/datasets" },
          { label: slug, to: `/datasets/${slug}` },
          { label: "PrSMs" },
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
                  <TableHead className="w-20">PrSM ID</TableHead>
                  <TableHead className="text-right">e-value</TableHead>
                  <TableHead className="text-right">p-value</TableHead>
                  <TableHead className="text-right">Matched frag / peak</TableHead>
                  <TableHead className="text-right">Precursor m/z</TableHead>
                  <TableHead className="text-right">Charge</TableHead>
                  <TableHead className="text-right">Mono mass</TableHead>
                  <TableHead>MS2 scan</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.items.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell>
                      <TransitionLink
                        to={`/datasets/${slug}/${cutoff}/prsms/${p.prsm_id}`}
                        className="font-medium text-primary hover:underline"
                      >
                        #{p.prsm_id}
                      </TransitionLink>
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {formatEValue(p.e_value)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {formatEValue(p.p_value)}
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
