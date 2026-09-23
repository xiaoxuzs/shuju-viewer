import { CapabilityReportPanel } from "@/features/dataset-capabilities/CapabilityReportPanel";
import { useDatasetCapability } from "@/features/dataset-capabilities/DatasetCapabilityContext";

export function DatasetCapabilityReportSlot() {
  const report = useDatasetCapability();
  if (!report) return null;
  return (
    <div className="mb-5">
      <CapabilityReportPanel report={report} />
    </div>
  );
}
