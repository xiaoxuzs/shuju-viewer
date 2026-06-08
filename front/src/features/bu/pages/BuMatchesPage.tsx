import { useOutletContext, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { DataLoadError } from "@/components/common/data-state";
import { Pagination } from "@/components/common/pagination";
import { Badge } from "@/components/ui/badge";
import { fetchBuMatches, fetchBuOverview } from "@/features/bu/api/buClient";
import { BuDataTable, type BuColumn } from "@/features/bu/components/BuDataTable";
import { BuListFilters } from "@/features/bu/components/BuListFilters";
import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";
import type { BuMatchListItemOut } from "@/features/bu/types";
import { formatCount, formatDecimal } from "@/features/bu/utils";
import { clearListParams, numberParam, setListParam } from "@/features/bu/utils/listParams";

export function BuMatchesPage() {
  const { dataset, defaultQMax } = useOutletContext<BuDatasetContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Number(searchParams.get("page") ?? "1") || 1;
  const search = searchParams.get("search") ?? "";
  const qMaxText = searchParams.get("q_max") ?? String(defaultQMax ?? 0.01);
  const qMax = Number(qMaxText);
  const runIdText = searchParams.get("run_id") ?? "";
  const proteinIdText = searchParams.get("protein_id") ?? "";
  const runId = numberParam(runIdText);
  const proteinId = numberParam(proteinIdText);
  const hideDecoy = searchParams.get("decoy") !== "true";
  const pageSize = 50;

  const overview = useQuery({
    queryKey: ["bu", dataset.slug, "overview", "runs"],
    queryFn: () => fetchBuOverview(dataset.slug),
  });

  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, "matches", page, search, qMaxText, runIdText, proteinIdText, hideDecoy],
    queryFn: () =>
      fetchBuMatches(dataset.slug, {
        page,
        page_size: pageSize,
        search: search || undefined,
        q_max: Number.isFinite(qMax) ? qMax : undefined,
        run_id: runId,
        protein_id: proteinId,
        decoy: !hideDecoy,
        sort: "q_value",
        order: "asc",
      }),
  });

  const columns: BuColumn<BuMatchListItemOut>[] = [
    { key: "sequence", header: "Sequence", render: (row) => row.modified_sequence ?? row.sequence },
    { key: "run", header: "Run", render: (row) => row.run_name },
    {
      key: "group",
      header: "Protein group",
      render: (row) => (
        <span title={row.protein_group ?? undefined} className="block max-w-[180px] truncate">
          {row.protein_group ?? "-"}
        </span>
      ),
    },
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

  if (error && !data) return <DataLoadError />;

  return (
    <div className="space-y-4">
      <BuListFilters
        search={search}
        onSearchChange={(value) => setListParam(searchParams, setSearchParams, "search", value)}
        showQMax
        qMax={qMaxText}
        onQMaxChange={(value) => setListParam(searchParams, setSearchParams, "q_max", value)}
        showRunFilter
        runs={overview.data?.runs ?? []}
        runId={runIdText}
        onRunIdChange={(value) => setListParam(searchParams, setSearchParams, "run_id", value)}
        showDecoyToggle
        hideDecoy={hideDecoy}
        onHideDecoyChange={(checked) =>
          setListParam(searchParams, setSearchParams, "decoy", checked ? "" : "true")
        }
        onReset={() => clearListParams(searchParams, setSearchParams, ["search", "q_max", "run_id", "protein_id", "decoy"])}
      />
      {proteinId && (
        <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
          Filtered to protein #{proteinId}.{" "}
          <button
            type="button"
            className="font-medium text-primary hover:underline"
            onClick={() => setListParam(searchParams, setSearchParams, "protein_id", "")}
          >
            Clear protein filter
          </button>
        </div>
      )}
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
