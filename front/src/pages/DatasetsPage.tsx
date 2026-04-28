/**
 * 数据集列表：展示已导入项目卡片，空状态时提示 CLI 导入命令。
 */
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Database, FileText, Layers, ListTree } from "lucide-react";

import { fetchDatasets } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/common/page-header";
import { Skeleton } from "@/components/ui/skeleton";

export function DatasetsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["datasets"],
    queryFn: fetchDatasets,
  });

  return (
    <>
      <PageHeader
        title="Datasets"
        description="Pick a dataset to start exploring proteins, proteoforms, PrSMs and spectra."
      />

      {isLoading && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      )}

      {error && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="p-6 text-sm text-destructive">
            Failed to load datasets: {(error as Error).message}
          </CardContent>
        </Card>
      )}

      {data && data.length === 0 && (
        <Card>
          <CardContent className="p-10 text-center text-sm text-muted-foreground">
            No datasets ingested yet. Run the backend CLI to load one:
            <pre className="mt-3 overflow-x-auto rounded-md bg-muted/50 p-3 text-left text-xs">
{`cd back
uv run python -m app.ingest.cli ingest \\
    --root ..\\shuju\\MZ20160222DS_histone48_html \\
    --slug mz20160222ds_histone48 \\
    --name "MZ20160222DS_histone48"`}
            </pre>
          </CardContent>
        </Card>
      )}

      {data && data.length > 0 && (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
          {data.map((ds) => {
            const totalProteins = ds.cutoffs.reduce((a, c) => a + c.protein_count, 0);
            const totalProteoforms = ds.cutoffs.reduce((a, c) => a + c.proteoform_count, 0);
            const totalPrsms = ds.cutoffs.reduce((a, c) => a + c.prsm_count, 0);
            return (
              <Link
                key={ds.id}
                to={`/datasets/${ds.slug}`}
                className="group"
              >
                <Card className="h-full border-border/50 transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-lg hover:shadow-primary/5">
                  <CardHeader>
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/15 text-primary">
                          <Database className="h-5 w-5" />
                        </div>
                        <Badge variant="outline">{ds.slug}</Badge>
                      </div>
                      <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-1 group-hover:text-primary" />
                    </div>
                    <CardTitle className="mt-3 text-xl">{ds.name}</CardTitle>
                    {ds.description && <CardDescription>{ds.description}</CardDescription>}
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="grid grid-cols-3 gap-2 text-xs">
                      <Metric icon={<FileText className="h-3.5 w-3.5" />} label="Proteins" value={totalProteins} />
                      <Metric icon={<Layers className="h-3.5 w-3.5" />} label="Proteoforms" value={totalProteoforms} />
                      <Metric icon={<ListTree className="h-3.5 w-3.5" />} label="PrSMs" value={totalPrsms} />
                    </div>
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {ds.cutoffs.map((c) => (
                        <Badge key={c.id} variant="secondary" className="font-mono text-[10px]">
                          {c.kind}
                        </Badge>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      )}
    </>
  );
}

function Metric({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
}) {
  return (
    <div className="rounded-md border border-border/60 bg-muted/40 p-2">
      <div className="flex items-center gap-1 text-muted-foreground">
        {icon}
        <span className="uppercase tracking-wider">{label}</span>
      </div>
      <div className="mt-0.5 font-semibold text-foreground">{value.toLocaleString()}</div>
    </div>
  );
}
