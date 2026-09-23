const IMPORT_STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  fingerprint: "Computing dataset fingerprint",
  raw_conversion: "Converting RAW to mzML",
  init: "Initializing import",
  proteins: "Importing proteins",
  proteoforms: "Importing proteoforms",
  matches: "Importing identification results",
  finalize: "Finalizing dataset",
  success: "Import complete",
  failed: "Import failed",
};

export function formatImportStageLabel(stage: string | null, _stageLabel: string | null): string {
  if (stage && IMPORT_STAGE_LABELS[stage]) return IMPORT_STAGE_LABELS[stage];
  return "Importing...";
}

export function clampImportProgress(progress: number | null | undefined): number {
  if (progress === null || progress === undefined || Number.isNaN(progress)) return 0;
  return Math.max(0, Math.min(100, progress));
}
