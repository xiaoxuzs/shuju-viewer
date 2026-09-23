import { expect, test } from "@playwright/test";

import {
  layoutSpectrumLabels,
  type SpectrumLabelCandidate,
} from "../src/features/bu/components/spectrum/spectrumLabelLayout";

const candidates: SpectrumLabelCandidate[] = [
  { id: "b2", x: 20, y: 80, intensity: 100, width: 28, height: 18 },
  { id: "y5", x: 24, y: 78, intensity: 90, width: 28, height: 18 },
  { id: "b3", x: 100, y: 60, intensity: 80, width: 28, height: 18 },
];

test("top label mode keeps stronger labels and removes collisions", () => {
  const labels = layoutSpectrumLabels(candidates, "top", 160, 100, 20);

  expect(labels.map((label) => label.id)).toEqual(["b2", "b3"]);
});

test("all label mode returns every in-bounds label", () => {
  const labels = layoutSpectrumLabels(candidates, "all", 160, 100, 20);

  expect(labels.map((label) => label.id)).toEqual(["b2", "y5", "b3"]);
});

test("no label mode returns no labels", () => {
  expect(layoutSpectrumLabels(candidates, "none", 160, 100, 20)).toEqual([]);
});

test("top label mode respects its dynamic limit", () => {
  const spaced = Array.from({ length: 30 }, (_, index) => ({
    id: `b${index + 1}`,
    x: 10 + index * 30,
    y: 80,
    intensity: 1000 - index,
    width: 24,
    height: 16,
  }));

  expect(layoutSpectrumLabels(spaced, "top", 1000, 100, 8)).toHaveLength(8);
});
