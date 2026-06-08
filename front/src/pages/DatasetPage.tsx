/**
 * 单个数据集概览：汇总各 cutoff 规模，并链接到蛋白质 / proteoform / PrSM 列表。
 */
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Filter } from "lucide-react";

import { fetchDataset } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
import { PageHeader } from "@/components/common/page-header";
import { PageLoading } from "@/components/common/page-loading";
import { Stat } from "@/components/common/stat";

export function DatasetPage() {
  const { slug = "" } = useParams();
  const { data, isLoading, error } = useQuery({
    queryKey: ["dataset", slug],
    queryFn: () => fetchDataset(slug),
    enabled: !!slug,
  });

  if (isLoading) return <PageLoading />;
  if (error && !data) return <DataLoadError />;
  if (!data) return <DataEmptyState />;

  const totalProteins = data.cutoffs.reduce((a, c) => a + c.protein_count, 0);
  const totalProteoforms = data.cutoffs.reduce((a, c) => a + c.proteoform_count, 0);
  const totalPrsms = data.cutoffs.reduce((a, c) => a + c.prsm_count, 0);

  return (
    <>
      <PageHeader
        title={data.name}
        description={data.description ?? "Choose a cutoff level to browse proteins, proteoforms and PrSMs."}
        crumbs={[{ label: "Datasets", to: "/datasets" }, { label: data.name }]}
      />

      <div className="mb-8 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Cutoffs" value={data.cutoffs.length} />
        <Stat label="Proteins" value={totalProteins.toLocaleString()} />
        <Stat label="Proteoforms" value={totalProteoforms.toLocaleString()} />
        <Stat label="PrSMs" value={totalPrsms.toLocaleString()} />
      </div>

      <h2 className="mb-3 text-sm font-medium uppercase tracking-wider text-muted-foreground">
        Cutoffs
      </h2>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {data.cutoffs.map((c) => (
          <Card key={c.id} className="border-border/50">
            <CardHeader>
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/15 text-primary">
                    <Filter className="h-5 w-5" />
                  </div>
                  <Badge variant="outline" className="font-mono uppercase">
                    {c.kind}
                  </Badge>
                </div>
              </div>
              <CardTitle className="mt-3">{c.label}</CardTitle>
              <CardDescription>
                {c.protein_count.toLocaleString()} proteins · {c.proteoform_count.toLocaleString()} proteoforms ·{" "}
                {c.prsm_count.toLocaleString()} PrSMs
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 gap-2">
                <CutoffLink to={`/datasets/${slug}/${c.kind}/proteins`} label="Proteins" count={c.protein_count} />
                <CutoffLink to={`/datasets/${slug}/${c.kind}/proteoforms`} label="Proteoforms" count={c.proteoform_count} />
                <CutoffLink to={`/datasets/${slug}/${c.kind}/prsms`} label="PrSMs" count={c.prsm_count} />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  );
}

function CutoffLink({ to, label, count }: { to: string; label: string; count: number }) {
  return (
    <Link
      to={to}
      className="group flex flex-col justify-between rounded-lg border border-border/60 bg-muted/40 p-3 transition-colors hover:border-primary/40 hover:bg-accent"
    >
      <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 flex items-end justify-between">
        <div className="text-lg font-semibold">{count.toLocaleString()}</div>
        <ArrowRight className="h-4 w-4 text-muted-foreground transition group-hover:translate-x-0.5 group-hover:text-primary" />
      </div>
    </Link>
  );
}
