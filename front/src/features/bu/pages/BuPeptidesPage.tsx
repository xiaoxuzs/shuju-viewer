import { Link, useOutletContext, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { DataLoadError } from "@/components/common/data-state";
import { Pagination } from "@/components/common/pagination";
import { Badge } from "@/components/ui/badge";
import { fetchBuPeptides } from "@/features/bu/api/buClient";
import { BuDataTable, type BuColumn } from "@/features/bu/components/BuDataTable";
import { BuListFilters } from "@/features/bu/components/BuListFilters";
import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";
import type { BuPeptideListItemOut } from "@/features/bu/types";
import { formatCount, formatDecimal } from "@/features/bu/utils";
import { clearListParams, setListParam } from "@/features/bu/utils/listParams";
import { formatModifiedSequenceForDisplay } from "@/features/bu/utils/modifiedSequenceFormatting";

export function BuPeptidesPage() {
  const { dataset } = useOutletContext<BuDatasetContext>();
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Number(searchParams.get("page") ?? "1") || 1;
  const search = searchParams.get("search") ?? "";
  const qMaxText = searchParams.get("q_max") ?? "";
  const qMax = Number(qMaxText);
  const pageSize = 50;

  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, "peptides", page, search, qMaxText],
    queryFn: () =>
      fetchBuPeptides(dataset.slug, {
        page,
        page_size: pageSize,
        search: search || undefined,
        q_max: qMaxText && Number.isFinite(qMax) ? qMax : undefined,
        sort: "best_q_value",
        order: "asc",
      }),
  });

  const columns: BuColumn<BuPeptideListItemOut>[] = [
    { key: "sequence", header: "Sequence", render: (row) => row.sequence },
    {
      key: "modified",
      header: "Example modified",
      render: (row) =>
        row.example_modified ? (
          <span title={row.example_modified}>
            {formatModifiedSequenceForDisplay(row.example_modified)}
          </span>
        ) : (
          "-"
        ),
    },
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
    {
      key: "actions",
      header: "",
      className: "text-right",
      render: (row) => (
        <Link
          className="text-xs font-medium text-primary hover:underline"
          to={`/datasets/${dataset.slug}/matches?search=${encodeURIComponent(row.sequence)}`}
        >
          All matches
        </Link>
      ),
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
        onReset={() => clearListParams(searchParams, setSearchParams, ["search", "q_max"])}
      />
      <BuDataTable
        columns={columns}
        rows={data?.items ?? []}
        isLoading={isLoading}
        emptyTitle="No peptides"
        emptyDescription="No peptide rows match the current filters."
        rowHref={(row) => `/datasets/${dataset.slug}/peptides/${row.id}`}
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
