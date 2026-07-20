import { useOutletContext, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { TransitionLink, usePageTransitionReady } from "@/features/page-transition";

import { DataLoadError } from "@/components/common/data-state";
import { Pagination } from "@/components/common/pagination";
import { Badge } from "@/components/ui/badge";
import { fetchBuProteins } from "@/features/bu/api/buClient";
import { BuDataTable, type BuColumn } from "@/features/bu/components/BuDataTable";
import { BuListFilters } from "@/features/bu/components/BuListFilters";
import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";
import type { BuProteinListItemOut } from "@/features/bu/types";
import { formatCount, formatDecimal } from "@/features/bu/utils";
import { clearListParams, setListParam } from "@/features/bu/utils/listParams";

export function BuProteinsPage() {
  const { dataset } = useOutletContext<BuDatasetContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Number(searchParams.get("page") ?? "1") || 1;
  const search = searchParams.get("search") ?? "";
  const hideDecoy = searchParams.get("decoy") !== "true";
  const pageSize = 50;

  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, "proteins", page, search, hideDecoy],
    queryFn: () =>
      fetchBuProteins(dataset.slug, {
        page,
        page_size: pageSize,
        search: search || undefined,
        decoy: !hideDecoy,
        sort: "pg_max_lfq",
        order: "desc",
      }),
  });
  usePageTransitionReady(!isLoading);

  const columns: BuColumn<BuProteinListItemOut>[] = [
    { key: "accession", header: "Accession", render: (row) => row.accession },
    { key: "gene", header: "Gene", render: (row) => row.gene_name ?? "-" },
    { key: "description", header: "Description", render: (row) => row.description ?? "-" },
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
      key: "lfq",
      header: "PG MaxLFQ",
      className: "text-right font-mono text-xs",
      render: (row) => formatDecimal(row.pg_max_lfq),
    },
    {
      key: "peptides",
      header: "Peptides",
      className: "text-right",
      render: (row) => <Badge variant="secondary">{formatCount(row.peptide_count)}</Badge>,
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
    {
      key: "actions",
      header: "",
      className: "text-right",
      render: (row) => (
        <TransitionLink
          className="text-xs font-medium text-primary hover:underline"
          to={`/datasets/${dataset.slug}/matches?protein_id=${row.id}`}
        >
          View matches
        </TransitionLink>
      ),
    },
  ];

  if (error && !data) return <DataLoadError />;

  return (
    <div className="space-y-4">
      <BuListFilters
        search={search}
        onSearchChange={(value) => setListParam(searchParams, setSearchParams, "search", value)}
        showDecoyToggle
        hideDecoy={hideDecoy}
        onHideDecoyChange={(checked) =>
          setListParam(searchParams, setSearchParams, "decoy", checked ? "" : "true")
        }
        onReset={() => clearListParams(searchParams, setSearchParams, ["search", "decoy"])}
      />
      <BuDataTable
        columns={columns}
        rows={data?.items ?? []}
        isLoading={isLoading}
        emptyTitle="No proteins"
        emptyDescription="No protein rows match the current filters."
        rowHref={(row) => `/datasets/${dataset.slug}/proteins/${row.id}`}
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
