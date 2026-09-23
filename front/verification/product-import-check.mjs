// Real app UI and HTTP, shared workspace: no handoff, cookies or token injection.
import { chromium } from "@playwright/test";
import fs from "node:fs";
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const browser = await chromium.launch({ headless: true });
const record = { passed: false, scope: "fresh-browser shared workspace, no login; delivery checked separately" };
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(input.origin + "/datasets");
  await page.getByRole("button", { name: "Upload local dataset", exact: true }).waitFor();
  record.login_required = false;
  if (input.mode === "delivery") {
    await page.goto(input.origin + "/agent-import-cases/" + input.caseId);
    await page.getByText("SUCCESS", { exact: true }).waitFor();
    const downloaded = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download HANDOVER.md", exact: true }).click();
    const download = await downloaded;
    if (await download.failure()) throw Error("HANDOVER download failed");
    record.handover_downloaded = download.suggestedFilename() === "HANDOVER.md";
    if (input.feedback) {
      await page.getByLabel("Published delivery feedback", { exact: true }).fill(input.feedback);
      const feedbackResponse = page.waitForResponse(r => r.url().endsWith("/maintenance") && r.request().method() === "POST");
      await page.getByRole("button", { name: "Send delivery feedback", exact: true }).click();
      const registered = await feedbackResponse;
      if (!registered.ok()) throw Error("Feedback submission failed");
      record.maintenance_task = (await registered.json()).task_id;
    }
    await page.getByRole("link", { name: "Open dataset", exact: true }).click();
    await page.getByRole("link", { name: "Matches", exact: true }).click();
    if (input.real_source) {
      await page.locator("table tbody tr").first().waitFor();
    } else {
      await page.getByText("PEPTIDE", { exact: true }).first().waitFor();
      await page.getByText("ANOTHER", { exact: true }).first().waitFor();
    }
    record.dataset_path = new URL(page.url()).pathname;
    record.passed = true;
  } else {
  await page.getByRole("button", { name: "Upload local dataset", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Upload local dataset", exact: true });
  await dialog.getByRole("radio", { name: "Unknown format import", exact: true }).click();
  if (!input.blank_format) {
    await dialog.getByRole("radio", { name: "Bottom-Up", exact: true }).click();
    await dialog.locator("#unknown-format-name").fill(input.profile);
    await dialog.getByRole("button", { name: "Add format details", exact: true }).click();
    await dialog.locator("#unknown-format-details").fill(input.details);
  }
  await dialog.getByLabel("Server source directory", { exact: true }).fill(input.source);
  const response = page.waitForResponse(r => r.url().endsWith("/agent-import-cases/from-path") && r.request().method() === "POST");
  const submittedAt = Date.now();
  record.submitted_at = new Date(submittedAt).toISOString();
  await dialog.getByRole("button", { name: "Start format analysis", exact: true }).click();
  const result = await response;
  if (result.status() !== 201) throw Error("Case creation HTTP " + result.status());
  record.case = await result.json();
  if (record.case.status !== "CREATED") throw Error("Normal Case was not queued under its server task policy: " + record.case.status);
  await dialog.getByRole("link", { name: "Open Agent case", exact: true }).click();
  await page.getByRole("heading", { name: input.profile, exact: true }).waitFor();
  if (input.follow_to_delivery) {
    const maxFlowSeconds = input.max_flow_seconds ?? 1200;
    if (!Number.isInteger(maxFlowSeconds) || maxFlowSeconds < 60 || maxFlowSeconds > 1500) throw Error("Invalid acceptance observation window");
    record.phases = [];
    let previous;
    let approved = false;
    while (Date.now() - submittedAt < maxFlowSeconds * 1000) {
      const stateResponse = await context.request.get(input.origin + "/api/v1/agent-import-cases/" + record.case.case_id);
      if (!stateResponse.ok()) throw Error("Case polling HTTP " + stateResponse.status());
      const state = await stateResponse.json();
      if (state.status !== previous) {
        record.phases.push({ status: state.status, seconds: (Date.now() - submittedAt) / 1000 });
        previous = state.status;
        console.log(JSON.stringify(record.phases.at(-1)));
      }
      if (state.status === "READY_FOR_REVIEW" && !approved) {
        const approval = page.waitForResponse(r => r.url().endsWith("/review/approve") && r.request().method() === "POST", { timeout: 60000 });
        await page.getByRole("button", { name: "Approve and import", exact: true }).click();
        if (!(await approval).ok()) throw Error("Normal reviewed import failed");
        approved = true;
      }
      if (["FAILED", "NEEDS_USER", "STOPPED", "WAITING_AUTHORIZATION"].includes(state.status)) {
        record.first_failure = { status: state.status, verification: state.verification?.failure_code ?? null };
        throw Error("Fresh normal Case stopped at " + state.status);
      }
      if (state.status === "SUCCESS") {
        await page.getByText("Dataset import complete", { exact: true }).waitFor();
        await page.getByRole("link", { name: "Open dataset", exact: true }).click();
        await page.getByRole("link", { name: "Matches", exact: true }).click();
        await page.locator("table tbody tr").first().waitFor();
        record.dataset_id = state.dataset_id;
        record.dataset_path = new URL(page.url()).pathname;
        record.submit_to_browsable_seconds = (Date.now() - submittedAt) / 1000;
        record.timing_target_met = record.submit_to_browsable_seconds <= maxFlowSeconds;
        record.completed_at = new Date().toISOString();
        if (!record.timing_target_met) throw Error("Delivery succeeded but the submit-to-browsable timing target was exceeded");
        record.passed = true;
        break;
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    if (!record.passed) {
      await context.request.post(input.origin + "/api/v1/agent-import-cases/" + record.case.case_id + "/stop");
      throw Error(`Fresh browser import exceeded its ${maxFlowSeconds}s acceptance window; cancellation requested`);
    }
  } else {
  // Identical browser-upload submission must hit the same domain admission and
  // reuse the same Case, not create a second runtime or logical dataset.
  await page.goto(input.origin + "/datasets");
  await page.getByRole("button", { name: "Upload local dataset", exact: true }).click();
  await dialog.getByRole("radio", { name: "Unknown format import", exact: true }).click();
  if (!input.blank_format) {
    await dialog.getByRole("radio", { name: "Bottom-Up", exact: true }).click();
    await dialog.locator("#unknown-format-name").fill(input.profile);
    await dialog.getByRole("button", { name: "Add format details", exact: true }).click();
    await dialog.locator("#unknown-format-details").fill(input.details);
  }
  await dialog.getByRole("button", { name: "Files on this computer", exact: true }).click();
  await dialog.getByLabel("Choose browser source files", { exact: true }).setInputFiles(input.source + "/unknown-results.tsv");
  const uploaded = page.waitForResponse(r => r.url().endsWith("/agent-import-cases/from-upload") && r.request().method() === "POST");
  await dialog.getByRole("button", { name: "Start format analysis", exact: true }).click();
  const uploadResponse = await uploaded;
  if (uploadResponse.status() !== 201) throw Error("Upload admission HTTP " + uploadResponse.status());
  record.upload_case = await uploadResponse.json();
  if (record.upload_case.case_id !== record.case.case_id) throw Error("Identical source submission created another Case");
  const anonymous = await browser.newContext();
  const denied = await anonymous.request.get(input.origin + "/api/v1/agent-import-cases/" + record.case.case_id);
  if (denied.status() !== 200) throw Error("Shared workspace unexpectedly requires login");
  record.fresh_browser_read_without_login = true;
  const admin = await anonymous.request.get(input.origin + "/api/v1/agent-retention/dry-run");
  if (admin.status() !== 403) throw Error("Internal administration became public");
  record.internal_management_denied = true;
  await anonymous.close();
  if (input.outside_source) {
    await page.goto(input.origin + "/datasets");
    await page.getByRole("button", { name: "Upload local dataset", exact: true }).click();
    await dialog.getByRole("radio", { name: "Unknown format import", exact: true }).click();
    await dialog.getByLabel("Server source directory", { exact: true }).fill(input.outside_source);
    const deniedPath = page.waitForResponse(r => r.url().endsWith("/agent-import-cases/from-path") && r.request().method() === "POST");
    await dialog.getByRole("button", { name: "Start format analysis", exact: true }).click();
    if (![400, 403, 422].includes((await deniedPath).status())) throw Error("Out-of-scope path not rejected");
    record.outside_path_denied = true;
  }
  record.passed = true;
  }
  }
  await context.close();
} catch (error) {
  record.error = String(error);
  process.exitCode = 1;
} finally {
  await browser.close();
  fs.writeFileSync(input.output, JSON.stringify(record, null, 2));
}
