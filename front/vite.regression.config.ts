import { defineConfig } from "vite";
import path from "node:path";
import base from "./vite.config";

// Mock UI regression must never proxy an accidental request to a real backend.
export default defineConfig({
  ...base,
  cacheDir: path.resolve(__dirname, "../.tmp/前端隔离回归缓存"),
  envDir: path.resolve(__dirname, "../.tmp/前端回归空环境"),
  server: { host: "127.0.0.1", port: 15516, strictPort: true, proxy: {},
    headers: { "X-Viewer-Mock-Run": process.env.VIEWER_MOCK_RUN_ID ?? "unowned" } },
});
