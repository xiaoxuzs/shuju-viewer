import type { ImportUploadType } from "@/api/types";

export const ACTIVE_IMPORT_JOB_KEY = "viewer.activeImportJob";

export interface ActiveImportJobRecord {
  job_id: string;
  import_type: ImportUploadType;
  upload_id: string;
  created_at: string;
}

type StorageAccess = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const IMPORT_TYPES = new Set<ImportUploadType>([
  "TD_RAW",
  "TD_MZML",
  "TD_TOPPIC_HTML",
  "TD_PRSM_BUNDLE",
  "TD_TOPPIC_NATIVE",
  "BU_DIA_NN",
  "BU_DIA_CLIP",
  "DDA_RAW",
  "RAW_ONLY",
  "MZML_ONLY",
  "TOPPIC",
  "PRSM",
  "TD_TOPPIC_NATIVE",
  "DIA_NN",
  "DIA_CLIP",
]);

export function parseActiveImportJob(value: string | null): ActiveImportJobRecord | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value) as Record<string, unknown>;
    if (
      typeof parsed.job_id !== "string"
      || !parsed.job_id.trim()
      || typeof parsed.upload_id !== "string"
      || !parsed.upload_id.trim()
      || typeof parsed.import_type !== "string"
      || !IMPORT_TYPES.has(parsed.import_type as ImportUploadType)
      || typeof parsed.created_at !== "string"
      || !Number.isFinite(Date.parse(parsed.created_at))
    ) {
      return null;
    }
    return parsed as unknown as ActiveImportJobRecord;
  } catch {
    return null;
  }
}

export function loadActiveImportJob(storage: StorageAccess): ActiveImportJobRecord | null {
  const raw = storage.getItem(ACTIVE_IMPORT_JOB_KEY);
  const record = parseActiveImportJob(raw);
  if (raw && !record) storage.removeItem(ACTIVE_IMPORT_JOB_KEY);
  return record;
}

export function saveActiveImportJob(storage: StorageAccess, record: ActiveImportJobRecord): void {
  storage.setItem(ACTIVE_IMPORT_JOB_KEY, JSON.stringify(record));
}

export function clearActiveImportJob(storage: StorageAccess): void {
  storage.removeItem(ACTIVE_IMPORT_JOB_KEY);
}
