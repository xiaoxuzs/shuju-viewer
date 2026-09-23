import type { DatasetCapabilityReport } from "../src/api/types";

/** Minimal valid legacy report for tests whose focus predates capability enforcement. */
export function advisoryCapabilityReport(datasetId: number): DatasetCapabilityReport {
  return {
    schema_version: 1,
    dataset_id: datasetId,
    source_case_id: null,
    provenance: "LEGACY_METADATA",
    enforcement: "ADVISORY",
    entities: [],
    views: [],
    missing_inputs: [],
    ambiguities: [],
    warnings: [
      {
        warning_id: "legacy_capability_metadata",
        message: "This report was conservatively inferred from legacy dataset capabilities.",
        evidence_refs: ["datasets.capabilities"],
      },
    ],
  };
}
