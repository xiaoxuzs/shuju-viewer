/**
 * Vite 配置：`@` 指向 `src`；开发服务器将 `/api` 代理到本机 FastAPI（默认 8000），
 * 与前端 axios `baseURL: "/api/v1"` 配合实现同源请求。
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
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
