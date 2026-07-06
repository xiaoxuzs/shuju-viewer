import { expect, test } from "@playwright/test";

import type { SpectraScanIndexItem } from "../src/features/spectra-only/types";
import {
  buildScanRelations,
  filterScansByMsLevel,
  findChildMs2Scans,
  findNearestPeakByMz,
  findParentMs1Scan,
  formatMassError,
  getMsLevel,
} from "../src/features/spectra-only/utils/scanRelations";
import {
  clampPage,
  findPageForScan,
  getTotalPages,
  paginateScans,
} from "../src/features/spectra-only/utils/scanPagination";

const scans: SpectraScanIndexItem[] = [
  scan({ scan_number: 100, ms_level: 1, retention_time: 1.0 }),
  scan({ scan_number: 210, ms_level: 2, retention_time: 1.1, precursor_mz: 500.02 }),
  scan({ scan_number: 220, ms_level: 2, retention_time: 1.2, precursor_mz: 610.05 }),
  scan({ scan_number: 400, ms_level: 1, retention_time: 2.0 }),
  scan({ scan_number: 450, ms_level: 2, retention_time: 2.1, precursor_mz: 700.01 }),
];
const SCAN_LIST_PAGE_SIZE = 16;

test("scan level filter keeps All, MS1, and MS2 separate", () => {
  expect(filterScansByMsLevel(scans, "all").map((item) => item.scan_number)).toEqual([
    100,
    210,
    220,
    400,
    450,
  ]);
  expect(filterScansByMsLevel(scans, "ms1").map((item) => item.scan_number)).toEqual([100, 400]);
  expect(filterScansByMsLevel(scans, "ms2").map((item) => item.scan_number)).toEqual([210, 220, 450]);
});

test("MS2 parent is the nearest previous MS1 in full scan order", () => {
  expect(findParentMs1Scan(scans, scans[2])?.scan_number).toBe(100);
  expect(findParentMs1Scan(scans, scans[4])?.scan_number).toBe(400);
});

test("standard DDA sequence assigns MS2 scans to the nearest previous MS1", () => {
  expect(findChildMs2Scans(scans, scans[0]).map((item) => item.scan_number)).toEqual([210, 220]);
  expect(findChildMs2Scans(scans, scans[3]).map((item) => item.scan_number)).toEqual([450]);
});

test("consecutive MS1 scans give children only to the most recent MS1", () => {
  const dda = [
    scan({ scan_number: 1, ms_level: 1 }),
    scan({ scan_number: 2, ms_level: 1 }),
    scan({ scan_number: 3, ms_level: 2 }),
  ];

  expect(findChildMs2Scans(dda, dda[0])).toEqual([]);
  expect(findChildMs2Scans(dda, dda[1]).map((item) => item.scan_number)).toEqual([3]);
});

test("scan relations are built from scan-number order", () => {
  const unordered = [
    scan({ scan_number: 3, ms_level: 2 }),
    scan({ scan_number: 1, ms_level: 1 }),
    scan({ scan_number: 2, ms_level: 2 }),
    scan({ scan_number: 4, ms_level: 1 }),
  ];

  const relations = buildScanRelations(unordered);

  expect(relations.orderedScans.map((item) => item.scan_number)).toEqual([1, 2, 3, 4]);
  expect(findChildMs2Scans(unordered, unordered[1]).map((item) => item.scan_number)).toEqual([2, 3]);
});

test("MS level normalization accepts numbers and common strings", () => {
  expect(getMsLevel(scan({ ms_level: 1 }))).toBe(1);
  expect(getMsLevel(scan({ ms_level: "2" }))).toBe(2);
  expect(getMsLevel(scan({ ms_level: "MS1" }))).toBe(1);
  expect(getMsLevel(scan({ ms_level: "ms2" }))).toBe(2);
});

test("string scan numbers still match selected scans and child lists", () => {
  const mixed = [
    scan({ scan_number: "10", ms_level: "MS1" }),
    scan({ scan_number: "11", ms_level: "MS2" }),
    scan({ scan_number: 12, ms_level: "2" }),
  ];

  expect(findParentMs1Scan(mixed, scan({ scan_number: 11, ms_level: 2 }))?.scan_number).toBe("10");
  expect(findChildMs2Scans(mixed, scan({ scan_number: 10, ms_level: 1 })).map((item) => item.scan_number)).toEqual([
    "11",
    12,
  ]);
});

test("MS level filtering does not affect parent-child calculation from the full index", () => {
  const ms1Only = filterScansByMsLevel(scans, "ms1");

  expect(ms1Only.map((item) => item.scan_number)).toEqual([100, 400]);
  expect(findChildMs2Scans(scans, ms1Only[0]).map((item) => item.scan_number)).toEqual([210, 220]);
});

test("scan pagination keeps 16 rows per page", () => {
  const manyScans = makeScans(40);

  expect(getTotalPages(manyScans.length, SCAN_LIST_PAGE_SIZE)).toBe(3);

  const firstPage = paginateScans(manyScans, 1, SCAN_LIST_PAGE_SIZE);
  expect(firstPage.pageStart).toBe(1);
  expect(firstPage.pageEnd).toBe(16);
  expect(firstPage.items[0].scan_number).toBe(1);
  expect(firstPage.items[firstPage.items.length - 1].scan_number).toBe(16);

  const secondPage = paginateScans(manyScans, 2, SCAN_LIST_PAGE_SIZE);
  expect(secondPage.pageStart).toBe(17);
  expect(secondPage.pageEnd).toBe(32);
  expect(secondPage.items[0].scan_number).toBe(17);
  expect(secondPage.items[secondPage.items.length - 1].scan_number).toBe(32);

  const thirdPage = paginateScans(manyScans, 3, SCAN_LIST_PAGE_SIZE);
  expect(thirdPage.pageStart).toBe(33);
  expect(thirdPage.pageEnd).toBe(40);
  expect(thirdPage.items[0].scan_number).toBe(33);
  expect(thirdPage.items[thirdPage.items.length - 1].scan_number).toBe(40);
});

test("filtered scan pagination uses the filtered total", () => {
  const manyScans = makeScans(40);
  const ms1Scans = filterScansByMsLevel(manyScans, "ms1");
  const ms2Scans = filterScansByMsLevel(manyScans, "ms2");

  expect(ms1Scans).toHaveLength(20);
  expect(ms2Scans).toHaveLength(20);
  expect(getTotalPages(ms1Scans.length, SCAN_LIST_PAGE_SIZE)).toBe(2);
  expect(getTotalPages(ms2Scans.length, SCAN_LIST_PAGE_SIZE)).toBe(2);
});

test("go to page clamps outside the valid page range", () => {
  expect(clampPage(0, 3)).toBe(1);
  expect(clampPage(-5, 3)).toBe(1);
  expect(clampPage(4, 3)).toBe(3);
  expect(clampPage(Number.NaN, 3)).toBe(1);
});

test("go to scan can locate scans after the first 16 rows", () => {
  const manyScans = makeScans(40);

  expect(findPageForScan(manyScans, 16, SCAN_LIST_PAGE_SIZE)).toBe(1);
  expect(findPageForScan(manyScans, 17, SCAN_LIST_PAGE_SIZE)).toBe(2);
  expect(findPageForScan(manyScans, 40, SCAN_LIST_PAGE_SIZE)).toBe(3);
});

test("go to scan normalizes string and number scan numbers", () => {
  const mixed = Array.from({ length: 34 }, (_item, index) =>
    scan({ scan_number: index % 2 === 0 ? String(index + 1) : index + 1, ms_level: 1 }),
  );

  expect(findPageForScan(mixed, 16, SCAN_LIST_PAGE_SIZE)).toBe(1);
  expect(findPageForScan(mixed, 17, SCAN_LIST_PAGE_SIZE)).toBe(2);
  expect(findPageForScan(mixed, 34, SCAN_LIST_PAGE_SIZE)).toBe(3);
});

test("selected scan can remain selected when hidden by the current filter", () => {
  const mixed = [scan({ scan_number: 1, ms_level: 1 }), scan({ scan_number: 2, ms_level: 2 })];
  const ms1Scans = filterScansByMsLevel(mixed, "ms1");

  expect(findPageForScan(mixed, 2, SCAN_LIST_PAGE_SIZE)).toBe(1);
  expect(findPageForScan(ms1Scans, 2, SCAN_LIST_PAGE_SIZE)).toBeNull();
});

test("parent lookup returns null when no previous MS1 exists", () => {
  const noParent = [scan({ scan_number: 10, ms_level: 2 }), scan({ scan_number: 20, ms_level: 1 })];

  expect(findParentMs1Scan(noParent, noParent[0])).toBeNull();
});

test("nearest precursor peak uses fixed Da tolerance", () => {
  const match = findNearestPeakByMz(
    [
      { mz: 499.8, intensity: 100 },
      { mz: 500.018, intensity: 240 },
      { mz: 500.08, intensity: 500 },
    ],
    500.02,
    0.05,
  );

  expect(match?.peak.mz).toBe(500.018);
  expect(formatMassError(match)).toContain("Da");
});

test("nearest precursor peak returns null outside tolerance", () => {
  expect(findNearestPeakByMz([{ mz: 500.2, intensity: 100 }], 500.02, 0.05)).toBeNull();
});

function scan(overrides: Record<string, unknown>): SpectraScanIndexItem {
  return {
    scan_number: overrides.scan_number ?? 1,
    native_id: `scan=${overrides.scan_number ?? 1}`,
    ms_level: overrides.ms_level ?? 1,
    retention_time: overrides.retention_time ?? 0,
    tic: overrides.tic ?? 1000,
    bpc: overrides.bpc ?? 500,
    precursor_mz: overrides.precursor_mz ?? null,
    isolation_target_mz: overrides.isolation_target_mz ?? null,
    isolation_lower_mz: overrides.isolation_lower_mz ?? null,
    isolation_upper_mz: overrides.isolation_upper_mz ?? null,
  } as unknown as SpectraScanIndexItem;
}

function makeScans(count: number): SpectraScanIndexItem[] {
  return Array.from({ length: count }, (_item, index) =>
    scan({ scan_number: index + 1, ms_level: index % 2 === 0 ? 1 : 2 }),
  );
}
