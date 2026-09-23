import { Navigate, useOutletContext, useParams } from "react-router-dom";
import type { ReactNode } from "react";

import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";

export function BuModeOnly({ children }: { children: ReactNode }) {
  const { slug = "" } = useParams();
  const { dataset } = useOutletContext<BuDatasetContext>();
  if (dataset.analysis_mode !== "BOTTOM_UP") {
    return <Navigate to={`/datasets/${slug}`} replace />;
  }
  return <>{children}</>;
}
