import type { ImportUploadType } from "@/api/types";

export type UploadSelectionMode = "files" | "folder";

export interface SelectedUploadFile {
  file: File;
  relativePath: string;
}

export interface SelectedUploadSummary {
  files: SelectedUploadFile[];
  totalBytes: number;
  rootLabel: string;
  mode: UploadSelectionMode;
}

export interface UploadProgressSnapshot {
  currentFileName: string;
  currentFileIndex: number;
  totalFiles: number;
  currentFileLoadedBytes: number;
  currentFileTotalBytes: number;
  currentFilePercent: number;
  completedBytes: number;
  overallUploadedBytes: number;
  totalBytes: number;
  overallPercent: number;
}

export interface SpeedSample {
  timestampMs: number;
  uploadedBytes: number;
}

export class ImportFileSelectionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ImportFileSelectionError";
  }
}

export const DIACLIP_REQUIRED_COLUMNS = [
  "label",
  "score",
  "feature_distance",
  "cos_similarity",
  "modified_peptide",
  "charge",
  "quant_result",
] as const;

export interface DiaclipSelectionCheck {
  resultPath: string;
  reportPath: string;
  spectraSources: string[];
}

function expectedExtension(importType: ImportUploadType): string | null {
  if (importType === "RAW_ONLY") return ".raw";
  if (importType === "MZML_ONLY") return ".mzml";
  return null;
}

export function selectImportFiles(
  input: Iterable<File>,
  mode: UploadSelectionMode,
  importType: ImportUploadType,
): SelectedUploadSummary {
  const source = Array.from(input);
  if (source.length === 0) throw new ImportFileSelectionError("Select at least one local file.");

  const seen = new Set<string>();
  const files = source.map((file) => {
    const browserRelativePath = file.webkitRelativePath;
    if (mode === "folder" && !browserRelativePath.trim()) {
      throw new ImportFileSelectionError("The selected folder did not preserve relative file paths.");
    }
    const relativePath = browserRelativePath || file.name;
    if (!relativePath.trim()) throw new ImportFileSelectionError("A selected file has an empty relative path.");
    if (seen.has(relativePath)) {
      throw new ImportFileSelectionError(`Duplicate relative path: ${relativePath}`);
    }
    seen.add(relativePath);
    return { file, relativePath };
  });

  const extension = expectedExtension(importType);
  if (extension) {
    const matching = files.filter(({ file }) => file.name.toLocaleLowerCase().endsWith(extension));
    if (mode === "files" && matching.length !== files.length) {
      throw new ImportFileSelectionError(`Only ${extension} files can be selected for this import type.`);
    }
    if (matching.length === 0) {
      throw new ImportFileSelectionError(`The selected folder does not contain any ${extension} files.`);
    }
  }

  const firstPath = files[0]!.relativePath;
  const rootLabel = mode === "folder" ? firstPath.split("/")[0] || "Selected folder" : "Selected files";
  return {
    files,
    totalBytes: files.reduce((sum, entry) => sum + entry.file.size, 0),
    rootLabel,
    mode,
  };
}

export async function preflightDiaclipSelection(
  files: SelectedUploadFile[],
): Promise<DiaclipSelectionCheck> {
  const reportFiles = files.filter(({ relativePath }) => (
    relativePath.split("/").at(-1)?.toLocaleLowerCase() === "all_report.parquet"
  ));
  if (reportFiles.length !== 1) {
    throw new ImportFileSelectionError(
      `DIA-CLIP requires exactly one all_report.parquet; found ${reportFiles.length}.`,
    );
  }

  const spectraSources = Array.from(new Set(files.flatMap(({ relativePath }) => {
    const normalized = relativePath.replaceAll("\\", "/");
    const lower = normalized.toLocaleLowerCase();
    if (lower.endsWith(".raw") || lower.endsWith(".mzml")) return [normalized];
    const brukerDirectory = normalized.split("/").find((part) => part.toLocaleLowerCase().endsWith(".d"));
    return brukerDirectory ? [brukerDirectory] : [];
  })));
  if (spectraSources.length === 0) {
    throw new ImportFileSelectionError(
      "DIA-CLIP requires one spectrum source: a .raw file, .mzML file, or Bruker .d directory.",
    );
  }

  const matchingResults: SelectedUploadFile[] = [];
  for (const entry of files) {
    if (!entry.relativePath.toLocaleLowerCase().endsWith(".tsv")) continue;
    const header = (await entry.file.slice(0, 65_536).text())
      .replace(/^\uFEFF/, "")
      .split(/\r?\n/, 1)[0] ?? "";
    const columns = new Set(header.split("\t").map((column) => column.trim()));
    if (DIACLIP_REQUIRED_COLUMNS.every((column) => columns.has(column))) {
      matchingResults.push(entry);
    }
  }
  if (matchingResults.length !== 1) {
    throw new ImportFileSelectionError(
      `DIA-CLIP requires exactly one TSV with the supported v1 header; found ${matchingResults.length}.`,
    );
  }

  return {
    resultPath: matchingResults[0]!.relativePath,
    reportPath: reportFiles[0]!.relativePath,
    spectraSources,
  };
}

export function previewImportFiles(files: SelectedUploadFile[], limit = 8): {
  visible: SelectedUploadFile[];
  remaining: number;
} {
  const safeLimit = Math.max(0, Math.floor(limit));
  return {
    visible: files.slice(0, safeLimit),
    remaining: Math.max(0, files.length - safeLimit),
  };
}

export function formatBytes(bytes: number): string {
  const safe = Number.isFinite(bytes) && bytes > 0 ? bytes : 0;
  if (safe < 1024) return `${Math.round(safe)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = safe / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value >= 10 ? value.toFixed(1) : value.toFixed(2)} ${units[unitIndex]}`;
}

export function formatUploadSpeed(bytesPerSecond: number): string {
  return `${formatBytes(bytesPerSecond)}/s`;
}

export function calculateWindowedSpeed(samples: SpeedSample[], windowMs = 3_000): number {
  if (samples.length < 2) return 0;
  const last = samples[samples.length - 1]!;
  const first = samples.find((sample) => sample.timestampMs >= last.timestampMs - windowMs) ?? samples[0]!;
  const elapsedSeconds = (last.timestampMs - first.timestampMs) / 1000;
  if (elapsedSeconds <= 0) return 0;
  return Math.max(0, (last.uploadedBytes - first.uploadedBytes) / elapsedSeconds);
}

export function createProgressSnapshot(
  entry: SelectedUploadFile,
  fileIndex: number,
  totalFiles: number,
  completedBytes: number,
  loadedBytes: number,
  totalBytes: number,
): UploadProgressSnapshot {
  const currentLoaded = Math.max(0, Math.min(entry.file.size, loadedBytes));
  const overallUploaded = Math.max(0, Math.min(totalBytes, completedBytes + currentLoaded));
  return {
    currentFileName: entry.relativePath,
    currentFileIndex: fileIndex + 1,
    totalFiles,
    currentFileLoadedBytes: currentLoaded,
    currentFileTotalBytes: entry.file.size,
    currentFilePercent: entry.file.size > 0 ? currentLoaded / entry.file.size * 100 : 100,
    completedBytes,
    overallUploadedBytes: overallUploaded,
    totalBytes,
    overallPercent: totalBytes > 0 ? overallUploaded / totalBytes * 100 : 100,
  };
}

export async function uploadFilesThenStart<T>(
  files: SelectedUploadFile[],
  uploadOne: (
    entry: SelectedUploadFile,
    index: number,
    onProgress: (loadedBytes: number) => void,
  ) => Promise<void>,
  startImport: () => Promise<T>,
  onProgress?: (snapshot: UploadProgressSnapshot) => void,
): Promise<T> {
  const totalBytes = files.reduce((sum, entry) => sum + entry.file.size, 0);
  let completedBytes = 0;
  for (let index = 0; index < files.length; index += 1) {
    const entry = files[index]!;
    const publish = (loadedBytes: number) => {
      onProgress?.(createProgressSnapshot(
        entry,
        index,
        files.length,
        completedBytes,
        loadedBytes,
        totalBytes,
      ));
    };
    publish(0);
    await uploadOne(entry, index, publish);
    completedBytes += entry.file.size;
    publish(entry.file.size);
  }
  return startImport();
}
