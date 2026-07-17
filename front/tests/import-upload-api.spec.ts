import { expect, test } from "@playwright/test";
import type { AxiosResponse } from "axios";

import {
  ImportUploadRequestError,
  api,
  createImportUpload,
  deleteImportUpload,
  startImportUpload,
  uploadImportFile,
} from "../src/api/client";

test("upload session create, start, and delete use the existing API client contract", async () => {
  const previousAdapter = api.defaults.adapter;
  const requests: Array<{ method?: string; url?: string; data?: unknown }> = [];
  api.defaults.adapter = async (config) => {
    requests.push({ method: config.method, url: config.url, data: config.data });
    let data: unknown = {};
    if (config.url === "/import-uploads") {
      data = {
        upload_id: "upload-one",
        import_type: "MZML_ONLY",
        state: "CREATED",
        created_at: "2026-07-17T00:00:00Z",
      };
    } else if (config.url?.endsWith("/start")) {
      data = { job_id: "job-one", status: "queued" };
    }
    return {
      data,
      status: 200,
      statusText: "OK",
      headers: {},
      config,
    } as AxiosResponse;
  };

  try {
    await expect(createImportUpload("MZML_ONLY")).resolves.toMatchObject({ upload_id: "upload-one" });
    await expect(startImportUpload("upload-one", {
      slug: "local-data",
      name: "Local data",
      description: null,
    })).resolves.toEqual({ job_id: "job-one", status: "queued" });
    await expect(deleteImportUpload("upload-one")).resolves.toBeUndefined();
  } finally {
    api.defaults.adapter = previousAdapter;
  }

  expect(requests.map((request) => [request.method, request.url])).toEqual([
    ["post", "/import-uploads"],
    ["post", "/import-uploads/upload-one/start"],
    ["delete", "/import-uploads/upload-one"],
  ]);
  expect(JSON.parse(String(requests[0]?.data))).toEqual({ import_type: "MZML_ONLY" });
  const startBody = JSON.parse(String(requests[1]?.data)) as Record<string, unknown>;
  expect(startBody).toEqual({
    parameters: { slug: "local-data", name: "Local data", description: null },
  });
  expect(JSON.stringify(startBody)).not.toContain("source_path");
});

test("file upload encodes the relative path, streams the File body, and reports progress", async () => {
  await withFakeXmlHttpRequest(async () => {
    const file = fakeFile("sample.mzML", 12);
    const progress: Array<[number, number]> = [];
    const request = uploadImportFile(
      "upload/id",
      "folder name/nested/sample.mzML",
      file,
      (loaded, total) => progress.push([loaded, total]),
    );
    const xhr = FakeXmlHttpRequest.instances[0]!;

    expect(xhr.method).toBe("PUT");
    expect(xhr.url).toBe(
      "/api/v1/import-uploads/upload%2Fid/files?relative_path=folder+name%2Fnested%2Fsample.mzML",
    );
    expect(xhr.headers["Content-Type"]).toBe("application/octet-stream");
    expect(xhr.sentBody).toBe(file);

    xhr.upload.onprogress?.({ loaded: 7, total: 12, lengthComputable: true });
    expect(progress).toEqual([[7, 12]]);
    xhr.status = 200;
    xhr.response = {
      upload_id: "upload/id",
      relative_path: "folder name/nested/sample.mzML",
      size_bytes: 12,
      state: "UPLOADING",
      total_size_bytes: 12,
      file_count: 1,
    };
    xhr.onload?.();
    await expect(request.promise).resolves.toMatchObject({ size_bytes: 12 });
  });
});

test("file upload parses structured backend errors and exposes abort", async () => {
  await withFakeXmlHttpRequest(async () => {
    const failed = uploadImportFile("upload-one", "bad.mzML", fakeFile("bad.mzML", 1));
    const failedXhr = FakeXmlHttpRequest.instances[0]!;
    failedXhr.status = 507;
    failedXhr.response = {
      detail: { code: "UPLOAD_DISK_SPACE_LOW", message: "磁盘剩余空间不足。" },
    };
    failedXhr.onload?.();
    await expect(failed.promise).rejects.toMatchObject({
      name: "ImportUploadRequestError",
      code: "UPLOAD_DISK_SPACE_LOW",
      message: "磁盘剩余空间不足。",
      status: 507,
    });

    const cancelled = uploadImportFile("upload-two", "later.mzML", fakeFile("later.mzML", 2));
    cancelled.abort();
    await expect(cancelled.promise).rejects.toEqual(expect.objectContaining<Partial<ImportUploadRequestError>>({
      code: "UPLOAD_CANCELLED",
      message: "Upload cancelled.",
    }));

    const networkFailure = uploadImportFile("upload-three", "network.mzML", fakeFile("network.mzML", 3));
    FakeXmlHttpRequest.instances[2]?.onerror?.();
    await expect(networkFailure.promise).rejects.toMatchObject({
      code: null,
      message: "Network error while uploading file.",
      status: null,
    });
  });
});

function fakeFile(name: string, size: number): File {
  return { name, size, webkitRelativePath: "" } as File;
}

async function withFakeXmlHttpRequest(run: () => Promise<void>): Promise<void> {
  const target = globalThis as unknown as { XMLHttpRequest: typeof XMLHttpRequest };
  const previous = target.XMLHttpRequest;
  FakeXmlHttpRequest.instances = [];
  target.XMLHttpRequest = FakeXmlHttpRequest as unknown as typeof XMLHttpRequest;
  try {
    await run();
  } finally {
    target.XMLHttpRequest = previous;
  }
}

class FakeXmlHttpRequest {
  static instances: FakeXmlHttpRequest[] = [];

  method = "";
  url = "";
  headers: Record<string, string> = {};
  sentBody: Document | XMLHttpRequestBodyInit | null = null;
  status = 0;
  response: unknown = null;
  responseText = "";
  responseType: XMLHttpRequestResponseType = "";
  upload: {
    onprogress: ((event: { loaded: number; total: number; lengthComputable: boolean }) => void) | null;
  } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  constructor() {
    FakeXmlHttpRequest.instances.push(this);
  }

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value;
  }

  send(body: Document | XMLHttpRequestBodyInit | null): void {
    this.sentBody = body;
  }

  abort(): void {
    this.onabort?.();
  }
}
