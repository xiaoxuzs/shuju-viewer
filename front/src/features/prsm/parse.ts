/**
 * Parsers that normalize the raw TopPIC-style JSON blobs returned by the
 * backend (`annotated_protein`, `ms_peaks`, MS1/MS2 spectra) into flat,
 * typed shapes that are easy for React components to consume.
 *
 * The original `.js` files wrap every scalar in a string and collapse
 * single-element arrays to a single object, so most of the work here is
 * coercing strings to numbers and making sure list-shaped fields are
 * always actual arrays.
 */
import type { PrsmDetailOut } from "@/api/types";

// ------------------------------ Basic helpers ------------------------------

export function asList<T>(v: T | T[] | null | undefined): T[] {
  if (v == null) return [];
  return Array.isArray(v) ? v : [v];
}

export function num(v: unknown): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

// ------------------------------ Sequence / annotation ---------------------

export type IonType = "B" | "C" | "Y" | "Z_DOT" | string;

export interface Residue {
  position: number; // 0-based within the protein sequence
  acid: string;
}

export interface MatchedPeakLite {
  ionType: IonType;
  ionPosition: number;
  ionDisplayPosition: number;
  specId: number;
  peakId: number;
  peakCharge: number;
}

export interface Cleavage {
  position: number; // 0..protein_length (cleavage between residue pos-1 and pos)
  existNIon: boolean;
  existCIon: boolean;
  matchedPeaks: MatchedPeakLite[];
}

export interface MassShift {
  id: number;
  leftPosition: number;
  rightPosition: number;
  shift: number | null;
  anno: string;
  shiftType: string; // "fixed" | "variable" | "unexpected" | ...
}

export interface AnnotatedProtein {
  sequenceId: number | null;
  proteoformId: number | null;
  sequenceName: string;
  sequenceDescription: string | null;
  proteoformMass: number | null;
  nAcetylation: number | null;
  unexpectedShiftNumber: number | null;
  proteinLength: number;
  firstResiduePosition: number;
  lastResiduePosition: number;
  annotatedSeq: string;
  residues: Residue[];
  cleavages: Cleavage[];
  massShifts: MassShift[];
}

export function parseAnnotatedProtein(
  raw: Record<string, unknown> | null | undefined,
): AnnotatedProtein | null {
  if (!raw) return null;
  const ann = (raw as any).annotation ?? {};
  const residues: Residue[] = asList(ann.residue).map((r: any) => ({
    position: Number(r.position),
    acid: String(r.acid ?? ""),
  }));
  const cleavages: Cleavage[] = asList(ann.cleavage).map((c: any) => {
    const mp = asList(c.matched_peaks?.matched_peak).map(
      (m: any): MatchedPeakLite => ({
        ionType: String(m.ion_type ?? ""),
        ionPosition: Number(m.ion_position),
        ionDisplayPosition: Number(m.ion_display_position),
        specId: Number(m.spec_id),
        peakId: Number(m.peak_id),
        peakCharge: Number(m.peak_charge),
      }),
    );
    return {
      position: Number(c.position),
      existNIon: String(c.exist_n_ion) === "1",
      existCIon: String(c.exist_c_ion) === "1",
      matchedPeaks: mp,
    };
  });
  const massShifts: MassShift[] = asList(ann.mass_shift).map((ms: any) => ({
    id: Number(ms.id),
    leftPosition: Number(ms.left_position),
    rightPosition: Number(ms.right_position),
    shift: num(ms.shift),
    anno: String(ms.anno ?? ""),
    shiftType: String(ms.shift_type ?? ""),
  }));

  return {
    sequenceId: num((raw as any).sequence_id),
    proteoformId: num((raw as any).proteoform_id),
    sequenceName: String((raw as any).sequence_name ?? ""),
    sequenceDescription: ((raw as any).sequence_description as string | null) ?? null,
    proteoformMass: num((raw as any).proteoform_mass),
    nAcetylation: num((raw as any).n_acetylation),
    unexpectedShiftNumber: num((raw as any).unexpected_shift_number),
    proteinLength: Number(ann.protein_length ?? residues.length),
    firstResiduePosition: Number(ann.first_residue_position ?? 0),
    lastResiduePosition: Number(ann.last_residue_position ?? residues.length - 1),
    annotatedSeq: String(ann.annotated_seq ?? ""),
    residues,
    cleavages,
    massShifts,
  };
}

// ------------------------------ MS peak table -----------------------------

export interface MatchedIon {
  ionType: IonType;
  matchShift: number | null;
  theoreticalMass: number | null;
  ionPosition: number;
  ionDisplayPosition: number;
  ionSortName: string;
  ionLeftPosition: number;
  massError: number | null;
  ppm: number | null;
}

export interface MsPeakRow {
  specId: number;
  peakId: number;
  monoMass: number | null;
  monoMz: number | null;
  intensity: number | null;
  charge: number | null;
  matchedIons: MatchedIon[];
}

/** Stable key for a matched table row (Peak + ion). */
export function matchedPeakDetailKey(peak: MsPeakRow, ion: MatchedIon): string {
  return `${peak.peakId}|${ion.ionType}|${ion.ionDisplayPosition}|${ion.ionSortName}`;
}

export function parseMsPeaks(raw: Record<string, unknown> | null | undefined): MsPeakRow[] {
  if (!raw) return [];
  const peaks = asList((raw as any).peak);
  return peaks.map((p: any) => {
    const ions = asList(p.matched_ions?.matched_ion).map(
      (i: any): MatchedIon => ({
        ionType: String(i.ion_type ?? ""),
        matchShift: num(i.match_shift),
        theoreticalMass: num(i.theoretical_mass),
        ionPosition: Number(i.ion_position),
        ionDisplayPosition: Number(i.ion_display_position),
        ionSortName: String(i.ion_sort_name ?? ""),
        ionLeftPosition: Number(i.ion_left_position),
        massError: num(i.mass_error),
        ppm: num(i.ppm),
      }),
    );
    return {
      specId: Number(p.spec_id),
      peakId: Number(p.peak_id),
      monoMass: num(p.monoisotopic_mass),
      monoMz: num(p.monoisotopic_mz),
      intensity: num(p.intensity),
      charge: num(p.charge),
      matchedIons: ions,
    };
  });
}

// ------------------------------ MS1 / MS2 raw spectrum --------------------

export interface RawPeak {
  mz: number;
  intensity: number;
}

/**
 * One isotope peak inside a deconvoluted envelope. The TopFD JS file lists
 * `env_peaks` per envelope as a flat array of `{ mz, intensity }` covering
 * every isotopologue position used during deconvolution.
 */
export interface RawEnvelopePeak {
  mz: number;
  intensity: number;
}

/**
 * A deconvoluted envelope as exported by TopFD. The envelope `id` matches
 * the `peak_id` field of the corresponding row in `ms_peaks`, which lets us
 * jump from a clicked matched-peak row straight to the precise isotopologue
 * cluster in the raw spectrum.
 */
export interface RawEnvelope {
  id: number;
  monoMass: number;
  charge: number;
  envPeaks: RawEnvelopePeak[];
}

export interface RawSpectrum {
  id: number;
  scan: number;
  retentionTime: number | null;
  targetMz: number | null;
  minMz: number | null;
  maxMz: number | null;
  nIonType: string | null;
  cIonType: string | null;
  peaks: RawPeak[];
  envelopes: RawEnvelope[];
}

export function parseRawSpectrum(raw: Record<string, unknown> | null | undefined): RawSpectrum | null {
  if (!raw) return null;
  // mzML-memory API (`/datasets/{id}/runs/{run}/spectra/{scan}`): parallel vectors at top level.
  const mzVec = (raw as any).mz;
  const intVec = (raw as any).intensity;
  if (Array.isArray(mzVec) && Array.isArray(intVec)) {
    const peaks: RawPeak[] = [];
    const n = Math.min(mzVec.length, intVec.length);
    for (let i = 0; i < n; i++) {
      const mz = Number(mzVec[i]);
      const intensity = Number(intVec[i]);
      if (Number.isFinite(mz) && Number.isFinite(intensity)) {
        peaks.push({ mz, intensity });
      }
    }
    return {
      id: Number((raw as any).id ?? (raw as any).scan ?? 0),
      scan: Number((raw as any).scan ?? 0),
      retentionTime: num((raw as any).rt_seconds ?? (raw as any).retention_time),
      targetMz: num((raw as any).target_mz),
      minMz: num((raw as any).min_mz),
      maxMz: num((raw as any).max_mz),
      nIonType: ((raw as any).n_ion_type as string | null) ?? null,
      cIonType: ((raw as any).c_ion_type as string | null) ?? null,
      peaks,
      envelopes: [],
    };
  }

  const peaks = asList((raw as any).peaks).map(
    (p: any): RawPeak => ({
      mz: Number(p.mz),
      intensity: Number(p.intensity),
    }),
  );
  const envelopes = asList((raw as any).envelopes).map(
    (e: any): RawEnvelope => ({
      id: Number(e.id ?? -1),
      monoMass: Number(e.mono_mass ?? 0),
      charge: Number(e.charge ?? 0),
      envPeaks: asList(e.env_peaks).map(
        (p: any): RawEnvelopePeak => ({
          mz: Number(p.mz),
          intensity: Number(p.intensity),
        }),
      ),
    }),
  );
  return {
    id: Number((raw as any).id ?? 0),
    scan: Number((raw as any).scan ?? 0),
    retentionTime: num((raw as any).retention_time),
    targetMz: num((raw as any).target_mz),
    minMz: num((raw as any).min_mz),
    maxMz: num((raw as any).max_mz),
    nIonType: ((raw as any).n_ion_type as string | null) ?? null,
    cIonType: ((raw as any).c_ion_type as string | null) ?? null,
    peaks,
    envelopes,
  };
}

/**
 * Find the envelope inside `spectrum` that corresponds to a deconvoluted
 * matched peak. We try the direct `id == peak_id` mapping first (TopFD
 * exports them with consistent indexing), then fall back to the closest
 * `mono_mass` with the same charge so renamed/re-indexed exports still
 * resolve.
 */
export function findMatchedEnvelope(
  spectrum: RawSpectrum | null | undefined,
  peak: MsPeakRow | null | undefined,
  tolerance = 0.5,
): RawEnvelope | null {
  if (!spectrum || !peak) return null;
  const envelopes = spectrum.envelopes;
  if (envelopes.length === 0) return null;
  for (const env of envelopes) {
    if (env.id === peak.peakId) return env;
  }
  const targetMass = peak.monoMass;
  if (targetMass == null || !Number.isFinite(targetMass)) return null;
  let best: RawEnvelope | null = null;
  let bestDist = Infinity;
  for (const env of envelopes) {
    if (peak.charge != null && env.charge !== peak.charge) continue;
    const d = Math.abs(env.monoMass - targetMass);
    if (d < bestDist) {
      best = env;
      bestDist = d;
    }
  }
  return best != null && bestDist <= tolerance ? best : null;
}

// ------------------------------ Top-level helper -------------------------

/** Tokens that appear between a pair of `(...)[+xx]` brackets in `annotated_seq`. */
export interface ShiftRegion {
  left: number; // inclusive (0-based residue position)
  right: number; // inclusive
  anno: string;
  type: string;
}

export function splitDataForDetail(d: PrsmDetailOut) {
  return {
    protein: parseAnnotatedProtein(d.annotated_protein),
    peaks: parseMsPeaks(d.ms_peaks),
  };
}
