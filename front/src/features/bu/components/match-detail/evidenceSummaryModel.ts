import type {
  BuMatchDetailOut,
  BuMs2AnnotationOut,
  BuMs2SlotItem,
  BuMs2SlotListOut,
  BuSpectrumV1,
  BuXicOut,
} from "@/features/bu/types";
import type { BuXicPointSelection } from "@/features/bu/components/spectrum/BuXicChart";
import { cleavageSite, pfmbResidues } from "@/features/bu/components/match-detail/pfmbSeries";
import {
  formatCount,
  formatDecimal,
  inspectedRtSourceLabel,
  type InspectedRtSource,
} from "@/features/bu/utils";

export interface EvidenceRow {
  label: string;
  value: string;
  detail?: string;
}

export interface EvidenceSection {
  key: "identification" | "diaclip" | "chromatographic" | "live-ms2" | "pfmb" | "mass-accuracy";
  title: string;
  rows: EvidenceRow[];
  empty?: string;
}

export interface EvidenceDataState<T> {
  data?: T;
  isLoading: boolean;
  isError: boolean;
}

export interface BuildBuEvidenceSummaryInput {
  match: BuMatchDetailOut;
  xic: EvidenceDataState<BuXicOut>;
  ms2: EvidenceDataState<BuSpectrumV1>;
  hasPfmb: boolean;
  pfmbSlots: EvidenceDataState<BuMs2SlotListOut>;
  pfmbAnnotation: EvidenceDataState<BuMs2AnnotationOut>;
  activePfmbSlot: BuMs2SlotItem | null;
  inspectedRt: { rt: number; source: InspectedRtSource } | null;
  selectedXicPoint: BuXicPointSelection | null;
}

export function buildBuEvidenceSummary(input: BuildBuEvidenceSummaryInput): EvidenceSection[] {
  const identificationRt = input.match.identification_rt_apex ?? input.match.rt_window.rt_apex;
  const identification: EvidenceSection = {
    key: "identification",
    title: "Identification",
    rows: [
      { label: "Charge", value: input.match.precursor_charge ? `${input.match.precursor_charge}+` : "N/A" },
      { label: "Precursor m/z", value: displayDecimal(input.match.precursor_mz) },
      { label: "Q-value", value: displayDecimal(input.match.q_value) },
      { label: "Identification RT apex", value: displayRt(identificationRt) },
    ],
  };

  const diaclip = buildDiaclipEvidence(input.match);
  const chromatographic = buildChromatographicEvidence(input);
  const liveMs2 = buildLiveMs2Evidence(input.ms2, input.match.sequence);
  const pfmb = buildPfmbEvidence(input);
  const massAccuracy = buildMassAccuracy(input.ms2, input.pfmbAnnotation);
  return [identification, ...(diaclip ? [diaclip] : []), chromatographic, liveMs2, pfmb, massAccuracy];
}

function buildDiaclipEvidence(match: BuMatchDetailOut): EvidenceSection | null {
  const raw = match.extra_metadata?.diaclip;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const metadata = raw as Record<string, unknown>;
  return {
    key: "diaclip",
    title: "DIA-CLIP evidence",
    rows: [
      { label: "DIA-CLIP score", value: displayDecimal(match.score) },
      { label: "Feature distance", value: displayMetadataDecimal(metadata.feature_distance) },
      { label: "Cosine similarity", value: displayMetadataDecimal(metadata.cos_similarity) },
      { label: "DIA-CLIP quantity", value: displayMetadataDecimal(metadata.quant_result) },
      { label: "Reference q-value", value: displayMetadataDecimal(metadata.diann_q_value) },
      { label: "Reference precursor quantity", value: displayMetadataDecimal(metadata.diann_precursor_quantity) },
    ],
  };
}

function buildChromatographicEvidence(input: BuildBuEvidenceSummaryInput): EvidenceSection {
  if (input.xic.isLoading) {
    return { key: "chromatographic", title: "Chromatographic evidence", rows: [], empty: "Loading XIC evidence..." };
  }
  if (input.xic.isError || !input.xic.data) {
    return { key: "chromatographic", title: "Chromatographic evidence", rows: [], empty: "XIC not available" };
  }

  const rows: EvidenceRow[] = [{ label: "Precursor XIC", value: "Available" }];
  const { rt_start: start, rt_stop: stop } = input.match.rt_window;
  rows.push({
    label: "RT window",
    value: Number.isFinite(start) && Number.isFinite(stop)
      ? `${formatDecimal(start, 4)} to ${formatDecimal(stop, 4)} min`
      : "Not available",
  });
  rows.push({
    label: "Current inspected RT",
    value: input.inspectedRt ? `${input.inspectedRt.rt.toFixed(4)} min` : "Not selected",
    detail: input.inspectedRt ? `From ${inspectedRtSourceLabel(input.inspectedRt.source)}` : " ",
  });
  if (input.selectedXicPoint) {
    rows.push({
      label: "Selected XIC point",
      value: `${input.selectedXicPoint.traceLabel} at ${input.selectedXicPoint.rt.toFixed(4)} min`,
      detail: `Intensity ${formatCount(input.selectedXicPoint.intensity)}`,
    });
  } else if (Number.isFinite(input.xic.data.rt_apex)) {
    rows.push({ label: "Identification RT apex guide", value: displayRt(input.xic.data.rt_apex), detail: " " });
  }
  return { key: "chromatographic", title: "Chromatographic evidence", rows };
}

function buildLiveMs2Evidence(
  ms2: EvidenceDataState<BuSpectrumV1>,
  sequence: string,
): EvidenceSection {
  if (ms2.isLoading) {
    return { key: "live-ms2", title: "Live mzML MS2 evidence", rows: [], empty: "Loading MS2 evidence..." };
  }
  if (ms2.isError || !ms2.data) {
    return { key: "live-ms2", title: "Live mzML MS2 evidence", rows: [], empty: "MS2 scan not available" };
  }
  const theoretical = Math.max(0, sequence.length * 2 - 2);
  return {
    key: "live-ms2",
    title: "Live mzML MS2 evidence",
    rows: [
      {
        label: "Live matched b/y ions",
        value: `${formatCount(ms2.data.matched_ions.length)} / ${formatCount(theoretical)}`,
      },
      { label: "MS2 scan", value: `#${ms2.data.scan}` },
      { label: "MS2 scan RT", value: displayRt(ms2.data.rt_minutes) },
    ],
  };
}

function buildPfmbEvidence(input: BuildBuEvidenceSummaryInput): EvidenceSection {
  if (!input.hasPfmb) {
    return { key: "pfmb", title: "Fragment Match evidence", rows: [], empty: "Fragment Match annotation not available" };
  }
  if (input.pfmbSlots.isLoading || input.pfmbAnnotation.isLoading) {
    return { key: "pfmb", title: "Fragment Match evidence", rows: [], empty: "Loading Fragment Match evidence..." };
  }
  if (
    input.pfmbSlots.isError
    || input.pfmbAnnotation.isError
    || !input.pfmbSlots.data?.slots.length
    || !input.pfmbAnnotation.data
    || !input.activePfmbSlot
  ) {
    return { key: "pfmb", title: "Fragment Match evidence", rows: [], empty: "Fragment Match annotation not available" };
  }

  const coverage = calculatePfmbCoverage(
    input.pfmbAnnotation.data.peptide,
    input.pfmbAnnotation.data,
  );
  const isApex = input.activePfmbSlot.slot_index === input.pfmbSlots.data.apex_slot;
  const rows: EvidenceRow[] = [
    {
      label: "Fragment Match coverage",
      value: coverage ? `${(coverage.ratio * 100).toFixed(0)}%` : "Not available",
      detail: coverage ? `${coverage.covered} / ${coverage.total} cleavage sites` : undefined,
    },
    {
      label: "Fragment Match matched peak rows",
      value: formatCount(input.pfmbAnnotation.data.matched_peak_count),
    },
    {
      label: "Fragment Match slot RT",
      value: displayRt(input.activePfmbSlot.rt_minutes),
      detail: isApex ? "Fragment Match apex" : " ",
    },
  ];
  return { key: "pfmb", title: "Fragment Match evidence", rows };
}

function buildMassAccuracy(
  liveMs2: EvidenceDataState<BuSpectrumV1>,
  pfmbAnnotation: EvidenceDataState<BuMs2AnnotationOut>,
): EvidenceSection {
  const rows: EvidenceRow[] = [];
  if (liveMs2.data) {
    const live = summarizePpm(liveMs2.data.matched_ions.map((ion) => ion.ppm));
    if (live) rows.push({ label: "Live MS2 mass accuracy", value: ppmText(live) });
  }
  if (pfmbAnnotation.data) {
    const pfmb = summarizePpm(pfmbAnnotation.data.matched_ions.map((ion) => ion.mass_error_ppm));
    if (pfmb) rows.push({ label: "Fragment Match mass accuracy", value: ppmText(pfmb) });
  }
  const loading = liveMs2.isLoading || pfmbAnnotation.isLoading;
  return {
    key: "mass-accuracy",
    title: "Mass accuracy",
    rows,
    empty: rows.length === 0
      ? loading ? "Loading mass accuracy..." : "Mass accuracy not available"
      : undefined,
  };
}

export function calculatePfmbCoverage(peptide: string, annotation: BuMs2AnnotationOut) {
  const peptideLength = pfmbResidues(peptide).length;
  if (peptideLength < 2) return null;
  const sites = new Set<number>();
  for (const ion of annotation.matched_ions) {
    const site = cleavageSite(ion, peptideLength);
    if (site >= 1 && site < peptideLength) sites.add(site);
  }
  return {
    covered: sites.size,
    total: peptideLength - 1,
    ratio: sites.size / (peptideLength - 1),
  };
}

export function summarizePpm(values: number[]) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (sorted.length === 0) return null;
  return {
    median: quantile(sorted, 0.5),
    q1: quantile(sorted, 0.25),
    q3: quantile(sorted, 0.75),
  };
}

function quantile(sorted: number[], q: number): number {
  if (sorted.length === 1) return sorted[0];
  const position = (sorted.length - 1) * q;
  const base = Math.floor(position);
  const fraction = position - base;
  return sorted[base + 1] === undefined
    ? sorted[base]
    : sorted[base] + fraction * (sorted[base + 1] - sorted[base]);
}

function ppmText(summary: NonNullable<ReturnType<typeof summarizePpm>>): string {
  return `Median ${formatDecimal(summary.median, 2)} ppm; IQR ${formatDecimal(summary.q1, 2)} to ${formatDecimal(summary.q3, 2)} ppm`;
}

function displayDecimal(value: number | null | undefined): string {
  return Number.isFinite(value) ? formatDecimal(value) : "N/A";
}

function displayMetadataDecimal(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? formatDecimal(value) : "N/A";
}

function displayRt(value: number | null | undefined): string {
  return Number.isFinite(value) ? `${formatDecimal(value, 4)} min` : "Not available";
}
