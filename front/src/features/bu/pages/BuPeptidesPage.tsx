import { useOutletContext, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Pagination } from "@/components/common/pagination";
import { Badge } from "@/components/ui/badge";
import { fetchBuPeptides } from "@/features/bu/api/buClient";
import { BuDataTable, type BuColumn } from "@/features/bu/components/BuDataTable";
import { BuListFilters } from "@/features/bu/components/BuListFilters";
import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";
import type { BuPeptideListItemOut } from "@/features/bu/types";
import { formatCount, formatDecimal } from "@/features/bu/utils";

export function BuPeptidesPage() {
  const { dataset } = useOutletContext<BuDatasetContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Number(searchParams.get("page") ?? "1") || 1;
  const search = searchParams.get("search") ?? "";
  const pageSize = 50;

  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, "peptides", page, search],
    queryFn: () =>
      fetchBuPeptides(dataset.slug, {
        page,
        page_size: pageSize,
        search: search || undefined,
        sort: "best_q_value",
        order: "asc",
      }),
  });

  const columns: BuColumn<BuPeptideListItemOut>[] = [
    { key: "sequence", header: "Sequence", render: (row) => row.sequence },
    { key: "modified", header: "Example modified", render: (row) => row.example_modified ?? "-" },
    { key: "genes", header: "Genes", render: (row) => row.genes ?? "-" },
    {
      key: "proteins",
      header: "Proteins",
      className: "text-right",
      render: (row) => <Badge variant="secondary">{formatCount(row.protein_count)}</Badge>,
    },
    {
      key: "matches",
      header: "Matches",
      className: "text-right",
      render: (row) => <Badge>{formatCount(row.match_count)}</Badge>,
    },
    {
      key: "q",
      header: "Best Q",
      className: "text-right font-mono text-xs",
      render: (row) => formatDecimal(row.best_q_value),
    },
  ];

  if (error) return <p className="text-destructive">{(error as Error).message}</p>;

  return (
    <div className="space-y-4">
      <BuListFilters
        search={search}
        onSearchChange={(value) => setListParam(searchParams, setSearchParams, "search", value)}
      />
      <BuDataTable
        columns={columns}
        rows={data?.items ?? []}
        isLoading={isLoading}
        emptyTitle="No peptides"
        emptyDescription="No peptide rows match the current filters."
      />
      <Pagination
        page={page}
        pageSize={pageSize}
        total={data?.total ?? 0}
        onPageChange={(nextPage) => setListParam(searchParams, setSearchParams, "page", String(nextPage), false)}
      />
    </div>
  );
}

function setListParam(
  searchParams: URLSearchParams,
  setSearchParams: (nextInit: URLSearchParams) => void,
  key: string,
  value: string,
  resetPage = true,
) {
  const next = new URLSearchParams(searchParams);
  if (value.trim()) next.set(key, value.trim());
  else next.delete(key);
  if (resetPage) next.set("page", "1");
  setSearchParams(next);
}
