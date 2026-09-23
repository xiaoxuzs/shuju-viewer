import type { ReactNode } from "react";

import type { DatasetCapabilityReport } from "@/api/types";
import { DatasetCapabilityContext } from "@/features/dataset-capabilities/DatasetCapabilityContext";

export function DatasetCapabilityProvider({
  report,
  children,
}: {
  report: DatasetCapabilityReport | null;
  children: ReactNode;
}) {
  return (
    <DatasetCapabilityContext.Provider value={report}>
      {children}
    </DatasetCapabilityContext.Provider>
  );
}
