const IMPORT_STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  adapt: "Running PFMB adaptation",
  fingerprint: "Computing dataset fingerprint",
  init: "Initializing import",
  proteins: "Importing proteins",
  proteoforms: "Importing proteoforms",
  matches: "Importing identifications",
  finalize: "Finalizing",
  success: "Import complete",
  failed: "Import failed",
};

export function formatImportStageLabel(stage: string | null, stageLabel: string | null): string {
  if (stage && IMPORT_STAGE_LABELS[stage]) return IMPORT_STAGE_LABELS[stage];
  if (stageLabel && stageLabel.trim()) return stageLabel;
  return "Importing…";
}

export function clampImportProgress(progress: number | null | undefined): number {
  if (progress === null || progress === undefined || Number.isNaN(progress)) return 0;
  return Math.max(0, Math.min(100, progress));
}
