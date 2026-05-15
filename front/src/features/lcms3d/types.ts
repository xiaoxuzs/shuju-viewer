export interface LcmsAxis {
  key: string;
  label: string;
  min: number;
  max: number;
  scale?: "linear" | "log";
}

export interface Lcms3DMap {
  source: "mzml_memory" | "topfd_js" | string;
  axes: {
    x: LcmsAxis;
    y: LcmsAxis;
    z: LcmsAxis;
  };
  points: {
    rt: number[];
    mz: number[];
    intensity: number[];
    scan?: number[];
    msLevel?: number[];
  };
  anchors: {
    centerScan?: number | null;
    centerSpecId?: number | null;
    precursorMz?: number | null;
  };
  meta: {
    datasetId: number;
    runId: number;
    msLevel: number;
    frameCount: number;
    rawPointCount: number;
    filteredPointCount: number;
    binnedPointCount: number;
    returnedPointCount: number;
    rtBins: number;
    mzBins: number;
    maxPoints: number;
    mzWindowFallback: boolean;
    generatedMs: number;
  };
}

export interface Lcms3DParams {
  ms_level?: number;
  center_scan?: number;
  center_spec_id?: number;
  center_rt_seconds?: number;
  precursor_mz?: number;
  rt_window_seconds?: number;
  mz_window?: number;
  frame_radius?: number;
  rt_bins?: number;
  mz_bins?: number;
  max_points?: number;
}
