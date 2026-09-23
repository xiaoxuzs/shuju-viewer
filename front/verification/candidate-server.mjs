// Trusted validator launcher. Runs a fresh build from the supplied source snapshot.
// Not a general-purpose command service or a sandbox for model-generated code.
import { build, preview } from "vite";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";

const [root, portText, apiPort, buildId, validationId] = process.argv.slice(2);
if (!root || !/^\d+$/.test(portText) || !/^\d+$/.test(apiPort) || !/^[a-f0-9]{64}$/.test(buildId)) throw Error("Invalid candidate launcher arguments");
if (!/^[a-f0-9]{64}$/.test(validationId)) throw Error("Candidate run identity is required");
const dependencies = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../node_modules");
// A read-only-in-practice dependency reference for trusted code, NOT sandboxing.
// Snapshot sources/config remain separate; no npm install, old dist, or service reuse.
fs.symlinkSync(dependencies, path.join(root, "node_modules"), process.platform === "win32" ? "junction" : "dir");
const config = {
  configFile: path.join(root, "vite.config.ts"), root,
  define: { "import.meta.env.VITE_VIEWER_BUILD_ID": JSON.stringify(buildId), "import.meta.env.VITE_VIEWER_VALIDATION_ID": JSON.stringify(validationId) },
  build: { outDir: path.join(root, "candidate-dist"), emptyOutDir: false },
  preview: { host: "127.0.0.1", port: Number(portText), strictPort: true,
    proxy: { "/api": { target: `http://127.0.0.1:${apiPort}`, changeOrigin: false } } },
};
await build(config);
await preview(config);
