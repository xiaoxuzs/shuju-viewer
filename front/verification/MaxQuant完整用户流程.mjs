// Visible Chromium, real product endpoints, no mocks or direct state mutations.
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const result = { passed: false, scope: "complete real single-sample MaxQuant; visible browser actions; ordinary model connection", steps: [], cases: [] };
const browser = await chromium.launch({ headless: false });
const context = await browser.newContext({ viewport: { width: 1400, height: 740 } });
await context.tracing.start({ screenshots: true, snapshots: true, sources: false });
const page = await context.newPage();
page.setDefaultTimeout(30000);
let sequence = 0;
function writeResult() { fs.writeFileSync(path.join(input.output, "用户流程.json"), JSON.stringify(result, null, 2)); }
async function screenshot(label) {
  const file = `${String(++sequence).padStart(2, "0")}-${label}.png`;
  await page.screenshot({ path: path.join(input.output, file) });
  result.steps.push({ label, time: new Date().toISOString(), screenshot: file, url: page.url() });
  writeResult();
  console.log(JSON.stringify({ event: "ui", label, screenshot: file, url: page.url() }));
}
async function get(relative) {
  const response = await context.request.get(input.origin + "/api/v1" + relative);
  if (!response.ok()) throw Error(`Read ${relative}: HTTP ${response.status()}`);
  return response.json();
}
async function artifacts(caseId) {
  const all = await get(`/agent-import-cases/${caseId}/artifacts`);
  const plans = all.filter(item => ["candidate_plan", "candidate"].includes(item.artifact_type) && item.structured_payload?.status === "READY");
  return { plan: plans.at(-1)?.structured_payload, model_requests: all.filter(item => item.artifact_type === "model_request").map(item => item.structured_payload) };
}
async function submit(button, suffix) {
  const received = page.waitForResponse(response => response.url().endsWith(suffix) && response.request().method() === "POST", { timeout: 120000 });
  await button.click();
  const response = await received;
  if (!response.ok()) throw Error(`UI submission ${suffix}: HTTP ${response.status()} ${await response.text()}`);
  return response.json();
}
async function followCase(created, label) {
  const begun = Date.now();
  const record = { case_id: created.case_id, phases: [], label };
  result.cases.push(record);
  let previous;
  while (Date.now() - begun < input.max_flow_seconds * 1000) {
    const state = await get(`/agent-import-cases/${created.case_id}`);
    if (state.status !== previous) {
      record.phases.push({ status: state.status, seconds: (Date.now() - begun) / 1000, at: new Date().toISOString() });
      previous = state.status; writeResult();
      console.log(JSON.stringify({ event: "phase", label, ...record.phases.at(-1) }));
    }
    if (state.status === "READY_FOR_REVIEW") {
      await screenshot(label + "-待批准");
      await submit(page.getByRole("button", { name: "Approve and import", exact: true }), `/agent-import-cases/${created.case_id}/review/approve`);
    }
    if (state.status === "SUCCESS") {
      await page.getByText("Dataset import complete", { exact: true }).waitFor();
      record.elapsed_seconds = (Date.now() - begun) / 1000;
      record.dataset_id = state.dataset_id; record.dataset_slug = state.dataset_slug;
      const evidence = await artifacts(created.case_id);
      record.model_requests = evidence.model_requests; record.requested_views = evidence.plan?.zp_conversion_plan?.declarative_plan?.requested_views;
      record.plan = evidence.plan;
      await screenshot(label + "-成功");
      return record;
    }
    if (["FAILED", "STOPPED", "NEEDS_USER", "WAITING_AUTHORIZATION"].includes(state.status)) {
      record.failure = { status: state.status, verification: state.verification };
      await screenshot(label + "-失败");
      throw Error(`${label}: ${state.status}: ${state.verification?.failure_code ?? "unknown failure"}`);
    }
    await page.waitForTimeout(2000);
  }
  throw Error(`${label} exceeded its ${input.max_flow_seconds}s observation window`);
}
async function browseDataset(record, label) {
  await page.getByRole("link", { name: "Open dataset", exact: true }).click();
  await screenshot(label + "-数据集");
  await page.getByRole("link", { name: "Matches", exact: true }).click();
  await page.locator("table tbody tr").first().waitFor();
  await screenshot(label + "-匹配列表");
  const counts = await get(`/datasets/${record.dataset_slug}/overview`);
  record.overview = counts;
  await page.goto(input.origin + `/agent-import-cases/${record.case_id}`);
  await page.getByText("SUCCESS", { exact: true }).waitFor();
}
try {
  let recipe, fixed;
  if (input.resume_case_id) {
    const state = await get(`/agent-import-cases/${input.resume_case_id}`);
    if (state.status !== "SUCCESS") throw Error("Repair continuation requires the retained published dataset");
    const evidence = await artifacts(state.case_id);
    fixed = { case_id: state.case_id, dataset_id: state.dataset_id, dataset_slug: state.dataset_slug,
      plan: evidence.plan, model_requests: evidence.model_requests, requested_views: evidence.plan.zp_conversion_plan.declarative_plan.requested_views };
    recipe = (await get("/import-recipes")).find(item => item.recipe_id === input.recipe_id);
    if (!recipe) throw Error("Original saved import recipe was not retained");
    result.recipe = recipe;
    result.cases.push({ ...fixed, label: "已发布固定导入的修复继续", source_reused: true });
    await page.goto(input.origin + `/agent-import-cases/${state.case_id}`);
    await page.getByText("SUCCESS", { exact: true }).waitFor();
    await screenshot("原成功数据集保留");
  } else {
  await page.goto(input.origin + "/datasets");
  await page.getByRole("button", { name: "Upload local dataset", exact: true }).waitFor();
  await screenshot("空白工作区");
  await page.getByRole("button", { name: "Upload local dataset", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Upload local dataset", exact: true });
  await dialog.getByRole("radio", { name: "Unknown format import", exact: true }).click();
  await dialog.getByLabel("Server source directory", { exact: true }).fill(input.source);
  await screenshot("智能导入-AUTO-格式留空");
  result.initial_submitted_at = new Date().toISOString();
  const first = await submit(dialog.getByRole("button", { name: "Start format analysis", exact: true }), "/agent-import-cases/from-path");
  await dialog.getByRole("link", { name: "Open Agent case", exact: true }).click();
  const original = await followCase(first, "智能导入");
  await browseDataset(original, "智能导入");
  if (!original.plan) throw Error("Published case has no persisted declarative plan evidence");
  await page.getByLabel("Default import format name", { exact: true }).first().fill("MaxQuant 单样本 DDA");
  recipe = await submit(page.getByRole("button", { name: "Save default import", exact: true }).first(), `/agent-import-cases/${first.case_id}/import-recipe`);
  result.recipe = recipe;
  if (recipe.display_category !== "DDA") throw Error("DDA format was not placed in the correct default-import category");
  await screenshot("保存默认导入");
  await page.goto(input.origin + "/datasets");
  await page.getByRole("button", { name: "Upload local dataset", exact: true }).click();
  await dialog.getByRole("radio", { name: "DDA", exact: true }).click();
  await dialog.getByRole("radio", { name: recipe.name, exact: true }).click();
  await dialog.getByLabel("Saved import source folder", { exact: true }).fill(input.replay_source);
  await screenshot("默认入口-完整副本");
  const second = await submit(dialog.getByRole("button", { name: "Start saved import", exact: true }), `/import-recipes/${recipe.recipe_id}/from-path`);
  await dialog.getByRole("link", { name: "Open import progress", exact: true }).click();
  fixed = await followCase(second, "固定默认导入");
  if (fixed.model_requests.length !== 0) throw Error("Fixed import unexpectedly called a model role");
  await browseDataset(fixed, "固定默认导入");
  }
  // Pause after actual imports: choose a grounded display improvement from their real plan.
  result.status = "AWAITING_FEEDBACK_SELECTION";
  writeResult();
  console.log(JSON.stringify({ event: "ready_for_feedback", case_id: fixed.case_id, requested_views: fixed.requested_views, output: input.output }));
  const feedbackPath = path.join(input.output, "反馈选择.json");
  const until = Date.now() + 900000;
  while (!fs.existsSync(feedbackPath) && Date.now() < until) await page.waitForTimeout(1000);
  if (!fs.existsSync(feedbackPath)) throw Error("Feedback selection was not supplied within its observation window");
  const selection = JSON.parse(fs.readFileSync(feedbackPath, "utf8"));
  result.feedback = selection.feedback;
  await page.getByLabel("Published delivery feedback", { exact: true }).fill(selection.feedback);
  await screenshot("提交实际反馈");
  const maintenance = await submit(page.getByRole("button", { name: "Send delivery feedback", exact: true }), `/agent-import-cases/${fixed.case_id}/maintenance`);
  result.maintenance_task_id = maintenance.task_id;
  let task;
  const maintenanceBegun = Date.now();
  while (Date.now() - maintenanceBegun < input.max_flow_seconds * 1000) {
    task = (await get(`/agent-import-cases/${fixed.case_id}/maintenance`)).find(item => item.task_id === maintenance.task_id);
    if (task.state === "PUBLISHED") break;
    if (["FAILED", "NEEDS_USER", "ENGINEERING_BLOCKED", "AWAITING_REVISION_VALIDATION", "RECONCILIATION_REQUIRED"].includes(task.state)) {
      result.maintenance = task; await screenshot("修复失败"); throw Error(`Maintenance ${task.state}: ${task.wait_reason}`);
    }
    await page.waitForTimeout(2000);
  }
  if (task?.state !== "PUBLISHED") throw Error("Repair did not finish within its observation window");
  result.maintenance = { task_id: task.task_id, state: task.state, published_revision_id: task.published_revision_id, candidate_sha256: task.candidate_sha256 };
  await page.getByText("Repair validated and applied.", { exact: true }).waitFor();
  await screenshot("真实修复已应用");
  await page.getByRole("link", { name: "Open repaired dataset", exact: true }).click();
  await screenshot("修复后结果");
  const dataset = await context.request.get(input.origin + `/api/v1/datasets/${fixed.dataset_slug}`);
  result.active_revision = dataset.headers()["x-viewer-revision"];
  if (result.active_revision !== task.published_revision_id) throw Error("Browser result did not read the repaired revision");
  await page.goto(input.origin + `/agent-import-cases/${fixed.case_id}`);
  await page.getByText("Repair validated and applied.", { exact: true }).waitFor();
  await page.getByLabel("Default import format name", { exact: true }).last().fill(recipe.name);
  await page.getByLabel("Default import to update", { exact: true }).last().selectOption(recipe.recipe_id);
  result.updated_recipe = await submit(page.getByRole("button", { name: "Update default import", exact: true }), `/agent-import-cases/${fixed.case_id}/import-recipe`);
  if (result.updated_recipe.version !== 2) throw Error("Repair did not create a new default-import version");
  await screenshot("修复方案更新原默认入口");
  const restore = page.getByRole("button", { name: /^Restore version / }).first();
  await restore.waitFor();
  result.restored = await submit(restore, `/agent-import-cases/${fixed.case_id}/revisions/rollback`);
  await page.getByText("Previous dataset version restored.", { exact: true }).waitFor();
  await screenshot("恢复旧版本");
  const restored = await context.request.get(input.origin + `/api/v1/datasets/${fixed.dataset_slug}`);
  if (restored.headers()["x-viewer-revision"] !== result.restored.active_revision_id) throw Error("Restored result does not match its active revision");
  result.passed = true; result.status = "PASSED_REAL_USER_FLOW";
} catch (error) {
  result.status = "FAILED"; result.error = String(error);
  for (const item of result.cases) {
    const evidence = await artifacts(item.case_id).catch(() => null);
    if (evidence) { item.model_requests = evidence.model_requests; item.plan = evidence.plan; }
  }
  await screenshot("流程停点").catch(() => {});
  process.exitCode = 1;
} finally {
  writeResult();
  await context.tracing.stop({ path: path.join(input.output, "浏览器轨迹.zip") });
  await browser.close();
}
