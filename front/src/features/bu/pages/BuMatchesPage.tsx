import { useOutletContext, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Pagination } from "@/components/common/pagination";
import { Badge } from "@/components/ui/badge";
import { fetchBuMatches } from "@/features/bu/api/buClient";
import { BuDataTable, type BuColumn } from "@/features/bu/components/BuDataTable";
import { BuListFilters } from "@/features/bu/components/BuListFilters";
import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";
import type { BuMatchListItemOut } from "@/features/bu/types";
import { formatCount, formatDecimal } from "@/features/bu/utils";

export function BuMatchesPage() {
  const { dataset, defaultQMax } = useOutletContext<BuDatasetContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Number(searchParams.get("page") ?? "1") || 1;
  const search = searchParams.get("search") ?? "";
  const qMaxText = searchParams.get("q_max") ?? String(defaultQMax ?? 0.01);
  const qMax = Number(qMaxText);
  const pageSize = 50;

  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, "matches", page, search, qMaxText],
    queryFn: () =>
      fetchBuMatches(dataset.slug, {
        page,
        page_size: pageSize,
        search: search || undefined,
        q_max: Number.isFinite(qMax) ? qMax : undefined,
        sort: "q_value",
        order: "asc",
      }),
  });

  const columns: BuColumn<BuMatchListItemOut>[] = [
    { key: "sequence", header: "Sequence", render: (row) => row.modified_sequence ?? row.sequence },
    { key: "run", header: "Run", render: (row) => row.run_name },
    {
      key: "mz",
      header: "m/z",
      className: "text-right font-mono text-xs",
      render: (row) => formatDecimal(row.precursor_mz),
    },
    {
      key: "charge",
      header: "z",
      className: "text-right",
      render: (row) => (row.precursor_charge ? <Badge variant="secondary">{row.precursor_charge}+</Badge> : "-"),
    },
    {
      key: "rt",
      header: "RT",
      className: "text-right font-mono text-xs",
      render: (row) => formatDecimal(row.retention_time),
    },
    {
      key: "q",
      header: "Q.Value",
      className: "text-right font-mono text-xs",
      render: (row) => formatDecimal(row.q_value),
    },
    {
      key: "intensity",
      header: "Intensity",
      className: "text-right font-mono text-xs",
      render: (row) => formatCount(row.intensity),
    },
  ];

  if (error) return <p className="text-destructive">{(error as Error).message}</p>;

  return (
    <div className="space-y-4">
      <BuListFilters
        search={search}
        onSearchChange={(value) => setListParam(searchParams, setSearchParams, "search", value)}
        showQMax
        qMax={qMaxText}
        onQMaxChange={(value) => setListParam(searchParams, setSearchParams, "q_max", value)}
      />
      <BuDataTable
        columns={columns}
        rows={data?.items ?? []}
        isLoading={isLoading}
        emptyTitle="No matches"
        emptyDescription="No identification matches pass the current filters."
        rowHref={(row) => `/datasets/${dataset.slug}/matches/${row.id}`}
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
