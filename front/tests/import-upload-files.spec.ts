import { expect, test } from "@playwright/test";

import {
  ACTIVE_IMPORT_JOB_KEY,
  clearActiveImportJob,
  loadActiveImportJob,
  parseActiveImportJob,
  saveActiveImportJob,
} from "../src/features/import-upload/activeImportJob";
import {
  ImportFileSelectionError,
  calculateWindowedSpeed,
  createProgressSnapshot,
  formatUploadSpeed,
  preflightDiaclipSelection,
  previewImportFiles,
  selectImportFiles,
  uploadFilesThenStart,
} from "../src/features/import-upload/importUploadFiles";

const DIACLIP_HEADER = [
  "label",
  "score",
  "feature_distance",
  "cos_similarity",
  "modified_peptide",
  "charge",
  "quant_result",
].join("\t");

test("single-file selection uses File.name and calculates total size", () => {
  const selected = selectImportFiles([
    fakeFile("first.mzML", 10),
    fakeFile("second.mzML", 25),
  ], "files", "TD_MZML");

  expect(selected.files.map((entry) => entry.relativePath)).toEqual(["first.mzML", "second.mzML"]);
  expect(selected.totalBytes).toBe(35);
  expect(selected.rootLabel).toBe("Selected files");
});

test("folder selection preserves webkitRelativePath", () => {
  const selected = selectImportFiles([
    fakeFile("sample.mzML", 8, "bundle/nested/sample.mzML"),
  ], "folder", "TD_MZML");

  expect(selected.files[0]?.relativePath).toBe("bundle/nested/sample.mzML");
  expect(selected.rootLabel).toBe("bundle");
});

test("empty, missing folder paths, and duplicate relative paths are rejected", () => {
  expect(() => selectImportFiles([], "files", "TD_MZML")).toThrow(ImportFileSelectionError);
  expect(() => selectImportFiles([fakeFile("a.mzML", 1)], "folder", "TD_MZML"))
    .toThrow("did not preserve relative file paths");
  expect(() => selectImportFiles([
    fakeFile("a.mzML", 1, "root/a.mzML"),
    fakeFile("a.mzML", 2, "root/a.mzML"),
  ], "folder", "TD_MZML")).toThrow("Duplicate relative path");
});

test("RAW and mzML file modes reject mismatched extensions", () => {
  expect(() => selectImportFiles([fakeFile("wrong.txt", 1)], "files", "DDA_RAW"))
    .toThrow("Only .raw files");
  expect(() => selectImportFiles([fakeFile("wrong.raw", 1)], "files", "TD_MZML"))
    .toThrow("Only .mzml files");
});

test("DIA-CLIP preflight is header-based and accepts an arbitrary result filename", async () => {
  const selected = selectImportFiles([
    textFile("renamed-output.tsv", `${DIACLIP_HEADER}\textra\n`, "bundle/results/renamed-output.tsv"),
    textFile("all_report.parquet", "", "bundle/all_report.parquet"),
    textFile("sample.raw", "", "bundle/sample.raw"),
  ], "folder", "BU_DIA_CLIP");

  await expect(preflightDiaclipSelection(selected.files)).resolves.toEqual({
    resultPath: "bundle/results/renamed-output.tsv",
    reportPath: "bundle/all_report.parquet",
    spectraSources: ["bundle/sample.raw"],
  });
});

test("DIA-CLIP preflight rejects a TSV without the supported v1 header", async () => {
  const selected = selectImportFiles([
    textFile("wrong.tsv", "modified_peptide\tcharge\n", "bundle/wrong.tsv"),
    textFile("all_report.parquet", "", "bundle/all_report.parquet"),
    textFile("sample.mzML", "", "bundle/sample.mzML"),
  ], "folder", "BU_DIA_CLIP");

  await expect(preflightDiaclipSelection(selected.files)).rejects.toThrow("supported v1 header");
});

test("large file summaries are truncated without losing the remaining count", () => {
  const files = Array.from({ length: 12 }, (_value, index) => ({
    file: fakeFile(`sample-${index}.mzML`, index + 1),
    relativePath: `sample-${index}.mzML`,
  }));
  expect(previewImportFiles(files, 8)).toMatchObject({
    visible: files.slice(0, 8),
    remaining: 4,
  });
});

test("uploads files strictly in order and starts only after all files complete", async () => {
  const files = [
    selectedFile("one.mzML", 4),
    selectedFile("two.mzML", 6),
    selectedFile("three.mzML", 2),
  ];
  const events: string[] = [];
  let activeUploads = 0;
  let maxActiveUploads = 0;

  const result = await uploadFilesThenStart(
    files,
    async (entry, _index, onProgress) => {
      activeUploads += 1;
      maxActiveUploads = Math.max(maxActiveUploads, activeUploads);
      events.push(`begin:${entry.relativePath}`);
      onProgress(entry.file.size / 2);
      await Promise.resolve();
      events.push(`end:${entry.relativePath}`);
      activeUploads -= 1;
    },
    async () => {
      events.push("start");
      return "job-one";
    },
  );

  expect(result).toBe("job-one");
  expect(maxActiveUploads).toBe(1);
  expect(events).toEqual([
    "begin:one.mzML", "end:one.mzML",
    "begin:two.mzML", "end:two.mzML",
    "begin:three.mzML", "end:three.mzML",
    "start",
  ]);
});

test("a failed file stops later uploads and does not start the import", async () => {
  const attempted: string[] = [];
  let started = false;
  await expect(uploadFilesThenStart(
    [selectedFile("one.mzML", 1), selectedFile("two.mzML", 1)],
    async (entry) => {
      attempted.push(entry.relativePath);
      throw new Error("upload failed");
    },
    async () => {
      started = true;
      return "job";
    },
  )).rejects.toThrow("upload failed");
  expect(attempted).toEqual(["one.mzML"]);
  expect(started).toBe(false);
});

test("file and overall progress accumulate completed bytes", () => {
  const snapshot = createProgressSnapshot(selectedFile("two.mzML", 6), 1, 2, 4, 3, 10);
  expect(snapshot).toMatchObject({
    currentFileIndex: 2,
    currentFileLoadedBytes: 3,
    currentFilePercent: 50,
    completedBytes: 4,
    overallUploadedBytes: 7,
    overallPercent: 70,
  });
});

test("upload speed uses a short byte window and formats safely", () => {
  expect(calculateWindowedSpeed([
    { timestampMs: 0, uploadedBytes: 0 },
    { timestampMs: 1_000, uploadedBytes: 1_024 },
    { timestampMs: 2_000, uploadedBytes: 4_096 },
  ])).toBe(2_048);
  expect(formatUploadSpeed(2_048)).toBe("2.00 KB/s");
  expect(formatUploadSpeed(Number.NaN)).toBe("0 B/s");
});

test("active ImportJob storage validates, persists, and clears the minimal record", () => {
  const storage = memoryStorage();
  const record = {
    job_id: "job-1",
    import_type: "TD_MZML" as const,
    upload_id: "upload-1",
    created_at: "2026-07-17T00:00:00.000Z",
  };
  saveActiveImportJob(storage, record);
  expect(loadActiveImportJob(storage)).toEqual(record);
  expect(storage.getItem(ACTIVE_IMPORT_JOB_KEY)).not.toContain("source_path");
  clearActiveImportJob(storage);
  expect(storage.getItem(ACTIVE_IMPORT_JOB_KEY)).toBeNull();
});

test("active ImportJob storage accepts DIA-CLIP as an explicit import type", () => {
  expect(parseActiveImportJob(JSON.stringify({
    job_id: "job-clip",
    import_type: "BU_DIA_CLIP",
    upload_id: "upload-clip",
    created_at: "2026-07-23T00:00:00.000Z",
  }))?.import_type).toBe("BU_DIA_CLIP");
});

test("invalid active ImportJob storage is rejected and removed", () => {
  const storage = memoryStorage();
  storage.setItem(ACTIVE_IMPORT_JOB_KEY, JSON.stringify({ job_id: 123, upload_id: "x" }));
  expect(loadActiveImportJob(storage)).toBeNull();
  expect(storage.getItem(ACTIVE_IMPORT_JOB_KEY)).toBeNull();
  expect(parseActiveImportJob("not json")).toBeNull();
});

function fakeFile(name: string, size: number, webkitRelativePath = ""): File {
  return { name, size, webkitRelativePath } as File;
}

function textFile(name: string, content: string, webkitRelativePath: string): File {
  const blob = new Blob([content]);
  return {
    name,
    size: blob.size,
    webkitRelativePath,
    slice: (start?: number, end?: number) => blob.slice(start, end),
  } as File;
}

function selectedFile(name: string, size: number) {
  return { file: fakeFile(name, size), relativePath: name };
}

function memoryStorage(): Pick<Storage, "getItem" | "setItem" | "removeItem"> {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
}
