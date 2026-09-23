/**
 * 蛋白质列表：按 cutoff 分页，支持名称/描述搜索，默认按最佳 e-value 升序。
 */
import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";

import { fetchProteins } from "@/api/client";
import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
import { PageLoading } from "@/components/common/page-loading";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { formatEValue } from "@/lib/utils";
import {
  TransitionLink,
  usePageTransitionReady,
  useTransitionNavigate,
} from "@/features/page-transition";

export function ProteinsPage() {
  const { slug = "", cutoff = "" } = useParams();
  const navigate = useTransitionNavigate();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const pageSize = 50;
  const listSort = "best_prsm_e_value" as const;
  const listOrder = "asc" as const;

  const { data, isLoading, error } = useQuery({
    queryKey: ["proteins", slug, cutoff, page, search, listSort, listOrder],
    queryFn: () =>
      fetchProteins(slug, cutoff, {
        page,
        page_size: pageSize,
        search: search || undefined,
        sort: listSort,
        order: listOrder,
      }),
  });
  usePageTransitionReady(!isLoading);

  if (error && !data) return <DataLoadError />;

  return (
    <>
      <PageHeader
        title="Proteins"
        description={`Proteins matching the ${cutoff} cutoff. Click a row to open details.`}
        crumbs={[
          { label: "Datasets", to: "/datasets" },
          { label: slug, to: `/datasets/${slug}` },
          { label: `${cutoff} cutoff`, to: `/datasets/${slug}` },
          { label: "Proteins" },
        ]}
        actions={
          <div className="relative w-full sm:w-80">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              className="pl-8"
              placeholder="Search by name or description"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </div>
        }
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
                  <TableHead>Sequence Name</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="text-right">Proteoforms</TableHead>
                  <TableHead className="text-right">PrSMs</TableHead>
                  <TableHead className="text-right">Best e-value</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.items.map((p) => (
                  <TableRow
                    key={p.id}
                    className="cursor-pointer"
                    onClick={() => {
                      navigate(`/datasets/${slug}/${cutoff}/proteins/${p.id}`);
                    }}
                  >
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {p.sequence_id}
                    </TableCell>
                    <TableCell>
                      <TransitionLink
                        to={`/datasets/${slug}/${cutoff}/proteins/${p.id}`}
                        className="font-medium text-foreground hover:text-primary"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {p.sequence_name}
                      </TransitionLink>
                    </TableCell>
                    <TableCell className="max-w-md truncate text-muted-foreground">
                      {p.sequence_description ?? "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      <Badge variant="secondary">{p.compatible_proteoform_number}</Badge>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      <Badge>{p.prsm_number}</Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {formatEValue(p.best_prsm_e_value)}
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
