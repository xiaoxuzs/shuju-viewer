/**
 * 入口：挂载 React、React Router 与 TanStack Query。
 * Query 默认关闭窗口聚焦自动刷新，30s 内视为新鲜数据，失败重试 1 次。
 */
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import App from "./App";
import { ThemeProvider } from "./features/theme/theme";
import { PageTransitionProvider } from "./features/page-transition";
import "./styles/globals.css";

document.documentElement.dataset.viewerBuildId = import.meta.env.VITE_VIEWER_BUILD_ID ?? "development";
document.documentElement.dataset.viewerValidationId = import.meta.env.VITE_VIEWER_VALIDATION_ID ?? "";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      retry: 1,
    },
  },
});

// Shared workspace: no login/handoff is required to render or import.
// Discard an obsolete handoff fragment without consuming or transmitting it.
if (new URLSearchParams(window.location.hash.slice(1)).has("viewer-handoff")) {
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
}
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <PageTransitionProvider>
            <App />
          </PageTransitionProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
