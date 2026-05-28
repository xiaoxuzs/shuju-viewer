/**
 * Vite config: `@` -> `src`; dev server proxies `/api` to FastAPI on port 7000.
 */
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 6100,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:7000",
        changeOrigin: true,
      },
    },
  },
});
