/** Top-Down routes under ``AppShell``: ``/datasets/:slug/:cutoff/...`` */
import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/app-shell";
import { DatasetsPage } from "@/pages/DatasetsPage";
import { DatasetPage } from "@/pages/DatasetPage";
import { ProteinsPage } from "@/pages/ProteinsPage";
import { ProteinDetailPage } from "@/pages/ProteinDetailPage";
import { ProteoformsPage } from "@/pages/ProteoformsPage";
import { ProteoformDetailPage } from "@/pages/ProteoformDetailPage";
import { PrsmsPage } from "@/pages/PrsmsPage";
import { PrsmDetailPage } from "@/pages/PrsmDetailPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/datasets" replace />} />
        <Route path="/datasets" element={<DatasetsPage />} />
        <Route path="/datasets/:slug" element={<DatasetPage />} />
        <Route path="/datasets/:slug/:cutoff/proteins" element={<ProteinsPage />} />
        <Route path="/datasets/:slug/:cutoff/proteins/:proteinId" element={<ProteinDetailPage />} />
        <Route path="/datasets/:slug/:cutoff/proteoforms" element={<ProteoformsPage />} />
        <Route
          path="/datasets/:slug/:cutoff/proteoforms/:proteoformId"
          element={<ProteoformDetailPage />}
        />
        <Route path="/datasets/:slug/:cutoff/prsms" element={<PrsmsPage />} />
        <Route path="/datasets/:slug/:cutoff/prsms/:prsmId" element={<PrsmDetailPage />} />
        <Route path="*" element={<Navigate to="/datasets" replace />} />
      </Route>
    </Routes>
  );
}
