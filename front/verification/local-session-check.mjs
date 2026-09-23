// Real browser and HTTP. No route interception, preinstalled cookie or token.
import { chromium } from "@playwright/test";
import fs from "node:fs";

const input = JSON.parse(fs.readFileSync(0, "utf8"));
const browser = await chromium.launch({ headless: true });
const record = { scope: "real local session/upload/Case APIs; SQLite fixture, no model or data delivery", passed: false, assertions: [], cases: [] };
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(input.origin + "/datasets#viewer-handoff=" + input.handoff);
  await page.getByRole("button", { name: "Upload local dataset", exact: true }).waitFor();
  if (new URL(page.url()).hash) throw Error("Handoff was retained in URL");
  if (await page.getByLabel("Viewer operator token", { exact: true }).count()) throw Error("Permanent credential input returned");
  record.assertions.push("fresh-context launcher exchange; handoff removed; no permanent key input");
  for (const mode of ["files", "server"]) {
    await page.goto(input.origin + "/datasets");
    await page.getByRole("button", { name: "Upload local dataset", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Upload local dataset", exact: true });
    await dialog.getByRole("radio", { name: "Unknown format import", exact: true }).click();
    if (mode === "files") {
      await dialog.getByRole("button", { name: "Files on this computer", exact: true }).click();
      await dialog.getByLabel("Choose browser source files", { exact: true }).setInputFiles({ name: "measurements.tsv", mimeType: "text/tab-separated-values", buffer: Buffer.from("id\tvalue\none\t0\ntwo\t\n") });
    } else {
      await dialog.getByLabel("Server source directory", { exact: true }).fill(input.source);
    }
    await dialog.getByRole("button", { name: "Start format analysis", exact: true }).click();
    await dialog.getByText("Format analysis started", { exact: true }).waitFor({ timeout: 15000 });
    await dialog.getByRole("link", { name: "Open Agent case", exact: true }).click();
    await page.getByRole("heading", { name: "Unknown format", exact: true }).waitFor();
    record.cases.push({ mode, case_id: new URL(page.url()).pathname.split("/").at(-1) });
    record.assertions.push(mode + " selection -> real upload/admission -> Case persisted -> Case page loaded");
  }
  const anonymous = await browser.newContext();
  const blocked = await anonymous.newPage();
  await blocked.goto(input.origin + "/agent-import-cases/" + record.cases[0].case_id);
  await blocked.getByText("Unable to load this Agent import case.", { exact: true }).waitFor({ timeout: 15000 });
  record.assertions.push("second unauthenticated browser cannot read first browser Case");
  await anonymous.close();
  await context.close();
  record.passed = true;
} catch (error) {
  record.error = String(error).replaceAll(input.handoff, "<redacted-handoff>");
  process.exitCode = 1;
} finally {
  await browser.close();
  fs.writeFileSync(input.output, JSON.stringify(record, null, 2));
}
