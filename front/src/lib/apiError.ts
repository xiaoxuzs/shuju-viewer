import axios from "axios";

export type ApiErrorKind =
  | "scan_index_missing"
  | "scan_index_stale"
  | "chromatogram_summary_missing"
  | "chromatogram_summary_stale"
  | "unsupported_raw_format"
  | "indexed_mzml_unsupported"
  | "no_signal"
  | "not_found"
  | "validation"
  | "server_error"
  | "unknown";

export interface ParsedApiError {
  kind: ApiErrorKind;
  status: number | null;
  code: string | null;
  message: string | null;
  backfillCommand: string | null;
}

type UnknownRecord = Record<string, unknown>;

const KNOWN_CODES = new Set<ApiErrorKind>([
  "scan_index_missing",
  "scan_index_stale",
  "chromatogram_summary_missing",
  "chromatogram_summary_stale",
  "unsupported_raw_format",
  "no_signal",
]);

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function responseFrom(error: unknown): { status: number | null; data: unknown } {
  if (axios.isAxiosError(error)) {
    return {
      status: numberValue(error.response?.status),
      data: error.response?.data,
    };
  }
  if (!isRecord(error)) return { status: null, data: null };

  const response = isRecord(error.response) ? error.response : null;
  return {
    status: numberValue(response?.status) ?? numberValue(error.status),
    data: response?.data ?? error.data ?? null,
  };
}

function detailFrom(data: unknown): unknown {
  if (!isRecord(data)) return data;
  return data.detail ?? data;
}

function errorFields(detail: unknown): {
  code: string | null;
  message: string | null;
  backfillCommand: string | null;
} {
  if (typeof detail === "string") {
    return { code: detail.trim() || null, message: detail.trim() || null, backfillCommand: null };
  }
  if (!isRecord(detail)) {
    return { code: null, message: null, backfillCommand: null };
  }

  const code = stringValue(detail.error) ?? stringValue(detail.code);
  const message = stringValue(detail.message) ?? code;
  const backfillCommand =
    stringValue(detail.backfill_command) ?? stringValue(detail.backfillCommand);
  return { code, message, backfillCommand };
}

function classify(status: number | null, code: string | null, message: string | null): ApiErrorKind {
  if (code && KNOWN_CODES.has(code as ApiErrorKind)) return code as ApiErrorKind;
  if (status === 404) return "not_found";

  const normalized = `${code ?? ""} ${message ?? ""}`.toLowerCase();
  if (
    status === 422
    && (
      normalized.includes("mzml")
      || normalized.includes("embedded index")
      || normalized.includes("indexed random access")
    )
  ) {
    return "indexed_mzml_unsupported";
  }
  if (status === 422) return "validation";
  if (status !== null && status >= 500) return "server_error";
  return "unknown";
}

export function parseApiError(error: unknown): ParsedApiError {
  const { status, data } = responseFrom(error);
  const fields = errorFields(detailFrom(data));
  const fallbackMessage = error instanceof Error ? stringValue(error.message) : null;
  const message = fields.message ?? fallbackMessage;

  return {
    kind: classify(status, fields.code, message),
    status,
    code: fields.code,
    message,
    backfillCommand: fields.backfillCommand,
  };
}

export function chartQueryRetry(failureCount: number, error: unknown): boolean {
  const { status } = parseApiError(error);
  if (status === 404 || status === 409 || status === 422) return false;
  return failureCount < 1;
}
