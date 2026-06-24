/**
 * Datasets list: imported dataset cards; local folder path import; empty state still points to the ingest CLI.
 */
import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Activity,
  Database,
  FileText,
  FolderOpen,
  Layers,
  ListTree,
  Loader2,
  Trash2,
} from "lucide-react";

import { deleteDataset, enqueueImport, fetchDatasets, fetchImportJob, pickImportFolder } from "@/api/client";
import type { DatasetOut, ImportJobOut } from "@/api/types";
import { DataLoadError } from "@/components/common/data-state";
import { PageLoading } from "@/components/common/page-loading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/common/page-header";
import { Input } from "@/components/ui/input";
import { parseApiError } from "@/lib/apiError";
import { clampImportProgress, formatImportStageLabel } from "@/lib/importStages";
import { basenamePath, slugifyFolderName } from "@/lib/serverPathFromDirectoryInput";
import { cn } from "@/lib/utils";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function analysisModeLabel(mode: DatasetOut["analysis_mode"]): string {
  return mode === "BOTTOM_UP" ? "Bottom-Up" : "Top-Down";
}

function statusLabel(status: string | null): string {
  if (!status) return "unknown";
  const normalized = status.toLowerCase();
  const labels: Record<string, string> = {
    ready: "Ready",
    importing: "Importing",
    failed: "Failed",
  };
  return labels[normalized] ?? status;
}

function statusVariant(status: string | null): "outline" | "secondary" | "success" | "destructive" {
  const normalized = status?.toLowerCase();
  if (normalized === "ready") return "success";
  if (normalized === "failed") return "destructive";
  if (normalized === "importing") return "secondary";
  return "outline";
}

function importFailureMessage(detail: string | null | undefined): string {
  return detail ? `Failed to import dataset: ${detail}` : "Failed to import dataset.";
}

function metadataNumber(ds: DatasetOut, key: string): number | null {
  const value = ds.extra_metadata?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function DatasetsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["datasets"],
    queryFn: fetchDatasets,
  });

  const [importOpen, setImportOpen] = useState(false);
  const [sourcePath, setSourcePath] = useState("");
  const [slug, setSlug] = useState("");
  const [dsName, setDsName] = useState("");
  const [description, setDescription] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const [currentImportJob, setCurrentImportJob] = useState<ImportJobOut | null>(null);
  const [folderPickBusy, setFolderPickBusy] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

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
    } catch {
      setDeleteError("Failed to delete dataset.");
    } finally {
      setDeleteBusy(false);
    }
  }, [deleteTarget, queryClient]);

  const resetImportForm = useCallback(() => {
    setSourcePath("");
    setSlug("");
    setDsName("");
    setDescription("");
    setImportError(null);
    setCurrentImportJob(null);
  }, []);

  const onBrowseFolder = useCallback(async () => {
    setImportError(null);
    setFolderPickBusy(true);
    try {
      const res = await pickImportFolder();
      if (res.cancelled || !res.path) return;
      setSourcePath(res.path);
      const leaf = basenamePath(res.path);
      setSlug((s) => (s.trim() ? s : slugifyFolderName(leaf)));
      setDsName((n) => (n.trim() ? n : leaf));
    } catch {
      setImportError("Failed to open folder picker.");
    } finally {
      setFolderPickBusy(false);
    }
  }, []);

  const runImport = useCallback(async () => {
    if (!sourcePath.trim() || !slug.trim() || !dsName.trim()) {
      setImportError("Please enter or browse to a dataset folder path, plus a slug and display name.");
      return;
    }
    setImportError(null);
    setImportBusy(true);
    setCurrentImportJob(null);
    try {
      const { job_id: jobId } = await enqueueImport({
        source_path: sourcePath.trim(),
        slug: slug.trim(),
        name: dsName.trim(),
        description: description.trim() || null,
      });

      for (;;) {
        const job = await fetchImportJob(jobId);
        setCurrentImportJob(job);
        if (job.status === "success") {
          await sleep(400);
          await queryClient.invalidateQueries({ queryKey: ["datasets"] });
          setImportBusy(false);
          setImportOpen(false);
          resetImportForm();
          return;
        }
        if (job.status === "failed") {
          setImportError(importFailureMessage(job.error ?? job.stage_detail));
          setImportBusy(false);
          return;
        }
        await sleep(900);
      }
    } catch (error) {
      setImportError(importFailureMessage(parseApiError(error).message));
      setImportBusy(false);
    }
  }, [description, dsName, queryClient, resetImportForm, slug, sourcePath]);

  return (
    <>
      <PageHeader
        title="Datasets"
        description="Pick a dataset to start exploring proteins, proteoforms, PrSMs and spectra."
        actions={
          <Button type="button" variant="outline" size="sm" onClick={() => setImportOpen(true)}>
            <FolderOpen className="h-4 w-4" />
            Import from folder
          </Button>
        }
      />

      {isLoading && <PageLoading />}

      {error && !data && <DataLoadError message="Failed to load datasets." />}

      {data && data.length === 0 && (
        <Card>
          <CardContent className="p-10 text-center text-sm text-muted-foreground">
            No datasets ingested yet. Use <strong>Import from folder</strong> for a TopPIC output directory on this
            machine, or run the universal-schema ingest CLI:
            <pre className="mt-3 overflow-x-auto rounded-md bg-muted/50 p-3 text-left text-xs">
{`cd back
uv run python -m app.ingest.universal_toppic_adapter ingest \\
    --root ..\\shuju\\MZ20160222DS_histone48_html \\
    --database-url "postgresql+psycopg://USER:PASS@localhost:5432/Universal_Viewer" \\
    --slug mz20160222ds_histone48 \\
    --name "MZ20160222DS_histone48" \\
    --mode full --replace`}
            </pre>
            <div className="mt-4 rounded-md border border-border/60 bg-muted/30 p-3 text-left">
              <div className="font-medium text-foreground">No Bottom-Up datasets available</div>
              <div className="mt-1">
                For DIA-NN data, choose an ingest root containing <strong>all_report.parquet</strong> plus mzML
                files or a Bruker <strong>.d</strong> directory. The parquet and spectra must live under the same
                selected root.
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {data && data.length > 0 && (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
          {data.map((ds) => {
            const totalProteins = ds.cutoffs.reduce((a, c) => a + c.protein_count, 0);
            const totalProteoforms = ds.cutoffs.reduce((a, c) => a + c.proteoform_count, 0);
            const totalPrsms = ds.cutoffs.reduce((a, c) => a + c.prsm_count, 0);
            const isBottomUp = ds.analysis_mode === "BOTTOM_UP";
            const qValueCutoff = metadataNumber(ds, "q_value_cutoff");
            const buRunCount = ds.bu_runs?.length ?? 0;
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
                          {isBottomUp ? <Activity className="h-5 w-5" /> : <Database className="h-5 w-5" />}
                        </div>
                        <Badge variant="outline">{ds.slug}</Badge>
                        <Badge variant={isBottomUp ? "default" : "secondary"}>{analysisModeLabel(ds.analysis_mode)}</Badge>
                        <Badge variant={statusVariant(ds.status)}>{statusLabel(ds.status)}</Badge>
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
                    {isBottomUp ? (
                      <>
                        <div className="grid grid-cols-3 gap-2 text-xs">
                          <Metric icon={<FileText className="h-3.5 w-3.5" />} label="Runs" value={buRunCount} />
                          <Metric
                            icon={<Layers className="h-3.5 w-3.5" />}
                            label="Q max"
                            value={qValueCutoff ?? "0.01"}
                          />
                          <Metric
                            icon={<ListTree className="h-3.5 w-3.5" />}
                            label="Software"
                            value={ds.source_software ?? "DIA-NN"}
                          />
                        </div>
                        <div className="flex flex-wrap gap-1.5 pt-1">
                          <Badge variant="outline">No cutoffs</Badge>
                          {ds.bu_runs?.map((run) => (
                            <Badge key={run.run_id} variant="secondary" className="font-mono text-[10px]">
                              {run.raw_format ?? "run"}
                            </Badge>
                          ))}
                        </div>
                      </>
                    ) : (
                      <>
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
                      </>
                    )}
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
              <CardTitle id="import-dialog-title">Import dataset from folder</CardTitle>
              <CardDescription>
                Pick the <strong>TopPIC output folder</strong> on this machine (you may select a wrapper folder; the
                backend finds the ingest root with <span className="font-mono">topfd</span> /{" "}
                <span className="font-mono">toppic_*_cutoff</span>). A metadata fingerprint is used for deduplication;
                files are not copied. <strong>Browse folder</strong> opens a native dialog on the same computer as the
                API (typical local setup); you can still paste a path manually.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="import-path">
                  Dataset folder path
                </label>
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                  <Input
                    id="import-path"
                    className="min-w-0 sm:flex-1"
                    placeholder="e.g. E:\\viewer\\shuju\\MyDataset"
                    value={sourcePath}
                    disabled={importBusy || folderPickBusy}
                    onChange={(e) => setSourcePath(e.target.value)}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="inline-flex shrink-0 items-center self-start sm:self-auto"
                    disabled={importBusy || folderPickBusy}
                    onClick={() => void onBrowseFolder()}
                  >
                    {folderPickBusy ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                        Picking…
                      </>
                    ) : (
                      "Browse folder…"
                    )}
                  </Button>
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="import-slug">
                  Slug (URL id)
                </label>
                <Input
                  id="import-slug"
                  placeholder="e.g. mz20160222ds_histone48"
                  value={slug}
                  disabled={importBusy || folderPickBusy}
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
                  disabled={importBusy || folderPickBusy}
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
                  disabled={importBusy || folderPickBusy}
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
                    <span className="text-xs font-medium text-foreground">
                      {formatImportStageLabel(currentImportJob?.stage ?? null, currentImportJob?.stage_label ?? null)}
                    </span>
                    <span className="ml-auto text-xs tabular-nums text-muted-foreground">
                      {clampImportProgress(currentImportJob?.progress).toFixed(0)}%
                    </span>
                  </div>
                  {currentImportJob?.stage_detail && (
                    <div className="text-xs text-muted-foreground">{currentImportJob.stage_detail}</div>
                  )}
                  <div
                    className="relative h-2 w-full overflow-hidden rounded-full bg-muted"
                    role="progressbar"
                    aria-label="Import in progress"
                    aria-valuenow={clampImportProgress(currentImportJob?.progress)}
                    aria-valuemin={0}
                    aria-valuemax={100}
                  >
                    <div
                      className="absolute left-0 top-0 h-full rounded-full bg-primary transition-all"
                      style={{ width: `${clampImportProgress(currentImportJob?.progress)}%` }}
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
                  disabled={importBusy || folderPickBusy}
                  onClick={() => {
                    setImportOpen(false);
                    resetImportForm();
                  }}
                >
                  Cancel
                </Button>
                <Button type="button" size="sm" disabled={importBusy || folderPickBusy} onClick={() => void runImport()}>
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
  value: React.ReactNode;
}) {
  const formattedValue = typeof value === "number" ? value.toLocaleString() : value;
  return (
    <div className="rounded-md border border-border/60 bg-muted/40 p-2">
      <div className="flex items-center gap-1 text-muted-foreground">
        {icon}
        <span className="uppercase tracking-wider">{label}</span>
      </div>
      <div className="mt-0.5 font-semibold text-foreground">{formattedValue}</div>
    </div>
  );
}
