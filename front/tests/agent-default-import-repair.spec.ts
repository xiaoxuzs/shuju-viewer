import { expect, test, type Route } from "@playwright/test";

const delivery = {
  case_id: "published-case", workspace_id: "default", status: "SUCCESS", source_mode: "LOCAL_PATH",
  source_ref: "agent-case:published-case", dataset_fingerprint: "a".repeat(32), analysis_category: "BOTTOM_UP",
  source_profile: "MaxQuant", format_details: null, interaction_mode: "guided", autonomous_attempt_used: 0,
  guided_attempt_no: 1, context_revision: 1, version: 8, stop_requested_at: null,
  candidate_zp_sha256: "b".repeat(64), dataset_id: 2, dataset_slug: "example", verification: null,
  ever_published: true, created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:00Z",
};
const recipe = { recipe_id: "recipe-1", name: "MaxQuant", version: 1, parent_case_id: "published-case",
  analysis_category: "BOTTOM_UP", display_category: "DDA" };
async function json(route: Route, body: unknown) { await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) }); }

test("published format is saved under its default-import category and reused", async ({ page }) => {
  let saved = false;
  let submitted: unknown;
  await page.route("**/api/v1/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/import-recipe")) { saved = true; return json(route, recipe); }
    if (path === "/api/v1/import-recipes") return json(route, saved ? [recipe] : []);
    if (path.endsWith("/recipe-1/from-path")) { submitted = request.postDataJSON(); return json(route, { case_id: "fresh-case", status: "CREATED", version: 1 }); }
    if (path.endsWith("/published-case")) return json(route, delivery);
    if (path.endsWith("/revisions")) return json(route, { active_revision_id: "legacy", revisions: [] });
    return json(route, []);
  });
  await page.goto("/agent-import-cases/published-case");
  await page.getByRole("button", { name: "Save default import", exact: true }).click();
  await expect(page.getByText("MaxQuant v1 is available in DDA default imports.")).toBeVisible();
  await page.goto("/datasets");
  await page.getByRole("button", { name: "Upload local dataset" }).click();
  const dialog = page.getByRole("dialog", { name: "Upload local dataset" });
  await dialog.getByRole("radio", { name: "Bottom-Up", exact: true }).click();
  await expect(dialog.getByRole("radio", { name: "MaxQuant", exact: true })).toHaveCount(0);
  await dialog.getByRole("radio", { name: "DDA", exact: true }).click();
  await dialog.getByRole("radio", { name: "MaxQuant", exact: true }).click();
  await dialog.getByLabel("Saved import source folder").fill("/fixture/new-data");
  await dialog.getByRole("button", { name: "Start saved import" }).click();
  await expect(dialog.getByRole("link", { name: "Open import progress" })).toHaveAttribute("href", "/agent-import-cases/fresh-case");
  expect(submitted).toEqual({ source_path: "/fixture/new-data", version: 1 });
});

for (const saved of [false, true]) {
  test(`${saved ? "saved" : "smart"} import explicitly reports an existing published source`, async ({ page }) => {
    await page.route("**/api/v1/**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/v1/import-recipes") return json(route, [recipe]);
      if (path.endsWith("/from-path")) return json(route, { case_id: "published-case", status: "SUCCESS", version: 8 });
      return json(route, []);
    });
    await page.goto("/datasets");
    await page.getByRole("button", { name: "Upload local dataset" }).click();
    const dialog = page.getByRole("dialog", { name: "Upload local dataset" });
    if (saved) {
      await dialog.getByRole("radio", { name: "DDA", exact: true }).click();
      await dialog.getByRole("radio", { name: "MaxQuant", exact: true }).click();
      await dialog.getByLabel("Saved import source folder").fill("/fixture/existing-data");
      await dialog.getByRole("button", { name: "Start saved import" }).click();
    } else {
      await dialog.getByRole("radio", { name: "Unknown format import", exact: true }).click();
      await dialog.getByLabel("Server source directory").fill("/fixture/existing-data");
      await dialog.getByRole("button", { name: "Start format analysis" }).click();
    }
    await expect(dialog.getByText(/^Source already imported/)).toBeVisible();
    await expect(dialog.getByText("Format analysis started", { exact: true })).toHaveCount(0);
    await expect(dialog.getByRole("link", { name: saved ? "Open existing result" : "Open Agent case", exact: true }))
      .toHaveAttribute("href", "/agent-import-cases/published-case");
  });
}

test("retrying a historical duplicate opens its existing delivery and keeps the failed case separate", async ({ page }) => {
  let retries = 0;
  const failed = { ...delivery, case_id: "failed-duplicate", status: "FAILED", ever_published: false,
    dataset_id: null, dataset_slug: null, version: 3, verification: { failure_code: "PUBLISHED_CASE_ROLE_FORBIDDEN" } };
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/failed-duplicate/retry")) {
      expect(route.request().headers()["if-match"]).toBe("3");
      retries++;
      return json(route, delivery);
    }
    if (path.endsWith("/failed-duplicate")) return json(route, failed);
    if (path.endsWith("/published-case")) return json(route, delivery);
    if (path.endsWith("/revisions")) return json(route, { active_revision_id: "legacy", revisions: [] });
    return json(route, []);
  });
  await page.goto("/agent-import-cases/failed-duplicate");
  await page.getByRole("button", { name: "Retry failed task" }).click();
  await expect(page).toHaveURL(/\/agent-import-cases\/published-case$/);
  await expect(page.getByRole("link", { name: "Open dataset", exact: true })).toHaveAttribute("href", "/datasets/example");
  await expect(page.getByRole("button", { name: "Retry failed task" })).toHaveCount(0);
  await page.goto("/agent-import-cases/failed-duplicate");
  await expect(page.getByRole("button", { name: "Retry failed task" })).toBeVisible();
  expect(retries).toBe(1);
});

test("feedback shows repair completion, updated result and a working rollback", async ({ page }) => {
  let queued = false;
  let rolledBack = false;
  await page.route("**/api/v1/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/published-case")) return json(route, delivery);
    if (path === "/api/v1/import-recipes") return json(route, [{ ...recipe, parent_case_id: "original-dataset-case" }]);
    if (path.endsWith("/import-recipe")) {
      expect(request.postDataJSON()).toEqual({ name: "MaxQuant", recipe_id: "recipe-1", expected_version: 1, maintenance_task_id: "repair-1" });
      return json(route, { ...recipe, version: 2 });
    }
    if (path.endsWith("/maintenance")) {
      if (request.method() === "POST") { queued = true; return json(route, { task_id: "repair-1", state: "QUEUED" }); }
      return json(route, queued ? [{ task_id: "repair-1", state: "PUBLISHED", published_revision_id: "new-version" }] : []);
    }
    if (path.endsWith("/revisions/rollback")) {
      expect(request.postDataJSON()).toEqual({ revision_id: "old-version", expected_base: "new-version" });
      rolledBack = true;
      return json(route, { active_revision_id: "old-version", revisions: [{ revision_id: "old-version", state: "ACTIVE" }, { revision_id: "new-version", state: "RETIRED" }] });
    }
    if (path.endsWith("/revisions")) return json(route, queued ? { active_revision_id: "new-version", revisions: [{ revision_id: "old-version", state: "RETIRED" }, { revision_id: "new-version", state: "ACTIVE" }] } : { active_revision_id: "legacy", revisions: [] });
    return json(route, []);
  });
  await page.goto("/agent-import-cases/published-case");
  await page.getByLabel("Published delivery feedback").fill("Improve the display.");
  await page.getByRole("button", { name: "Send delivery feedback" }).click();
  await expect(page.getByText("Repair validated and applied.", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open repaired dataset" })).toHaveAttribute("href", "/datasets/example");
  await page.getByLabel("Default import format name").last().fill("MaxQuant");
  await page.getByLabel("Default import to update").last().selectOption("recipe-1");
  await page.getByRole("button", { name: "Update default import", exact: true }).click();
  await expect(page.getByText("MaxQuant v2 is available in DDA default imports.")).toBeVisible();
  await page.getByRole("button", { name: "Restore version old-vers" }).click();
  await expect(page.getByText("Previous dataset version restored.")).toBeVisible();
  expect(rolledBack).toBe(true);
});
