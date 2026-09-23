import { expect, test, type Route } from "@playwright/test";

function casePayload(status: string, code = "AGENT_CANDIDATE_SCHEMA_INVALID") {
  return {
    case_id: "diagnostic-case", workspace_id: "default", status,
    source_mode: "LOCAL_PATH", source_ref: "agent-case:diagnostic-case",
    dataset_fingerprint: "a".repeat(32), analysis_category: "AUTO", source_profile: "Unknown dataset",
    format_details: null, interaction_mode: "guided", autonomous_attempt_used: 0, guided_attempt_no: 1,
    context_revision: 2, version: status === "STRATEGY_READY" ? 8 : 9,
    stop_requested_at: null, candidate_zp_sha256: null, dataset_id: null, dataset_slug: null,
    created_at: "2026-09-07T05:00:00Z", updated_at: "2026-09-07T05:10:00Z",
    verification: status === "STRATEGY_READY" ? null : {
      failure_code: code,
      failure_class: status === "FAILED" ? "ENGINEERING_REVIEW" : "USER_INPUT",
      summary: "Candidate validation failed: zp_conversion_plan.sources.0.reader: Invalid reader",
    },
  };
}

function artifact() {
  return {
    artifact_id: "rejected-1", case_id: "diagnostic-case", attempt_id: null,
    artifact_type: "candidate_diagnostic", storage_ref: "agent-artifact:rejected-1",
    sha256: "b".repeat(64), size_bytes: 200, media_type: "application/json", created_at: "2026-09-07T05:10:00Z",
    structured_payload: {
      schema_version: 1, context_revision: 2, candidate_attempt: 1, kind: "schema_rejected",
      errors: [{ loc: ["zp_conversion_plan", "sources", 0, "reader"], type: "literal_error", msg: "Invalid reader" }],
      candidate: { extra: "[REDACTED]" },
    },
  };
}

async function json(route: Route, body: unknown) {
  await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
}

for (const status of ["FAILED", "NEEDS_USER"]) {
  test(`schema failure ${status} shows diagnostics without requesting an answer`, async ({ page }) => {
    await page.route("**/api/v1/**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/diagnostic-case")) return json(route, casePayload(status));
      if (path.endsWith("/artifacts")) return json(route, [artifact()]);
      return json(route, []);
    });
    await page.goto("/agent-import-cases/diagnostic-case");
    await expect(page.getByTestId("agent-engineering-error")).toBeVisible();
    await expect(page.getByRole("button", { name: "Send answer" })).toHaveCount(0);
    await expect(page.getByTestId("candidate-diagnostic")).toContainText("zp_conversion_plan.sources.0.reader");
    await expect(page.getByTestId("candidate-diagnostic")).toContainText("Candidate attempt 1 · revision 2");
    await page.getByText("Inspect redacted rejected candidate").click();
    await expect(page.getByTestId("candidate-diagnostic").locator("pre")).toContainText("[REDACTED]");
  });
}

test("real scientific ambiguity still offers the answer input", async ({ page }) => {
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    return json(route, path.endsWith("/diagnostic-case") ? casePayload("NEEDS_USER", "UNIT_AMBIGUOUS") : []);
  });
  await page.goto("/agent-import-cases/diagnostic-case");
  await expect(page.getByTestId("agent-engineering-error")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Send answer" })).toBeVisible();
});

test("entering a terminal state refreshes the final candidate diagnostics", async ({ page }) => {
  let failed = false;
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/diagnostic-case")) return json(route, casePayload(failed ? "FAILED" : "STRATEGY_READY"));
    if (path.endsWith("/artifacts")) return json(route, failed ? [artifact()] : []);
    return json(route, []);
  });
  await page.goto("/agent-import-cases/diagnostic-case");
  await expect(page.getByText("No artifacts yet.")).toBeVisible();
  failed = true;
  await expect(page.getByTestId("agent-engineering-error")).toBeVisible();
  await expect(page.getByTestId("candidate-diagnostic")).toBeVisible();
});
