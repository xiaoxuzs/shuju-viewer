import { expect, test } from "@playwright/test";

import { chartQueryRetry, parseApiError } from "../src/lib/apiError";

function httpError(status: number, detail: unknown) {
  return {
    response: {
      status,
      data: { detail },
    },
  };
}

test("classifies derived-data errors and preserves backfill commands", () => {
  const command = "python scripts/backfill_mzml_scan_indexes.py --dataset-id 40 --run-id 39";
  expect(parseApiError(httpError(409, {
    error: "scan_index_missing",
    backfill_command: command,
  }))).toEqual({
    kind: "scan_index_missing",
    status: 409,
    code: "scan_index_missing",
    message: "scan_index_missing",
    backfillCommand: command,
  });

  expect(parseApiError(httpError(409, "scan_index_stale")).kind).toBe("scan_index_stale");
  expect(parseApiError(httpError(409, "chromatogram_summary_missing")).kind)
    .toBe("chromatogram_summary_missing");
  expect(parseApiError(httpError(409, "chromatogram_summary_stale")).kind)
    .toBe("chromatogram_summary_stale");
});

test("handles string, object, fetch-like, server, and unknown errors", () => {
  expect(parseApiError(httpError(422, "unsupported_raw_format")).kind)
    .toBe("unsupported_raw_format");
  expect(parseApiError(httpError(422, "gzip-compressed mzML does not support indexed random access")).kind)
    .toBe("indexed_mzml_unsupported");
  expect(parseApiError({ status: 404, data: { detail: "scan not found" } }).kind)
    .toBe("not_found");
  expect(parseApiError(httpError(500, { message: "reader failed" })).kind)
    .toBe("server_error");
  expect(parseApiError(new Error("network failed"))).toMatchObject({
    kind: "unknown",
    status: null,
    message: "network failed",
  });
  expect(parseApiError({ unexpected: true })).toMatchObject({
    kind: "unknown",
    status: null,
    code: null,
  });
});

test("does not retry expected chart errors and retries server errors only once", () => {
  for (const status of [404, 409, 422]) {
    expect(chartQueryRetry(0, httpError(status, "expected"))).toBe(false);
  }

  expect(chartQueryRetry(0, httpError(500, "failed"))).toBe(true);
  expect(chartQueryRetry(1, httpError(500, "failed"))).toBe(false);
});
