import { createContext, useContext } from "react";

import type { DatasetCapabilityReport, DatasetViewCapability } from "@/api/types";

export const DatasetCapabilityContext = createContext<DatasetCapabilityReport | null | undefined>(undefined);

export function useDatasetCapability(): DatasetCapabilityReport | null {
  const report = useContext(DatasetCapabilityContext);
  if (report === undefined) {
    throw new Error("useDatasetCapability must be used within DatasetCapabilityProvider");
  }
  return report;
}

export function findDatasetViewCapability(
  report: DatasetCapabilityReport | null,
  ...viewIds: string[]
): DatasetViewCapability | null {
  if (report?.enforcement !== "ENFORCED") return null;
  for (const viewId of viewIds) {
    const view = report.views.find((item) => item.view_id === viewId);
    if (view) return view;
  }
  return null;
}
