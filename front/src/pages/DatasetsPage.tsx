/**
 * 数据集列表：展示已导入项目卡片；支持上传 ZIP 导入，空状态时仍提示 CLI 备选。
 */
import { useCallback, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import {
  ArrowRight,
  Database,
  FileText,
  Layers,
  ListTree,
  Loader2,
  Trash2,
  Upload,
} from "lucide-react";

import { deleteDataset, enqueueImport, fetchDatasets, fetchImportJob } from "@/api/client";
import type { DatasetOut } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/common/page-header";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function DatasetsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["datasets"],
    queryFn: fetchDatasets,
  });

  const [importOpen, setImportOpen] = useState(false);
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [slug, setSlug] = useState("");
  const [dsName, setDsName] = useState("");
  const [description, setDescription] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Delete dialog state
  const [deleteTarget, setDeleteTarget] = useState<DatasetOut | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const runDelete = useCallback(async () => {
    if (!deleteTarget) return;
    setDeleteError(null);
    setDeleteBusy(true);
    try {
      await deleteDataset(deleteTarget.slug);
      await queryClient.invalidateQueries({ queryKey: ["datasets"] });
      setDeleteTarget(null);
    } catch (e) {
      let msg = (e as Error).message || "Delete failed.";
      if (axios.isAxiosError(e)) {
        const detail = (e.response?.data as { detail?: string } | undefined)?.detail;
        if (detail) msg = detail;
      }
      setDeleteError(msg);
    } finally {
      setDeleteBusy(false);
    }
  }, [deleteTarget, queryClient]);

  const resetImportForm = useCallback(() => {
    setZipFile(null);
    setSlug("");
    setDsName("");
    setDescription("");
    setImportError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, []);

  const runImport = useCallback(async () => {
    if (!zipFile || !slug.trim() || !dsName.trim()) {
      setImportError("Choose a .zip file and fill slug and name.");
      return;
    }
    setImportError(null);
    setImportBusy(true);
    try {
      const form = new FormData();
      form.append("file", zipFile);
      form.append("slug", slug.trim());
      form.append("name", dsName.trim());
      if (description.trim()) form.append("description", description.trim());
      const { job_id: jobId } = await enqueueImport(form);

      for (;;) {
        const job = await fetchImportJob(jobId);
        if (job.status === "success") {
          await sleep(400);
          await queryClient.invalidateQueries({ queryKey: ["datasets"] });
          setImportBusy(false);
          setImportOpen(false);
          resetImportForm();
          return;
        }
        if (job.status === "failed") {
          setImportError(job.error || job.message || "Import failed.");
          setImportBusy(false);
          return;
        }
        await sleep(900);
      }
    } catch (e) {
      setImportError((e as Error).message || "Request failed.");
      setImportBusy(false);
    }
  }, [description, dsName, queryClient, resetImportForm, slug, zipFile]);

  return (
    <>
      <PageHeader
        title="Datasets"
        description="Pick a dataset to start exploring proteins, proteoforms, PrSMs and spectra."
        actions={
          <Button type="button" variant="outline" size="sm" onClick={() => setImportOpen(true)}>
            <Upload className="h-4 w-4" />
            Import from ZIP
          </Button>
        }
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
            No datasets ingested yet. Zip your TopPIC output folder and use &quot;Import from ZIP&quot;, or run the
            universal-schema ingest CLI:
            <pre className="mt-3 overflow-x-auto rounded-md bg-muted/50 p-3 text-left text-xs">
{`cd back
uv run python -m app.ingest.universal_toppic_adapter ingest \\
    --root ..\\shuju\\MZ20160222DS_histone48_html \\
    --database-url "postgresql+psycopg://USER:PASS@localhost:5432/Universal_Viewer" \\
    --slug mz20160222ds_histone48 \\
    --name "MZ20160222DS_histone48" \\
    --mode full --replace`}
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
                      <div className="flex items-center gap-1 text-muted-foreground">
                        <button
                          type="button"
                          aria-label={`Delete ${ds.slug}`}
                          title="Delete this dataset"
                          className={cn(
                            "flex h-7 w-7 items-center justify-center rounded-md",
                            "opacity-60 transition-all hover:bg-destructive/10 hover:text-destructive hover:opacity-100",
                            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-destructive",
                          )}
                          onClick={(ev) => {
                            ev.preventDefault();
                            ev.stopPropagation();
                            setDeleteError(null);
                            setDeleteTarget(ds);
                          }}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                        <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1 group-hover:text-primary" />
                      </div>
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

      {importOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="import-dialog-title"
        >
          <Card className="w-full max-w-md border-border/80 shadow-xl">
            <CardHeader>
              <CardTitle id="import-dialog-title">Import dataset</CardTitle>
              <CardDescription>
                Upload a <span className="font-mono text-foreground">.zip</span> of one TopPIC result tree (contains{" "}
                <span className="font-mono">topfd</span> and <span className="font-mono">toppic_*_cutoff</span>). Files
                are unpacked under the server <span className="font-mono">shuju</span> folder, then ingested.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">Archive (.zip)</label>
                <Input
                  ref={fileInputRef}
                  type="file"
                  accept=".zip,application/zip"
                  disabled={importBusy}
                  onChange={(ev) => {
                    const f = ev.target.files?.[0];
                    setZipFile(f ?? null);
                  }}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="import-slug">
                  Slug (URL id)
                </label>
                <Input
                  id="import-slug"
                  placeholder="e.g. mz20160222ds_histone48"
                  value={slug}
                  disabled={importBusy}
                  onChange={(e) => setSlug(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="import-name">
                  Display name
                </label>
                <Input
                  id="import-name"
                  placeholder="Human-readable name"
                  value={dsName}
                  disabled={importBusy}
                  onChange={(e) => setDsName(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="import-desc">
                  Description (optional)
                </label>
                <textarea
                  id="import-desc"
                  rows={2}
                  placeholder="Optional notes"
                  value={description}
                  disabled={importBusy}
                  onChange={(e) => setDescription(e.target.value)}
                  className={cn(
                    "flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm",
                    "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    "disabled:cursor-not-allowed disabled:opacity-50",
                  )}
                />
              </div>

              {importBusy && (
                <div
                  className="space-y-2 rounded-md border border-border/60 bg-muted/30 p-3"
                  aria-busy="true"
                  aria-live="polite"
                >
                  <div className="flex items-center gap-2.5">
                    <Loader2
                      className="h-4 w-4 shrink-0 animate-spin text-primary"
                      aria-hidden
                    />
                    <span className="text-xs font-medium text-foreground">Importing…</span>
                  </div>
                  <div
                    className="relative h-2 w-full overflow-hidden rounded-full bg-muted"
                    role="progressbar"
                    aria-label="Import in progress"
                  >
                    <div
                      className="absolute left-0 top-0 h-full w-2/5 rounded-full bg-primary animate-import-indeterminate"
                      aria-hidden
                    />
                  </div>
                </div>
              )}

              {importError && (
                <p className="text-sm text-destructive" role="alert">
                  {importError}
                </p>
              )}

              <div className="flex flex-wrap justify-end gap-2 pt-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={importBusy}
                  onClick={() => {
                    setImportOpen(false);
                    resetImportForm();
                  }}
                >
                  Cancel
                </Button>
                <Button type="button" size="sm" disabled={importBusy} onClick={() => void runImport()}>
                  {importBusy ? "Working…" : "Start import"}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {deleteTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-dialog-title"
        >
          <Card className="w-full max-w-md border-destructive/40 shadow-xl">
            <CardHeader>
              <CardTitle id="delete-dialog-title" className="flex items-center gap-2 text-destructive">
                <Trash2 className="h-5 w-5" />
                Delete dataset
              </CardTitle>
              <CardDescription>
                Permanently delete <span className="font-mono text-foreground">{deleteTarget.slug}</span>{" "}
                <span className="text-foreground">({deleteTarget.name})</span>? This action cannot be undone.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                <li>
                  Database: deletes <code className="font-mono">datasets</code> and cascades to{" "}
                  <code className="font-mono">
                    runs / proteins / proteoforms / identification_matches / protein_relation_mapping
                  </code>
                  .
                </li>
                <li>
                  Disk: removes folder <code className="font-mono">{deleteTarget.source_path || "—"}</code> (only if it
                  is under server <code className="font-mono">DATA_ROOT</code>).
                </li>
                <li>If there is an active import job for this slug, the backend will refuse the deletion (409).</li>
              </ul>

              {deleteError && (
                <p className="text-sm text-destructive" role="alert">
                  {deleteError}
                </p>
              )}

              <div className="flex flex-wrap justify-end gap-2 pt-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={deleteBusy}
                  onClick={() => {
                    setDeleteTarget(null);
                    setDeleteError(null);
                  }}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  disabled={deleteBusy}
                  onClick={() => void runDelete()}
                >
                  {deleteBusy ? "Deleting…" : "Delete permanently"}
                </Button>
              </div>
            </CardContent>
          </Card>
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
