import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileUp, FolderOpen, Loader2, RotateCcw, X } from "lucide-react";

import {
  ImportUploadRequestError,
  createImportUpload,
  deleteImportUpload,
  fetchImportJob,
  getImportUpload,
  startImportUpload,
  uploadImportFile,
} from "@/api/client";
import type { ImportJobOut, ImportUploadType } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  clearActiveImportJob,
  loadActiveImportJob,
  saveActiveImportJob,
  type ActiveImportJobRecord,
} from "@/features/import-upload/activeImportJob";
import {
  ImportFileSelectionError,
  calculateWindowedSpeed,
  formatBytes,
  formatUploadSpeed,
  preflightDiaclipSelection,
  previewImportFiles,
  selectImportFiles,
  uploadFilesThenStart,
  type DiaclipSelectionCheck,
  type SelectedUploadSummary,
  type SpeedSample,
  type UploadProgressSnapshot,
  type UploadSelectionMode,
} from "@/features/import-upload/importUploadFiles";
import { parseApiError } from "@/lib/apiError";
import { clampImportProgress, formatImportStageLabel } from "@/lib/importStages";
import { cn } from "@/lib/utils";
import { TransitionLink } from "@/features/page-transition";

type UploadUiState =
  | "idle"
  | "creating-session"
  | "uploading"
  | "starting-import"
  | "import-running"
  | "success"
  | "failed"
  | "cancelled";

interface UploadUiError {
  title: string;
  message: string;
  code: string | null;
  fileName: string | null;
}

interface ImportUploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface DirectoryInputAttributes {
  webkitdirectory: "";
}

type AnalysisType = "TOP_DOWN" | "BOTTOM_UP" | "DDA";

interface ImportTypeOption {
  value: ImportUploadType;
  label: string;
  help: string;
}

const DIRECTORY_INPUT_ATTRIBUTES: DirectoryInputAttributes = { webkitdirectory: "" };
const FILE_PREVIEW_LIMIT = 8;
const IMPORT_JOB_POLL_MS = 900;
const INTERRUPTED_UPLOAD_KEY = "viewer.interruptedImportUpload";

const ANALYSIS_TYPES: Array<{
  value: AnalysisType;
  label: string;
  help: string;
}> = [
  { value: "TOP_DOWN", label: "Top-Down", help: "Intact proteoform and TopPIC data" },
  { value: "BOTTOM_UP", label: "Bottom-Up", help: "DIA identification result data" },
  { value: "DDA", label: "DDA", help: "Data-dependent acquisition from Thermo RAW spectra" },
];

const IMPORT_TYPES_BY_ANALYSIS: Record<AnalysisType, ImportTypeOption[]> = {
  TOP_DOWN: [
    { value: "TD_RAW", label: "Thermo RAW", help: "Top-Down Thermo .raw spectra" },
    { value: "TD_MZML", label: "mzML", help: "Top-Down .mzML spectra" },
    { value: "TD_TOPPIC_HTML", label: "TopPIC HTML Output", help: "A complete TopPIC HTML result folder" },
    { value: "TD_PRSM_BUNDLE", label: "PrSM Detail Bundle", help: "Viewer-ready PrSM detail files with mzML spectra" },
    {
      value: "TD_TOPPIC_NATIVE",
      label: "TopPIC Native Output",
      help: "TopPIC PrSM XML and TopFD MSAlign files; Viewer generates PrSM details during import",
    },
  ],
  BOTTOM_UP: [
    { value: "BU_DIA_NN", label: "DIA-NN", help: "A DIA-NN result folder" },
    {
      value: "BU_DIA_CLIP",
      label: "DIA-CLIP",
      help: "DIA-CLIP v1 TSV plus an all_report.parquet context report and one matching spectrum run",
    },
  ],
  DDA: [
    { value: "DDA_RAW", label: "Thermo RAW", help: "DDA Thermo .raw spectra" },
  ],
};

const BLOCKING_LEAVE_STATES = new Set<UploadUiState>([
  "creating-session",
  "uploading",
  "starting-import",
]);

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function importFailureMessage(detail: string | null | undefined): string {
  if (!detail) return "The import job failed.";
  if (detail.includes("raw_converter_missing")) return `RAW converter is not configured. ${detail}`;
  if (detail.includes("raw_conversion_timeout")) return `RAW conversion timed out. ${detail}`;
  return detail;
}

function stageTitle(state: UploadUiState, job: ImportJobOut | null): string {
  if (state === "creating-session") return "Creating upload session";
  if (state === "uploading") return "Uploading local files";
  if (state === "starting-import") return "Creating import task";
  if (state === "import-running") return job?.status === "running" ? "Importing" : "Waiting for processing";
  if (state === "success") return "Import complete";
  if (state === "failed") return "Import failed";
  if (state === "cancelled") return "Upload cancelled";
  return "Ready to upload";
}

export function ImportUploadDialog({ open, onOpenChange }: ImportUploadDialogProps) {
  const queryClient = useQueryClient();
  const [analysisType, setAnalysisType] = useState<AnalysisType | null>(null);
  const [importType, setImportType] = useState<ImportUploadType | null>(null);
  const [slug, setSlug] = useState("");
  const [datasetName, setDatasetName] = useState("");
  const [description, setDescription] = useState("");
  const [selection, setSelection] = useState<SelectedUploadSummary | null>(null);
  const [diaclipCheck, setDiaclipCheck] = useState<DiaclipSelectionCheck | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const [uiState, setUiState] = useState<UploadUiState>("idle");
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [currentJob, setCurrentJob] = useState<ImportJobOut | null>(null);
  const [uploadProgress, setUploadProgress] = useState<UploadProgressSnapshot | null>(null);
  const [uploadSpeed, setUploadSpeed] = useState(0);
  const [uiError, setUiError] = useState<UploadUiError | null>(null);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [recovered, setRecovered] = useState(false);

  const uploadIdRef = useRef<string | null>(null);
  const abortUploadRef = useRef<(() => void) | null>(null);
  const cancelRequestedRef = useRef(false);
  const pollTokenRef = useRef(0);
  const selectionTokenRef = useRef(0);
  const speedSamplesRef = useRef<SpeedSample[]>([]);

  const resetForNewUpload = useCallback(() => {
    pollTokenRef.current += 1;
    selectionTokenRef.current += 1;
    clearActiveImportJob(window.localStorage);
    window.sessionStorage.removeItem(INTERRUPTED_UPLOAD_KEY);
    uploadIdRef.current = null;
    abortUploadRef.current = null;
    cancelRequestedRef.current = false;
    speedSamplesRef.current = [];
    setSlug("");
    setDatasetName("");
    setDescription("");
    setAnalysisType(null);
    setImportType(null);
    setSelection(null);
    setDiaclipCheck(null);
    setInputKey((value) => value + 1);
    setUiState("idle");
    setUploadId(null);
    setJobId(null);
    setCurrentJob(null);
    setUploadProgress(null);
    setUploadSpeed(0);
    setUiError(null);
    setCancelBusy(false);
    setRecovered(false);
  }, []);

  const pollImportJob = useCallback(async (active: ActiveImportJobRecord) => {
    const token = ++pollTokenRef.current;
    for (;;) {
      try {
        const job = await fetchImportJob(active.job_id);
        if (token !== pollTokenRef.current) return;
        setCurrentJob(job);
        if (job.status === "success") {
          clearActiveImportJob(window.localStorage);
          setUiState("success");
          try {
            await queryClient.invalidateQueries({ queryKey: ["datasets"] });
          } catch {
            // The completed ImportJob remains successful even if the list refresh fails.
          }
          return;
        }
        if (job.status === "failed") {
          clearActiveImportJob(window.localStorage);
          setUiState("failed");
          setUiError({
            title: "ImportJob execution failed",
            message: importFailureMessage(job.error ?? job.stage_detail),
            code: null,
            fileName: null,
          });
          return;
        }
      } catch (error) {
        if (token !== pollTokenRef.current) return;
        const parsed = parseApiError(error);
        if (parsed.status === 404) clearActiveImportJob(window.localStorage);
        setUiState("failed");
        setUiError({
          title: parsed.status === 404 ? "Import task no longer exists" : "Could not restore import task",
          message: parsed.message ?? "Failed to query the import task.",
          code: parsed.code,
          fileName: null,
        });
        return;
      }
      await sleep(IMPORT_JOB_POLL_MS);
    }
  }, [queryClient]);

  useEffect(() => {
    const active = loadActiveImportJob(window.localStorage);
    if (!active) {
      const interrupted = window.sessionStorage.getItem(INTERRUPTED_UPLOAD_KEY) === "true";
      window.sessionStorage.removeItem(INTERRUPTED_UPLOAD_KEY);
      if (interrupted) {
        setUiState("failed");
        setUiError({
          title: "Previous local upload was interrupted",
          message: "Browser uploads cannot resume after a refresh. Select the local files again to restart.",
          code: null,
          fileName: null,
        });
        onOpenChange(true);
      }
      return;
    }
    window.sessionStorage.removeItem(INTERRUPTED_UPLOAD_KEY);
    setImportType(active.import_type);
    setUploadId(active.upload_id);
    uploadIdRef.current = active.upload_id;
    setJobId(active.job_id);
    setUiState("import-running");
    setRecovered(true);
    onOpenChange(true);
    void pollImportJob(active);
    return () => {
      pollTokenRef.current += 1;
    };
  }, [onOpenChange, pollImportJob]);

  useEffect(() => {
    if (BLOCKING_LEAVE_STATES.has(uiState)) {
      window.sessionStorage.setItem(INTERRUPTED_UPLOAD_KEY, "true");
      return;
    }
    window.sessionStorage.removeItem(INTERRUPTED_UPLOAD_KEY);
  }, [uiState]);

  useEffect(() => {
    if (!BLOCKING_LEAVE_STATES.has(uiState)) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [uiState]);

  const filePreview = useMemo(
    () => previewImportFiles(selection?.files ?? [], FILE_PREVIEW_LIMIT),
    [selection],
  );
  const importTypeOptions = analysisType ? IMPORT_TYPES_BY_ANALYSIS[analysisType] : [];
  const currentImportOption = importTypeOptions.find((option) => option.value === importType);
  const rawImport = importType === "TD_RAW" || importType === "DDA_RAW";
  const supportsFileSelection = rawImport || importType === "TD_MZML";
  const controlsDisabled = BLOCKING_LEAVE_STATES.has(uiState)
    || uiState === "import-running"
    || uploadId !== null
    || jobId !== null
    || cancelBusy;
  const canCancelUpload = jobId === null && (
    BLOCKING_LEAVE_STATES.has(uiState)
    || (uploadId !== null && uiState === "failed")
  );

  const selectFiles = useCallback(async (event: ChangeEvent<HTMLInputElement>, mode: UploadSelectionMode) => {
    const token = ++selectionTokenRef.current;
    try {
      if (!importType) throw new ImportFileSelectionError("Select an import format first.");
      const next = selectImportFiles(event.target.files ?? [], mode, importType);
      const nextDiaclipCheck = importType === "BU_DIA_CLIP"
        ? await preflightDiaclipSelection(next.files)
        : null;
      if (token !== selectionTokenRef.current) return;
      setSelection(next);
      setDiaclipCheck(nextDiaclipCheck);
      setUiError(null);
      setUiState("idle");
    } catch (error) {
      if (token !== selectionTokenRef.current) return;
      setSelection(null);
      setDiaclipCheck(null);
      setUiError({
        title: "Local file selection failed",
        message: error instanceof ImportFileSelectionError ? error.message : "Could not read the selected files.",
        code: null,
        fileName: null,
      });
    }
  }, [importType]);

  const publishProgress = useCallback((snapshot: UploadProgressSnapshot) => {
    const now = performance.now();
    const recent = speedSamplesRef.current.filter((sample) => sample.timestampMs >= now - 3_000);
    recent.push({ timestampMs: now, uploadedBytes: snapshot.overallUploadedBytes });
    speedSamplesRef.current = recent;
    setUploadProgress(snapshot);
    setUploadSpeed(calculateWindowedSpeed(recent));
  }, []);

  const finishCancellation = useCallback(() => {
    uploadIdRef.current = null;
    abortUploadRef.current = null;
    cancelRequestedRef.current = true;
    speedSamplesRef.current = [];
    setUploadId(null);
    setJobId(null);
    setCurrentJob(null);
    setUploadProgress(null);
    setUploadSpeed(0);
    setUiError(null);
    setCancelBusy(false);
    setUiState("cancelled");
  }, []);

  const cancelUpload = useCallback(async () => {
    if (jobId !== null) return;
    cancelRequestedRef.current = true;
    setCancelBusy(true);
    abortUploadRef.current?.();
    const managedUploadId = uploadIdRef.current;
    if (!managedUploadId) return;
    try {
      await deleteImportUpload(managedUploadId);
      finishCancellation();
    } catch (error) {
      const parsed = parseApiError(error);
      try {
        const status = await getImportUpload(managedUploadId);
        if (status.job_id) {
          const active: ActiveImportJobRecord = {
            job_id: status.job_id,
            import_type: status.import_type,
            upload_id: status.upload_id,
            created_at: status.started_at ?? status.created_at,
          };
          saveActiveImportJob(window.localStorage, active);
          setJobId(status.job_id);
          setUiState("import-running");
          setCancelBusy(false);
          cancelRequestedRef.current = false;
          void pollImportJob(active);
          return;
        }
      } catch {
        // Preserve the original DELETE failure below.
      }
      setCancelBusy(false);
      setUiState("failed");
      setUiError({
        title: "Could not cancel upload",
        message: parsed.message ?? "The upload session could not be deleted.",
        code: parsed.code,
        fileName: null,
      });
    }
  }, [finishCancellation, jobId, pollImportJob]);

  const runUpload = useCallback(async () => {
    const selectedImportType = importType;
    if (!selectedImportType) {
      setUiError({ title: "No import format selected", message: "Select an analysis type and import format.", code: null, fileName: null });
      return;
    }
    if (!selection || selection.files.length === 0) {
      setUiError({ title: "No local files selected", message: "Select files before uploading.", code: null, fileName: null });
      return;
    }
    if (!slug.trim() || !datasetName.trim()) {
      setUiError({
        title: "Dataset information is incomplete",
        message: "Enter a slug and display name before uploading.",
        code: null,
        fileName: null,
      });
      return;
    }

    pollTokenRef.current += 1;
    cancelRequestedRef.current = false;
    speedSamplesRef.current = [];
    setUiError(null);
    setCurrentJob(null);
    setUploadProgress(null);
    setUploadSpeed(0);
    setRecovered(false);
    setUiState("creating-session");

    let currentFileName: string | null = null;
    let failureTitle = "Creating upload session failed";
    try {
      const created = await createImportUpload(selectedImportType);
      uploadIdRef.current = created.upload_id;
      setUploadId(created.upload_id);
      if (cancelRequestedRef.current) {
        try {
          await deleteImportUpload(created.upload_id);
          finishCancellation();
        } catch (error) {
          const parsed = parseApiError(error);
          setCancelBusy(false);
          setUiState("failed");
          setUiError({
            title: "Could not cancel upload",
            message: parsed.message ?? "The upload session could not be deleted.",
            code: parsed.code,
            fileName: null,
          });
        }
        return;
      }

      setUiState("uploading");
      const started = await uploadFilesThenStart(
        selection.files,
        async (entry, _index, onFileProgress) => {
          currentFileName = entry.relativePath;
          failureTitle = "File upload failed";
          const request = uploadImportFile(
            created.upload_id,
            entry.relativePath,
            entry.file,
            (loadedBytes) => onFileProgress(loadedBytes),
          );
          abortUploadRef.current = request.abort;
          await request.promise;
          abortUploadRef.current = null;
        },
        async () => {
          currentFileName = null;
          failureTitle = "Starting import failed";
          setUiState("starting-import");
          return startImportUpload(created.upload_id, {
            slug: slug.trim(),
            name: datasetName.trim(),
            description: description.trim() || null,
          });
        },
        publishProgress,
      );

      const active: ActiveImportJobRecord = {
        job_id: started.job_id,
        import_type: selectedImportType,
        upload_id: created.upload_id,
        created_at: new Date().toISOString(),
      };
      if (cancelRequestedRef.current) return;
      setJobId(started.job_id);
      saveActiveImportJob(window.localStorage, active);
      setUiState("import-running");
      await pollImportJob(active);
    } catch (error) {
      abortUploadRef.current = null;
      if (cancelRequestedRef.current) {
        if (!uploadIdRef.current) {
          setCancelBusy(false);
          setUiState("cancelled");
        }
        return;
      }
      const uploadError = error instanceof ImportUploadRequestError ? error : null;
      const parsed = uploadError ? null : parseApiError(error);
      setUiState("failed");
      setUiError({
        title: failureTitle,
        message: uploadError?.message ?? parsed?.message ?? "The upload request failed.",
        code: uploadError?.code ?? parsed?.code ?? null,
        fileName: currentFileName,
      });
    }
  }, [
    datasetName,
    description,
    finishCancellation,
    importType,
    pollImportJob,
    publishProgress,
    selection,
    slug,
  ]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay/65 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="import-upload-dialog-title"
    >
      <Card className="max-h-[94vh] w-full max-w-2xl overflow-y-auto border-border/80 shadow-xl">
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle id="import-upload-dialog-title">Upload local dataset</CardTitle>
              <CardDescription className="mt-1.5">
                Select local files or a folder. Files upload in order, then the existing import task starts automatically.
              </CardDescription>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Close upload dialog"
              disabled={BLOCKING_LEAVE_STATES.has(uiState) || cancelBusy}
              onClick={() => onOpenChange(false)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          <section className="space-y-2" aria-labelledby="import-type-title">
            <h3 id="import-type-title" className="text-sm font-semibold">1. Analysis type</h3>
            <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Analysis type">
              {ANALYSIS_TYPES.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={analysisType === option.value}
                  title={option.help}
                  disabled={controlsDisabled}
                  className={cn(
                    "rounded-md border px-3 py-2 text-sm font-medium transition-colors",
                    analysisType === option.value
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border bg-background hover:bg-muted",
                    "disabled:cursor-not-allowed disabled:border-border disabled:bg-disabled disabled:text-disabled-foreground",
                  )}
                  onClick={() => {
                    selectionTokenRef.current += 1;
                    setAnalysisType(option.value);
                    setImportType(null);
                    setSelection(null);
                    setDiaclipCheck(null);
                    setInputKey((value) => value + 1);
                    setUiError(null);
                  }}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              {ANALYSIS_TYPES.find((option) => option.value === analysisType)?.help
                ?? "Select an analysis type to view its supported import formats."}
            </p>
          </section>

          {analysisType && (
            <section className="space-y-2" aria-labelledby="import-format-title">
              <h3 id="import-format-title" className="text-sm font-semibold">2. Import format</h3>
              <div
                className="grid grid-cols-2 gap-2 sm:grid-cols-3"
                role="radiogroup"
                aria-label="Import format"
              >
                {importTypeOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={importType === option.value}
                    title={option.help}
                    disabled={controlsDisabled}
                    className={cn(
                      "rounded-md border px-3 py-2 text-sm font-medium transition-colors",
                      importType === option.value
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-background hover:bg-muted",
                      "disabled:cursor-not-allowed disabled:border-border disabled:bg-disabled disabled:text-disabled-foreground",
                    )}
                    onClick={() => {
                      selectionTokenRef.current += 1;
                      setImportType(option.value);
                      setSelection(null);
                      setDiaclipCheck(null);
                      setInputKey((value) => value + 1);
                      setUiError(null);
                    }}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              {currentImportOption && (
                <p className="text-xs text-muted-foreground">{currentImportOption.help}</p>
              )}
            {importType === "BU_DIA_CLIP" && (
              <div className="rounded-md border border-primary/30 bg-primary/5 p-3 text-xs text-muted-foreground">
                DIA-CLIP v1 is a single-run Bottom-Up import. Select one folder containing exactly one supported
                DIA-CLIP result TSV, exactly one required context report named{" "}
                <span className="font-mono">all_report.parquet</span>, and the matching{" "}
                <span className="font-mono">.raw</span>, <span className="font-mono">.mzML</span>, or Bruker{" "}
                <span className="font-mono">.d</span> spectrum source. The server validates this contract again
                before importing.
              </div>
            )}
            </section>
          )}

          {importType && (
            <>
              <section className="grid gap-3 sm:grid-cols-2" aria-labelledby="dataset-info-title">
                <h3 id="dataset-info-title" className="text-sm font-semibold sm:col-span-2">3. Dataset information</h3>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground" htmlFor="import-slug">Slug (URL id)</label>
                  <Input
                    id="import-slug"
                    value={slug}
                    disabled={controlsDisabled}
                    placeholder="e.g. histone_sample"
                    onChange={(event) => setSlug(event.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground" htmlFor="import-name">Display name</label>
                  <Input
                    id="import-name"
                    value={datasetName}
                    disabled={controlsDisabled}
                    placeholder="Human-readable name"
                    onChange={(event) => setDatasetName(event.target.value)}
                  />
                </div>
                <div className="space-y-1.5 sm:col-span-2">
                  <label className="text-xs font-medium text-muted-foreground" htmlFor="import-description">
                    Description (optional)
                  </label>
                  <textarea
                    id="import-description"
                    rows={2}
                    value={description}
                    disabled={controlsDisabled}
                    placeholder="Optional notes"
                    onChange={(event) => setDescription(event.target.value)}
                    className={cn(
                      "flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      "disabled:cursor-not-allowed disabled:border-border disabled:bg-disabled disabled:text-disabled-foreground",
                    )}
                  />
                </div>
              </section>

              <section className="space-y-3" aria-labelledby="local-files-title">
                <h3 id="local-files-title" className="text-sm font-semibold">4. Local files</h3>
                <div className="flex flex-wrap gap-2">
                  {supportsFileSelection && (
                    <label className={cn(buttonVariants({ variant: "outline", size: "sm" }), controlsDisabled && "pointer-events-none opacity-50")}>
                      <FileUp className="h-4 w-4" />
                      Select {rawImport ? ".raw" : ".mzML"} files
                      <input
                        key={`files-${inputKey}`}
                        id="import-files"
                        type="file"
                        multiple
                        accept={rawImport ? ".raw" : ".mzML,.mzml"}
                        disabled={controlsDisabled}
                        className="sr-only"
                        onChange={(event) => void selectFiles(event, "files")}
                      />
                    </label>
                  )}
                  <label className={cn(buttonVariants({ variant: "outline", size: "sm" }), controlsDisabled && "pointer-events-none opacity-50")}>
                    <FolderOpen className="h-4 w-4" />
                    Select folder
                    <input
                      {...DIRECTORY_INPUT_ATTRIBUTES}
                      key={`folder-${inputKey}`}
                      id="import-folder"
                      type="file"
                      multiple
                      disabled={controlsDisabled}
                      className="sr-only"
                      onChange={(event) => void selectFiles(event, "folder")}
                    />
                  </label>
                </div>

                {selection && (
                  <div className="space-y-2 rounded-md border border-border/60 bg-muted/30 p-3">
                    <div className="flex flex-wrap gap-2 text-xs">
                      <Badge variant="outline">{selection.mode === "folder" ? "Folder" : "Files"}</Badge>
                      <span>{selection.rootLabel}</span>
                      <span>{selection.files.length.toLocaleString()} files</span>
                      <span>{formatBytes(selection.totalBytes)}</span>
                    </div>
                    <ul className="space-y-1 text-xs text-muted-foreground" aria-label="Selected file summary">
                      {filePreview.visible.map((entry) => (
                        <li key={entry.relativePath} className="flex justify-between gap-3">
                          <span className="min-w-0 truncate font-mono">{entry.relativePath}</span>
                          <span className="shrink-0 tabular-nums">{formatBytes(entry.file.size)}</span>
                        </li>
                      ))}
                    </ul>
                    {filePreview.remaining > 0 && (
                      <p className="text-xs text-muted-foreground">+ {filePreview.remaining.toLocaleString()} more files</p>
                    )}
                  </div>
                )}
                {diaclipCheck && (
                  <div className="rounded-md border border-primary/40 bg-primary/5 p-3 text-xs">
                    <div className="font-semibold text-primary">DIA-CLIP v1 preflight passed</div>
                    <dl className="mt-2 grid gap-1 text-muted-foreground">
                      <div><dt className="inline font-medium">Result TSV: </dt><dd className="inline font-mono">{diaclipCheck.resultPath}</dd></div>
                      <div><dt className="inline font-medium">Context report: </dt><dd className="inline font-mono">{diaclipCheck.reportPath}</dd></div>
                      <div><dt className="inline font-medium">Spectrum sources: </dt><dd className="inline">{diaclipCheck.spectraSources.length}</dd></div>
                    </dl>
                  </div>
                )}
              </section>
            </>
          )}

          {(uiState !== "idle" || recovered) && (
            <section className="space-y-3 rounded-md border border-border/60 bg-muted/20 p-3" aria-live="polite">
              <div className="flex items-center gap-2">
                {(BLOCKING_LEAVE_STATES.has(uiState) || uiState === "import-running") && (
                  <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden />
                )}
                <span className="text-sm font-semibold">{stageTitle(uiState, currentJob)}</span>
                {recovered && <Badge variant="outline">Restored after refresh</Badge>}
              </div>

              {uiState === "uploading" && uploadProgress && (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                    <ProgressMetric label="Current file" value={`${uploadProgress.currentFileIndex} / ${uploadProgress.totalFiles}`} />
                    <ProgressMetric label="File progress" value={`${uploadProgress.currentFilePercent.toFixed(0)}%`} />
                    <ProgressMetric
                      label="Uploaded"
                      value={`${formatBytes(uploadProgress.overallUploadedBytes)} / ${formatBytes(uploadProgress.totalBytes)}`}
                    />
                    <ProgressMetric label="Speed" value={formatUploadSpeed(uploadSpeed)} />
                  </div>
                  <p className="truncate font-mono text-xs text-muted-foreground">{uploadProgress.currentFileName}</p>
                  <ProgressBar label="Current file upload" value={uploadProgress.currentFilePercent} />
                  <ProgressBar label="Overall upload" value={uploadProgress.overallPercent} />
                </div>
              )}

              {(uiState === "import-running" || uiState === "success" || (uiState === "failed" && currentJob)) && (
                <div className="space-y-2">
                  <div className="flex justify-between gap-3 text-xs">
                    <span>{formatImportStageLabel(currentJob?.stage ?? null, currentJob?.stage_label ?? null)}</span>
                    <span className="tabular-nums">{clampImportProgress(currentJob?.progress).toFixed(0)}%</span>
                  </div>
                  {currentJob?.stage_detail && <p className="text-xs text-muted-foreground">{currentJob.stage_detail}</p>}
                  <ProgressBar label="Import progress" value={clampImportProgress(currentJob?.progress)} />
                </div>
              )}
            </section>
          )}

          {uiError && (
            <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm" role="alert">
              <div className="font-semibold text-destructive">{uiError.title}</div>
              {uiError.fileName && <div className="mt-1 font-mono text-xs">{uiError.fileName}</div>}
              <div className="mt-1 text-muted-foreground">{uiError.message}</div>
              {uiError.code && <div className="mt-1 font-mono text-xs text-destructive">{uiError.code}</div>}
            </div>
          )}

          <div className="flex flex-wrap justify-end gap-2 pt-1">
            {canCancelUpload && (
              <Button type="button" variant="outline" size="sm" disabled={cancelBusy} onClick={() => void cancelUpload()}>
                {cancelBusy ? "Cancelling upload..." : "Cancel upload"}
              </Button>
            )}
            {uiState === "success" && currentJob?.dataset_slug && (
              <Button asChild size="sm">
                <TransitionLink to={`/datasets/${currentJob.dataset_slug}`}>Open dataset</TransitionLink>
              </Button>
            )}
            {(
              uiState === "success"
              || uiState === "cancelled"
              || (uiState === "failed" && (jobId !== null || uploadId === null))
            ) && (
              <Button type="button" variant="outline" size="sm" onClick={resetForNewUpload}>
                <RotateCcw className="h-4 w-4" />
                Start another upload
              </Button>
            )}
            {uiState === "import-running" && (
              <Button type="button" variant="ghost" size="sm" onClick={() => onOpenChange(false)}>Hide status</Button>
            )}
            {uiState === "idle" && (
              <Button
                type="button"
                size="sm"
                disabled={!importType || !selection || !slug.trim() || !datasetName.trim()}
                onClick={() => void runUpload()}
              >
                Start upload and import
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function ProgressMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/60 bg-background p-2">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-0.5 truncate font-medium tabular-nums">{value}</div>
    </div>
  );
}

function ProgressBar({ label, value }: { label: string; value: number }) {
  const safeValue = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  return (
    <div
      className="relative h-2 w-full overflow-hidden rounded-full bg-muted"
      role="progressbar"
      aria-label={label}
      aria-valuenow={safeValue}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className="absolute inset-y-0 left-0 rounded-full bg-primary transition-all" style={{ width: `${safeValue}%` }} />
    </div>
  );
}
