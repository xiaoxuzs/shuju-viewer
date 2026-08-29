/**
 * Datasets list with a local-only browser upload entrypoint.
 */
import { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Activity,
  Database,
  FileText,
  FolderOpen,
  Layers,
  ListTree,
  Trash2,
  Bot,
} from "lucide-react";

import { deleteDataset, fetchDatasets } from "@/api/client";
import type { DatasetOut } from "@/api/types";
import { DataLoadError } from "@/components/common/data-state";
import { PageLoading } from "@/components/common/page-loading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/common/page-header";
import { ImportUploadDialog } from "@/features/import-upload/ImportUploadDialog";
import { TransitionLink, usePageTransitionReady } from "@/features/page-transition";
import { parseApiError } from "@/lib/apiError";
import { cn } from "@/lib/utils";
import { isSpectraOnlyDataset } from "@/features/spectra-only/utils";
import { DIACLIP_DISPLAY_NAME, formatSourceSoftwareName, getBuDatasetDisplayDescription } from "@/features/bu/utils";

function analysisModeLabel(ds: DatasetOut): string {
  if (isSpectraOnlyDataset(ds)) return "Spectra";
  return ds.analysis_mode === "BOTTOM_UP" ? "Bottom-Up" : "Top-Down";
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
  usePageTransitionReady(!isLoading);

  const [importOpen, setImportOpen] = useState(false);

  // Delete dialog state
  const [deleteTarget, setDeleteTarget] = useState<DatasetOut | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteBlockedByImport, setDeleteBlockedByImport] = useState(false);

  const runDelete = useCallback(
    async (cancelImport = false) => {
      if (!deleteTarget) return;
      setDeleteError(null);
      setDeleteBusy(true);
      try {
        await deleteDataset(deleteTarget.slug, { cancelImport });
        await queryClient.invalidateQueries({ queryKey: ["datasets"] });
        setDeleteTarget(null);
        setDeleteBlockedByImport(false);
      } catch (error) {
        const parsed = parseApiError(error);
        if (!cancelImport && parsed.status === 409) {
          setDeleteBlockedByImport(true);
          setDeleteError(
            "An import job is still queued or running for this dataset. Cancel the import and delete, or wait for it to finish.",
          );
        } else {
          setDeleteError(parsed.message ?? "Failed to delete dataset.");
        }
      } finally {
        setDeleteBusy(false);
      }
    },
    [deleteTarget, queryClient],
  );

  return (
    <>
      <PageHeader
        title="Datasets"
        description="Pick a dataset to start exploring proteins, proteoforms, PrSMs and spectra."
        actions={
          <div className="flex flex-wrap justify-end gap-2">
            <Button asChild variant="outline" size="sm">
              <TransitionLink to="/agent-import-cases">
                <Bot className="h-4 w-4" />
                Agent cases
              </TransitionLink>
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => setImportOpen(true)}>
              <FolderOpen className="h-4 w-4" />
              Upload local dataset
            </Button>
          </div>
        }
      />

      {isLoading && <PageLoading />}

      {error && !data && <DataLoadError message="Failed to load datasets." />}

      {data && data.length === 0 && (
        <Card>
          <CardContent className="p-10 text-center text-sm text-muted-foreground">
            No datasets have been imported yet. Choose <strong>Upload local dataset</strong> to upload RAW, mzML,
            TopPIC, PrSM, DIA-NN, or {DIACLIP_DISPLAY_NAME} data from this computer.
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
            const isSpectraOnly = isSpectraOnlyDataset(ds);
            const qValueCutoff = metadataNumber(ds, "q_value_cutoff");
            const buRunCount = ds.bu_runs?.length ?? 0;
            const spectraRunCount = ds.runs?.length ?? 0;
            const spectraFormat = ds.runs?.[0]?.raw_format ?? "mzML";
            return (
              <TransitionLink
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
                        <Badge variant={isBottomUp ? "default" : "secondary"}>{analysisModeLabel(ds)}</Badge>
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
                            setDeleteBlockedByImport(false);
                            setDeleteTarget(ds);
                          }}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                        <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1 group-hover:text-primary" />
                      </div>
                    </div>
                    <CardTitle className="mt-3 text-xl">{ds.name}</CardTitle>
                    {ds.description && (
                      <CardDescription>
                        {isBottomUp ? getBuDatasetDisplayDescription(ds) : ds.description}
                      </CardDescription>
                    )}
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {isSpectraOnly ? (
                      <>
                        <div className="grid grid-cols-3 gap-2 text-xs">
                          <Metric icon={<FileText className="h-3.5 w-3.5" />} label="Runs" value={spectraRunCount} />
                          <Metric icon={<Layers className="h-3.5 w-3.5" />} label="Format" value={spectraFormat} />
                          <Metric
                            icon={<ListTree className="h-3.5 w-3.5" />}
                            label="Source"
                            value={ds.source_software ?? "mzML"}
                          />
                        </div>
                        <div className="flex flex-wrap gap-1.5 pt-1">
                          <Badge variant="outline">No identifications</Badge>
                          {ds.runs?.map((run) => (
                            <Badge key={run.run_id} variant="secondary" className="font-mono text-[10px]">
                              {run.raw_format ?? "mzml"}
                            </Badge>
                          ))}
                        </div>
                      </>
                    ) : isBottomUp ? (
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
                            value={formatSourceSoftwareName(ds.source_software) ?? "Bottom-Up DIA"}
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
              </TransitionLink>
            );
          })}
        </div>
      )}

      <ImportUploadDialog open={importOpen} onOpenChange={setImportOpen} />
      {deleteTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-overlay/65 p-4 backdrop-blur-sm"
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
                <li>Associated dataset records are removed permanently.</li>
                <li>
                  If an import job is still running, deletion is blocked until you cancel the import or it finishes.
                </li>
              </ul>

              {deleteBlockedByImport && (
                <p className="text-sm text-muted-foreground">
                  Use <strong className="text-foreground">Cancel import and delete</strong> to stop any queued or
                  running import for this slug, then remove the dataset from the database.
                </p>
              )}

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
                    setDeleteBlockedByImport(false);
                  }}
                >
                  Cancel
                </Button>
                {deleteBlockedByImport ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="destructive"
                    disabled={deleteBusy}
                    onClick={() => void runDelete(true)}
                  >
                    {deleteBusy ? "Deleting…" : "Cancel import and delete"}
                  </Button>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    variant="destructive"
                    disabled={deleteBusy}
                    onClick={() => void runDelete(false)}
                  >
                    {deleteBusy ? "Deleting…" : "Delete permanently"}
                  </Button>
                )}
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
