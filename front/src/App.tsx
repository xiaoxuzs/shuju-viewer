/**
 * 应用路由：所有业务页挂在 `AppShell` 下，URL 模式为
 * `/datasets/:slug/:cutoff/(proteins|proteoforms|prsms)/...`。
 */
import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/app-shell";
import { DatasetsPage } from "@/pages/DatasetsPage";
import { ProteinsPage } from "@/pages/ProteinsPage";
import { ProteinDetailPage } from "@/pages/ProteinDetailPage";
import { ProteoformsPage } from "@/pages/ProteoformsPage";
import { ProteoformDetailPage } from "@/pages/ProteoformDetailPage";
import { PrsmsPage } from "@/pages/PrsmsPage";
import { PrsmDetailPage } from "@/pages/PrsmDetailPage";
import { DatasetModeGate } from "@/features/bu/routes/DatasetModeGate";
import { TdCutoffModeGate } from "@/features/bu/routes/TdCutoffModeGate";
import { BuModeOnly } from "@/features/bu/routes/BuModeOnly";
import { BuOverviewPage } from "@/features/bu/pages/BuOverviewPage";
import { BuProteinsPage } from "@/features/bu/pages/BuProteinsPage";
import { BuPeptidesPage } from "@/features/bu/pages/BuPeptidesPage";
import { BuMatchesPage } from "@/features/bu/pages/BuMatchesPage";
import { BuMatchDetailPage } from "@/features/bu/pages/BuMatchDetailPage";
import { BuProteinDetailPage } from "@/features/bu/pages/BuProteinDetailPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/datasets" replace />} />
        <Route path="/datasets" element={<DatasetsPage />} />
        <Route path="/datasets/:slug" element={<DatasetModeGate />}>
          <Route index element={<BuModeOnly><BuOverviewPage /></BuModeOnly>} />
          <Route path="proteins" element={<BuModeOnly><BuProteinsPage /></BuModeOnly>} />
          <Route path="proteins/:proteinId" element={<BuModeOnly><BuProteinDetailPage /></BuModeOnly>} />
          <Route path="peptides" element={<BuModeOnly><BuPeptidesPage /></BuModeOnly>} />
          <Route path="matches" element={<BuModeOnly><BuMatchesPage /></BuModeOnly>} />
          <Route path="matches/:matchId" element={<BuModeOnly><BuMatchDetailPage /></BuModeOnly>} />
        </Route>
        <Route element={<TdCutoffModeGate />}>
          <Route path="/datasets/:slug/:cutoff/proteins" element={<ProteinsPage />} />
          <Route path="/datasets/:slug/:cutoff/proteins/:proteinId" element={<ProteinDetailPage />} />
          <Route path="/datasets/:slug/:cutoff/proteoforms" element={<ProteoformsPage />} />
          <Route
            path="/datasets/:slug/:cutoff/proteoforms/:proteoformId"
            element={<ProteoformDetailPage />}
          />
          <Route path="/datasets/:slug/:cutoff/prsms" element={<PrsmsPage />} />
          <Route path="/datasets/:slug/:cutoff/prsms/:prsmId" element={<PrsmDetailPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/datasets" replace />} />
      </Route>
    </Routes>
  );
}
