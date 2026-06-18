export type SpectrumAnnotationSource = "live" | "pfmb";

export type SpectrumExternalAnnotation = {
  id: string;
  source: SpectrumAnnotationSource;
  ionType: string;
  position: number;
  charge: number;
  expMz: number;
  theoMz?: number;
  ppm?: number | null;
  massErrorDa?: number | null;
  label: string;
  matchedPeakMz?: number;
  matchedPeakIntensity?: number;
  isMappedToRawPeak: boolean;
  color?: string;
};
