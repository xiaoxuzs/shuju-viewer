import { expect, test } from "@playwright/test";

import type { SpectraScanIndexItem } from "../src/features/spectra-only/types";
import {
  filterScansByMsLevel,
  findChildMs2Scans,
  findNearestPeakByMz,
  findParentMs1Scan,
  formatMassError,
} from "../src/features/spectra-only/utils/scanRelations";

const scans: SpectraScanIndexItem[] = [
  scan({ scan_number: 100, ms_level: 1, retention_time: 1.0 }),
  scan({ scan_number: 210, ms_level: 2, retention_time: 1.1, precursor_mz: 500.02 }),
  scan({ scan_number: 220, ms_level: 2, retention_time: 1.2, precursor_mz: 610.05 }),
  scan({ scan_number: 400, ms_level: 1, retention_time: 2.0 }),
  scan({ scan_number: 450, ms_level: 2, retention_time: 2.1, precursor_mz: 700.01 }),
];

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

test("MS1 children are MS2 scans before the next MS1", () => {
  expect(findChildMs2Scans(scans, scans[0]).map((item) => item.scan_number)).toEqual([210, 220]);
  expect(findChildMs2Scans(scans, scans[3]).map((item) => item.scan_number)).toEqual([450]);
});

test("parent lookup returns null when no previous MS1 exists", () => {
  const noParent = [scan({ scan_number: 10, ms_level: 2 }), scan({ scan_number: 20, ms_level: 1 })];

  expect(findParentMs1Scan(noParent, noParent[0])).toBeNull();
});

test("nearest precursor peak uses fixed Da tolerance", () => {
  const match = findNearestPeakByMz(
    [
      { mz: 499.8, intensity: 100 },
      { mz: 500.018, intensity: 250 },
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

function scan(overrides: Partial<SpectraScanIndexItem>): SpectraScanIndexItem {
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
  };
}
