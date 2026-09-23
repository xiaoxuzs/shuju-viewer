import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

if (!process.env.VIEWER_MOCK_RUN_ID) throw new Error("Use cs/前端隔离回归.py to own and identify the regression server");
if (!process.env.VIEWER_MOCK_OUTPUT) throw new Error("A new explicit evidence directory is required");
const seconds = Number(process.env.VIEWER_MOCK_SECONDS ?? 180);
if (!Number.isInteger(seconds) || seconds < 30 || seconds > 900) throw new Error("Invalid bounded test deadline");

export default defineConfig({
  testDir: "./tests", fullyParallel: false, workers: 1,
  outputDir: path.join(process.env.VIEWER_MOCK_OUTPUT, "artifacts"),
  reporter: [["line"], ["json", { outputFile: path.join(process.env.VIEWER_MOCK_OUTPUT, "results.json") }]],
  use: { baseURL: "http://127.0.0.1:15516", trace: "retain-on-failure" },
  globalTimeout: seconds * 1000,
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
