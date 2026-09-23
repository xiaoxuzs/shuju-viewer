import { expect, test } from "@playwright/test";

import {
  buildPeakAnnotations,
  findNearestPeakByMz,
  getBasePeak,
  getRelativeIntensity,
  getTopPeaks,
  normalizePeaks,
  type RawPeakLike,
} from "../src/features/spectra-only/utils/peakAnnotations";

test("base peak is the highest intensity peak", () => {
  const basePeak = getBasePeak([
    { mz: 100.1, intensity: 50 },
    { mz: 100.2, intensity: 500 },
    { mz: 100.3, intensity: 200 },
  ]);

  expect(basePeak?.mz).toBe(100.2);
  expect(basePeak?.intensity).toBe(500);
});

test("Top 5 peaks are selected by descending intensity", () => {
  const topPeaks = getTopPeaks(makePeaks(12), 5);

  expect(topPeaks).toHaveLength(5);
  expect(topPeaks.map((peak) => peak.intensity)).toEqual([12, 11, 10, 9, 8]);
});

test("Top 10 returns all peaks when fewer than 10 are available", () => {
  expect(getTopPeaks(makePeaks(6), 10)).toHaveLength(6);
});

test("relative intensity uses the base peak as 100 percent", () => {
  const peaks = normalizePeaks([
    { mz: 100.1, intensity: 25 },
    { mz: 100.2, intensity: 100 },
  ]);

  expect(getRelativeIntensity(peaks[1], 100)).toBe(100);
  expect(getRelativeIntensity(peaks[0], 100)).toBe(25);
});

test("selected peak is preserved even when it is outside TopN labels", () => {
  const peaks = makePeaks(12);
  const selectedPeak = peaks[0];
  const annotations = buildPeakAnnotations(peaks, "top5", selectedPeak);

  expect(annotations.labelAnnotations).toHaveLength(5);
  expect(annotations.labelAnnotations.some((annotation) => annotation.peak.mz === selectedPeak.mz)).toBe(false);
  expect(annotations.selectedAnnotation?.peak.mz).toBe(selectedPeak.mz);
});

test("empty peaks do not crash annotation building", () => {
  const annotations = buildPeakAnnotations([], "top10", null);

  expect(annotations.normalizedPeaks).toEqual([]);
  expect(annotations.basePeak).toBeNull();
  expect(annotations.labelAnnotations).toEqual([]);
  expect(annotations.tableAnnotations).toEqual([]);
  expect(annotations.selectedAnnotation).toBeNull();
});

test("mz and intensity are normalized from strings and numbers", () => {
  const peaks = normalizePeaks([
    { mz: "445.23", intensity: "1000" },
    { mz: 446.12, intensity: 500 },
    { mz: "not-a-number", intensity: 2000 },
  ]);

  expect(peaks).toHaveLength(2);
  expect(peaks[0].mz).toBe(445.23);
  expect(peaks[0].intensity).toBe(1000);
  expect(peaks[1].mz).toBe(446.12);
});

test("Off mode suppresses chart labels but keeps Top 10 table peaks", () => {
  const annotations = buildPeakAnnotations(makePeaks(15), "off", null);

  expect(annotations.labelAnnotations).toHaveLength(0);
  expect(annotations.tableAnnotations).toHaveLength(10);
  expect(annotations.tableAnnotations[0].peak.intensity).toBe(15);
});

test("Top 5, Top 10, and Top 20 modes produce the expected label counts", () => {
  const peaks = makePeaks(25);

  expect(buildPeakAnnotations(peaks, "top5").labelAnnotations).toHaveLength(5);
  expect(buildPeakAnnotations(peaks, "top10").labelAnnotations).toHaveLength(10);
  expect(buildPeakAnnotations(peaks, "top20").labelAnnotations).toHaveLength(20);
});

test("nearest peak lookup respects m/z tolerance", () => {
  const match = findNearestPeakByMz(
    [
      { mz: 445.1, intensity: 100 },
      { mz: 445.235, intensity: 300 },
      { mz: 445.4, intensity: 500 },
    ],
    "445.23",
    0.01,
  );

  expect(match?.mz).toBe(445.235);
  expect(findNearestPeakByMz([{ mz: 445.4, intensity: 100 }], 445.23, 0.01)).toBeNull();
});

function makePeaks(count: number): RawPeakLike[] {
  return Array.from({ length: count }, (_item, index) => ({
    mz: 100 + index,
    intensity: index + 1,
  }));
}
