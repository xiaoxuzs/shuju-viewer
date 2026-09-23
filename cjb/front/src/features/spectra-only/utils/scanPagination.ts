import type { SpectraScanIndexItem } from "@/features/spectra-only/types";
import { getScanNumber } from "@/features/spectra-only/utils/scanRelations";

export interface ScanPage<T> {
  items: T[];
  currentPage: number;
  totalPages: number;
  pageStart: number;
  pageEnd: number;
}

export function getTotalPages(itemCount: number, pageSize: number): number {
  if (!Number.isFinite(itemCount) || !Number.isFinite(pageSize) || pageSize <= 0) return 1;
  return Math.max(1, Math.ceil(Math.max(0, itemCount) / pageSize));
}

export function clampPage(page: number, totalPages: number): number {
  const safeTotalPages = getTotalPages(totalPages, 1);
  if (!Number.isFinite(page)) return 1;
  return Math.min(Math.max(Math.trunc(page), 1), safeTotalPages);
}

export function paginateScans<T>(items: T[], page: number, pageSize: number): ScanPage<T> {
  const totalPages = getTotalPages(items.length, pageSize);
  const currentPage = clampPage(page, totalPages);
  const startIndex = (currentPage - 1) * pageSize;
  const pageItems = items.slice(startIndex, startIndex + pageSize);
  return {
    items: pageItems,
    currentPage,
    totalPages,
    pageStart: pageItems.length === 0 ? 0 : startIndex + 1,
    pageEnd: startIndex + pageItems.length,
  };
}

export function findPageForScan(
  scans: SpectraScanIndexItem[],
  scanNumber: number,
  pageSize: number,
): number | null {
  const scanIndex = scans.findIndex((scan) => getScanNumber(scan) === scanNumber);
  if (scanIndex < 0) return null;
  return Math.floor(scanIndex / pageSize) + 1;
}
