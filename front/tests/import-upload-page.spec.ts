import { expect, test, type Locator, type Page, type Route } from "@playwright/test";

const ACTIVE_JOB_KEY = "viewer.activeImportJob";
const NOW = "2026-07-17T00:00:00.000Z";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/datasets", async (route) => {
    await json(route, []);
  });
});

test("analysis type reveals only its supported second-level import formats", async ({ page }) => {
  const oldPathRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname === "/api/v1/imports") oldPathRequests.push(request.url());
  });

  await page.goto("/datasets");
  await expect(page.getByRole("button", { name: "Agent-ZP import" })).toHaveCount(0);
  await page.getByRole("button", { name: "Upload local dataset" }).click();
  const dialog = page.getByRole("dialog", { name: "Upload local dataset" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Server folder", { exact: false })).toHaveCount(0);
  await expect(dialog.getByText("source path", { exact: false })).toHaveCount(0);
  await expect(dialog.getByText("import source", { exact: false })).toHaveCount(0);
  await expect(dialog.getByRole("radio", { name: "Supported format import", exact: true })).toHaveAttribute("aria-checked", "true");
  await expect(dialog.getByRole("radio", { name: "Unknown format import", exact: true })).toBeVisible();

  await dialog.getByRole("radio", { name: "Unknown format import", exact: true }).click();
  await expect(dialog.getByRole("heading", { name: "1. Analysis type" })).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "2. Import format" })).toBeVisible();
  await expect(dialog.locator("#unknown-format-details")).toHaveCount(0);
  await expect(dialog.getByText("Binary operation", { exact: false })).toHaveCount(0);
  await expect(dialog.getByText("Source profile", { exact: false })).toHaveCount(0);

  await dialog.getByRole("radio", { name: "Supported format import", exact: true }).click();

  for (const label of ["Top-Down", "Bottom-Up", "DDA"]) {
    await expect(dialog.getByRole("radio", { name: label, exact: true })).toBeVisible();
  }
  await expect(dialog.getByRole("heading", { name: "2. Import format" })).toHaveCount(0);
  await expect(dialog.getByRole("heading", { name: "3. Dataset information" })).toHaveCount(0);
  await expect(dialog.locator("#import-folder")).toHaveCount(0);

  await dialog.getByRole("radio", { name: "Top-Down", exact: true }).click();
  await expect(dialog.getByRole("heading", { name: "3. Dataset information" })).toHaveCount(0);
  for (const label of ["Thermo RAW", "mzML", "TopPIC HTML Output", "PrSM Detail Bundle", "TopPIC Native Output"]) {
    await expect(dialog.getByRole("radio", { name: label, exact: true })).toBeVisible();
  }
  await dialog.getByRole("radio", { name: "Thermo RAW", exact: true }).click();
  await expect(dialog.getByRole("heading", { name: "3. Dataset information" })).toBeVisible();
  await expect(dialog.locator("#import-files")).toHaveAttribute("accept", ".raw");
  await expect(dialog.locator("#import-folder")).toHaveAttribute("webkitdirectory", "");

  await dialog.getByRole("radio", { name: "mzML", exact: true }).click();
  await expect(dialog.locator("#import-files")).toHaveAttribute("accept", ".mzML,.mzml");

  for (const label of ["TopPIC HTML Output", "PrSM Detail Bundle", "TopPIC Native Output"]) {
    await dialog.getByRole("radio", { name: label, exact: true }).click();
    await expect(dialog.locator("#import-files")).toHaveCount(0);
    await expect(dialog.locator("#import-folder")).toHaveAttribute("webkitdirectory", "");
  }
  await dialog.getByRole("radio", { name: "Bottom-Up", exact: true }).click();
  await expect(dialog.getByRole("radio", { name: "DIA-NN", exact: true })).toBeVisible();
  await dialog.getByRole("radio", { name: "πdia-clip", exact: true }).click();
  await expect(dialog.getByRole("radio", { name: "TopPIC Native Output", exact: true })).toHaveCount(0);
  await expect(dialog.getByText("πdia-clip is a single-run Bottom-Up import", { exact: false })).toBeVisible();
  await expect(dialog.getByText("*.diaclip.fdr.parquet", { exact: false })).toBeVisible();
  await expect(dialog.getByText("legacy workflow", { exact: false })).toBeVisible();
  await expect(dialog.getByText("DIA-NN context", { exact: false })).toHaveCount(0);

  await dialog.getByRole("radio", { name: "DDA", exact: true }).click();
  await expect(dialog.getByRole("radio", { name: "Thermo RAW", exact: true })).toBeVisible();
  await expect(dialog.getByRole("radio", { name: "DIA-NN", exact: true })).toHaveCount(0);
  expect(oldPathRequests).toEqual([]);
});

test("unknown format import submits required identity and optional prompt context", async ({ page }) => {
  let requestBody: unknown = null;
  await page.route("**/api/v1/imports/pick-folder", async (route) => {
    await json(route, { path: "E:\\data\\new-format", cancelled: false });
  });
  await page.route("**/api/v1/agent-import-cases/from-path", async (route) => {
    requestBody = route.request().postDataJSON();
    await json(route, { case_id: "case-new-format", status: "CREATED", version: 1 }, 201);
  });

  await page.goto("/datasets");
  await page.getByRole("button", { name: "Upload local dataset" }).click();
  const dialog = page.getByRole("dialog", { name: "Upload local dataset" });
  await dialog.getByRole("radio", { name: "Unknown format import", exact: true }).click();

  const start = dialog.getByRole("button", { name: "Start format analysis" });
  await expect(start).toBeDisabled();
  for (const label of ["Top-Down", "Bottom-Up", "Spectra Only", "Custom"]) {
    await expect(dialog.getByRole("radio", { name: label, exact: true })).toBeVisible();
  }
  await dialog.getByRole("radio", { name: "Bottom-Up", exact: true }).click();
  await dialog.locator("#unknown-format-name").fill("DIA-CLIP");
  await dialog.getByRole("button", { name: "Add format details" }).click();
  await dialog.locator("#unknown-format-details").fill("One result TSV and one matching mzML file.");
  await dialog.getByRole("button", { name: "Select source folder" }).click();
  await expect(dialog.getByText("E:\\data\\new-format", { exact: true })).toBeVisible();
  await expect(start).toBeEnabled();
  await start.click();

  await expect(dialog.getByText("Format analysis started", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("link", { name: "Open Agent case" }))
    .toHaveAttribute("href", "/agent-import-cases/case-new-format");
  expect(requestBody).toEqual({
    source_path: "E:\\data\\new-format",
    data_type: "Bottom-Up",
    format_name: "DIA-CLIP",
    format_details: "One result TSV and one matching mzML file.",
  });
});

test("unknown format import accepts a trimmed custom analysis type without leaking it into presets", async ({ page }) => {
  let requestBody: unknown = null;
  await page.route("**/api/v1/imports/pick-folder", async (route) => {
    await json(route, { path: "E:\\data\\custom-analysis", cancelled: false });
  });
  await page.route("**/api/v1/agent-import-cases/from-path", async (route) => {
    requestBody = route.request().postDataJSON();
    await json(route, { case_id: "case-custom-analysis", status: "CREATED", version: 1 }, 201);
  });

  await page.goto("/datasets");
  await page.getByRole("button", { name: "Upload local dataset" }).click();
  const dialog = page.getByRole("dialog", { name: "Upload local dataset" });
  await dialog.getByRole("radio", { name: "Unknown format import", exact: true }).click();

  await dialog.getByRole("radio", { name: "Custom", exact: true }).click();
  const customDataType = dialog.getByLabel("Custom analysis type", { exact: true });
  await expect(customDataType).toHaveAttribute("maxlength", "80");
  await customDataType.fill("   ");
  await dialog.locator("#unknown-format-name").fill("New Format");
  await dialog.getByRole("button", { name: "Select source folder" }).click();
  const start = dialog.getByRole("button", { name: "Start format analysis" });
  await expect(start).toBeDisabled();

  await customDataType.fill("  Single-cell spatial proteomics  ");
  await dialog.getByRole("radio", { name: "Top-Down", exact: true }).click();
  await expect(dialog.getByLabel("Custom analysis type", { exact: true })).toHaveCount(0);
  await expect(start).toBeEnabled();
  await dialog.getByRole("radio", { name: "Custom", exact: true }).click();
  await expect(dialog.getByLabel("Custom analysis type", { exact: true }))
    .toHaveValue("  Single-cell spatial proteomics  ");
  await start.click();

  expect(requestBody).toEqual({
    source_path: "E:\\data\\custom-analysis",
    data_type: "Single-cell spatial proteomics",
    format_name: "New Format",
    format_details: null,
  });
});

test("Agent case exposes the validated .zp candidate and requires explicit approval", async ({ page }) => {
  let status = "READY_FOR_REVIEW";
  let approveHeaders: Record<string, string> | null = null;
  await page.route("**/api/v1/agent-import-cases/case-review**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/messages")) {
      await json(route, [
        {
          message_id: "message-strategy",
          case_id: "case-review",
          sequence_no: 1,
          context_revision: 0,
          sender_type: "AGENT_1",
          message_kind: "STATUS",
          content: "Agent 1 completed tool-backed dataset research.",
          structured_payload: {
            event: "strategy_ready",
            strategy: {
              blueprint: {
                dataset_family: "Agent-designed scientific dataset",
                executive_summary: "Local inspectors and official sources support this Blueprint.",
                source_assets: [{ relative_path: "sample.txt" }],
                scientific_entities: [{ entity_name: "identification" }],
                visualizations: [{ view_id: "overview" }],
              },
            },
          },
          created_at: NOW,
        },
        {
          message_id: "message-one",
          case_id: "case-review",
          sequence_no: 2,
          context_revision: 0,
          sender_type: "AGENT_2",
          message_kind: "STATUS",
          content: "A .zp candidate passed deep validation.",
          structured_payload: {
            event: "candidate_ready",
            candidate: {
              zp_conversion_plan: {
                mapping_plan: {
                  adapter_id: "agent_blueprint_profile_v1",
                  source_files: [{ relative_path: "evidence.txt" }],
                  field_mappings: [{ source_field: "Sequence" }],
                  unmapped_fields: { "evidence.txt": ["Extra column"] },
                },
              },
            },
          },
          created_at: NOW,
        },
        {
          message_id: "message-review",
          case_id: "case-review",
          sequence_no: 3,
          context_revision: 0,
          sender_type: "AGENT_1",
          message_kind: "EVIDENCE",
          content: "Agent 1 approved the mapping plan.",
          structured_payload: { event: "review_approved", review: { status: "APPROVED" } },
          created_at: NOW,
        },
      ]);
      return;
    }
    if (path.endsWith("/attempts")) {
      await json(route, [{
        attempt_id: "attempt-one",
        case_id: "case-review",
        attempt_no: 1,
        context_revision: 0,
        result: "SUCCESS",
        failure_code: null,
        started_at: NOW,
        finished_at: NOW,
      }]);
      return;
    }
    if (path.endsWith("/artifacts")) {
      await json(route, [{
        artifact_id: "artifact-one",
        case_id: "case-review",
        attempt_id: "attempt-one",
        artifact_type: "ZP_BINARY",
        storage_ref: "agent-artifact:artifact-one",
        sha256: "b".repeat(64),
        size_bytes: 4096,
        media_type: "application/octet-stream",
        created_at: NOW,
      }]);
      return;
    }
    if (path.endsWith("/review/approve")) {
      approveHeaders = request.headers();
      status = "SUCCESS";
      await json(route, agentCase(status));
      return;
    }
    await json(route, agentCase(status));
  });

  await page.goto("/agent-import-cases/case-review");
  await expect(page.getByText("A .zp candidate passed deep validation.")).toBeVisible();
  await expect(page.getByText("ZP_BINARY", { exact: true })).toBeVisible();
  await expect(page.getByText("ZP mapping plan", { exact: true })).toBeVisible();
  await expect(page.getByText("Agent 1 Dataset Blueprint", { exact: true })).toBeVisible();
  await expect(page.getByText("Agent-designed scientific dataset", { exact: true })).toBeVisible();
  await expect(page.getByText("agent_blueprint_profile_v1", { exact: true })).toBeVisible();
  await expect(page.getByText("APPROVED", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve and import" })).toBeVisible();
  await page.getByRole("button", { name: "Approve and import" }).click();

  await expect(page.getByText("Dataset import complete", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open dataset" }))
    .toHaveAttribute("href", "/datasets/agent-output");
  expect(approveHeaders?.["if-match"]).toBe('"4"');
});

test("local files upload sequentially, auto-start ImportJob, and clear restored state on success", async ({ page }) => {
  await installBeforeUnloadAudit(page);
  const uploadOrder: string[] = [];
  let activeUploads = 0;
  let maxActiveUploads = 0;
  let startBody: unknown = null;
  let jobPolls = 0;
  const oldPathRequests: string[] = [];

  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname === "/api/v1/imports") oldPathRequests.push(request.url());
  });
  await page.route("**/api/v1/import-uploads", async (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual({ import_type: "TD_MZML" });
    await json(route, {
      upload_id: "upload-one",
      import_type: "TD_MZML",
      state: "CREATED",
      created_at: NOW,
    }, 201);
  });
  await page.route("**/api/v1/import-uploads/upload-one/files?*", async (route) => {
    activeUploads += 1;
    maxActiveUploads = Math.max(maxActiveUploads, activeUploads);
    const relativePath = new URL(route.request().url()).searchParams.get("relative_path");
    uploadOrder.push(relativePath ?? "");
    expect(route.request().headers()["content-type"]).toContain("application/octet-stream");
    await delay(220);
    activeUploads -= 1;
    await json(route, {
      upload_id: "upload-one",
      relative_path: relativePath,
      size_bytes: route.request().postDataBuffer()?.byteLength ?? 0,
      state: "UPLOADING",
      total_size_bytes: 20,
      file_count: uploadOrder.length,
    });
  });
  await page.route("**/api/v1/import-uploads/upload-one/start", async (route) => {
    startBody = route.request().postDataJSON();
    await json(route, { job_id: "job-one", status: "queued" });
  });
  await page.route("**/api/v1/imports/job-one", async (route) => {
    jobPolls += 1;
    await json(route, importJob(jobPolls === 1 ? "running" : "success"));
  });

  await page.goto("/datasets");
  await page.getByRole("button", { name: "Upload local dataset" }).click();
  const dialog = page.getByRole("dialog", { name: "Upload local dataset" });
  await chooseTopDownMzml(dialog);
  await dialog.locator("#import-files").setInputFiles([
    { name: "first.mzML", mimeType: "application/octet-stream", buffer: Buffer.from("12345678") },
    { name: "second.mzML", mimeType: "application/octet-stream", buffer: Buffer.from("abcdefghijkl") },
  ]);
  await expect(dialog.getByText("2 files", { exact: true })).toBeVisible();
  await expect(dialog.getByText("20 B", { exact: true })).toBeVisible();
  await dialog.locator("#import-slug").fill("local-data");
  await dialog.locator("#import-name").fill("Local data");
  await dialog.locator("#import-description").fill("Browser upload");
  await dialog.getByRole("button", { name: "Start upload and import" }).click();

  await expect.poll(() => uploadOrder.length).toBe(1);
  await expect(dialog.getByRole("radio", { name: "mzML", exact: true })).toBeDisabled();
  await expect(dialog.getByRole("progressbar", { name: "Current file upload" })).toBeVisible();
  await expect(dialog.getByRole("progressbar", { name: "Overall upload" })).toBeVisible();
  await expect.poll(() => beforeUnloadCount(page, "adds")).toBeGreaterThan(0);

  await expect(dialog.getByText("Importing", { exact: true }).first()).toBeVisible();
  await expect.poll(() => page.evaluate((key) => window.localStorage.getItem(key), ACTIVE_JOB_KEY))
    .not.toBeNull();
  await expect.poll(() => beforeUnloadCount(page, "removes")).toBeGreaterThan(0);

  await expect(dialog.getByText("Import complete", { exact: true }).first()).toBeVisible();
  await expect(dialog.getByRole("link", { name: "Open dataset" })).toHaveAttribute("href", "/datasets/local-data");
  await expect.poll(() => page.evaluate((key) => window.localStorage.getItem(key), ACTIVE_JOB_KEY))
    .toBeNull();

  expect(uploadOrder).toEqual(["first.mzML", "second.mzML"]);
  expect(maxActiveUploads).toBe(1);
  expect(startBody).toEqual({
    parameters: { slug: "local-data", name: "Local data", description: "Browser upload" },
  });
  expect(JSON.stringify(startBody)).not.toContain("source_path");
  expect(oldPathRequests).toEqual([]);
});

test("a structured upload error stops later files and exposes the managed-session cancel action", async ({ page }) => {
  let uploadAttempts = 0;
  let startAttempts = 0;
  await page.route("**/api/v1/import-uploads", async (route) => {
    await json(route, {
      upload_id: "upload-failed",
      import_type: "TD_MZML",
      state: "CREATED",
      created_at: NOW,
    }, 201);
  });
  await page.route("**/api/v1/import-uploads/upload-failed/files?*", async (route) => {
    uploadAttempts += 1;
    await json(route, {
      detail: { code: "UPLOAD_DISK_SPACE_LOW", message: "磁盘剩余空间不足。" },
    }, 507);
  });
  await page.route("**/api/v1/import-uploads/upload-failed/start", async (route) => {
    startAttempts += 1;
    await json(route, { job_id: "unexpected", status: "queued" });
  });

  await page.goto("/datasets");
  await page.getByRole("button", { name: "Upload local dataset" }).click();
  const dialog = page.getByRole("dialog", { name: "Upload local dataset" });
  await chooseTopDownMzml(dialog);
  await dialog.locator("#import-files").setInputFiles([
    { name: "first.mzML", mimeType: "application/octet-stream", buffer: Buffer.from("first") },
    { name: "second.mzML", mimeType: "application/octet-stream", buffer: Buffer.from("second") },
  ]);
  await dialog.locator("#import-slug").fill("disk-low");
  await dialog.locator("#import-name").fill("Disk low");
  await dialog.getByRole("button", { name: "Start upload and import" }).click();

  const alert = dialog.getByRole("alert");
  await expect(alert).toContainText("File upload failed");
  await expect(alert).toContainText("first.mzML");
  await expect(alert).toContainText("磁盘剩余空间不足。");
  await expect(alert).toContainText("UPLOAD_DISK_SPACE_LOW");
  await expect(dialog.getByRole("button", { name: "Cancel upload" })).toBeVisible();
  expect(uploadAttempts).toBe(1);
  expect(startAttempts).toBe(0);
});

test("cancel aborts the active upload, deletes the unstarted session, and hides cancellation after job creation", async ({ page }) => {
  let deleteAttempts = 0;
  let uploadStarted = false;
  await page.route("**/api/v1/import-uploads", async (route) => {
    await json(route, {
      upload_id: "upload-cancel",
      import_type: "TD_MZML",
      state: "CREATED",
      created_at: NOW,
    }, 201);
  });
  await page.route("**/api/v1/import-uploads/upload-cancel/files?*", async (route) => {
    uploadStarted = true;
    await delay(500);
    try {
      await json(route, {
        upload_id: "upload-cancel",
        relative_path: "cancel.mzML",
        size_bytes: 6,
        state: "UPLOADING",
        total_size_bytes: 6,
        file_count: 1,
      });
    } catch {
      // The expected XHR abort may close the routed request before it is fulfilled.
    }
  });
  await page.route("**/api/v1/import-uploads/upload-cancel", async (route) => {
    if (route.request().method() === "DELETE") {
      deleteAttempts += 1;
      await route.fulfill({ status: 204, body: "" });
      return;
    }
    await json(route, {
      upload_id: "upload-cancel",
      import_type: "TD_MZML",
      state: "UPLOADING",
      file_count: 0,
      total_size_bytes: 0,
      job_id: null,
      created_at: NOW,
      started_at: null,
    });
  });

  await page.goto("/datasets");
  await page.getByRole("button", { name: "Upload local dataset" }).click();
  const dialog = page.getByRole("dialog", { name: "Upload local dataset" });
  await chooseTopDownMzml(dialog);
  await dialog.locator("#import-files").setInputFiles({
    name: "cancel.mzML",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("cancel"),
  });
  await dialog.locator("#import-slug").fill("cancelled");
  await dialog.locator("#import-name").fill("Cancelled");
  await dialog.getByRole("button", { name: "Start upload and import" }).click();
  await expect.poll(() => uploadStarted).toBe(true);
  await dialog.getByRole("button", { name: "Cancel upload" }).click();
  await expect(dialog.getByText("Upload cancelled", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Cancel upload" })).toHaveCount(0);
  expect(deleteAttempts).toBe(1);
});

test("refresh after an unfinished browser upload asks the user to select local files again", async ({ page }) => {
  await page.addInitScript(() => {
    window.sessionStorage.setItem("viewer.interruptedImportUpload", "true");
  });
  await page.goto("/datasets");

  const dialog = page.getByRole("dialog", { name: "Upload local dataset" });
  await expect(dialog.getByRole("alert")).toContainText("Previous local upload was interrupted");
  await expect(dialog.getByRole("alert")).toContainText("Select the local files again to restart");
  await expect.poll(() => page.evaluate(() => (
    window.sessionStorage.getItem("viewer.interruptedImportUpload")
  ))).toBeNull();
  await expect(dialog.getByRole("button", { name: "Start another upload" })).toBeVisible();
});

for (const initialStatus of ["queued", "running"] as const) {
  test(`refresh restores a ${initialStatus} ImportJob and clears storage after success`, async ({ page }) => {
    await seedActiveJob(page, "job-restored");
    let finishJob = false;
    await page.route("**/api/v1/imports/job-restored", async (route) => {
      await json(route, importJob(finishJob ? "success" : initialStatus, "restored-data"));
    });

    await page.goto("/datasets");
    const dialog = page.getByRole("dialog", { name: "Upload local dataset" });
    await expect(dialog.getByText("Restored after refresh", { exact: true })).toBeVisible();
    await expect(dialog.getByText(
      initialStatus === "running" ? "Importing" : "Waiting for processing",
      { exact: true },
    ).first()).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Cancel upload" })).toHaveCount(0);
    finishJob = true;
    await expect(dialog.getByText("Import complete", { exact: true }).first()).toBeVisible();
    await expect.poll(() => page.evaluate((key) => window.localStorage.getItem(key), ACTIVE_JOB_KEY))
      .toBeNull();
  });
}

test("restored failed or missing ImportJobs show stable errors and clear invalid activity", async ({ page }) => {
  await seedActiveJob(page, "job-failed");
  await page.route("**/api/v1/imports/job-failed", async (route) => {
    await json(route, { ...importJob("failed"), error: "Importer rejected the result bundle." });
  });
  await page.goto("/datasets");
  let dialog = page.getByRole("dialog", { name: "Upload local dataset" });
  await expect(dialog.getByRole("alert")).toContainText("Importer rejected the result bundle.");
  await expect.poll(() => page.evaluate((key) => window.localStorage.getItem(key), ACTIVE_JOB_KEY))
    .toBeNull();

  await page.evaluate(({ key, value }) => window.localStorage.setItem(key, value), {
    key: ACTIVE_JOB_KEY,
    value: activeJobJson("job-missing"),
  });
  await page.route("**/api/v1/imports/job-missing", async (route) => {
    await json(route, { detail: "Import job not found" }, 404);
  });
  await page.reload();
  dialog = page.getByRole("dialog", { name: "Upload local dataset" });
  await expect(dialog.getByRole("alert")).toContainText("Import task no longer exists");
  await expect.poll(() => page.evaluate((key) => window.localStorage.getItem(key), ACTIVE_JOB_KEY))
    .toBeNull();
});

async function seedActiveJob(page: Page, jobId: string): Promise<void> {
  await page.addInitScript(({ key, value }) => {
    const seedKey = `__viewer_test_seeded_${key}`;
    if (window.sessionStorage.getItem(seedKey) !== "true") {
      window.localStorage.setItem(key, value);
      window.sessionStorage.setItem(seedKey, "true");
    }
  }, { key: ACTIVE_JOB_KEY, value: activeJobJson(jobId) });
}

function activeJobJson(jobId: string): string {
  return JSON.stringify({
    job_id: jobId,
    import_type: "TD_MZML",
    upload_id: "upload-restored",
    created_at: NOW,
  });
}

async function chooseTopDownMzml(dialog: Locator): Promise<void> {
  await dialog.getByRole("radio", { name: "Top-Down", exact: true }).click();
  await dialog.getByRole("radio", { name: "mzML", exact: true }).click();
}

function importJob(status: "queued" | "running" | "success" | "failed", datasetSlug = "local-data") {
  return {
    job_id: status === "failed" ? "job-failed" : "job-one",
    status,
    message: null,
    error: null,
    dataset_slug: status === "success" ? datasetSlug : null,
    progress: status === "success" ? 100 : status === "running" ? 55 : 0,
    stage: status,
    stage_label: status === "running" ? "Importing" : status,
    stage_detail: status === "running" ? "Reading local upload" : null,
    created_at: NOW,
    updated_at: NOW,
  };
}

function agentCase(status: string) {
  return {
    case_id: "case-review",
    workspace_id: "default",
    status,
    source_mode: "server_path",
    source_ref: "agent-case:case-review",
    dataset_fingerprint: "a".repeat(32),
    analysis_category: "BOTTOM_UP",
    source_profile: "New binary format",
    format_details: null,
    interaction_mode: "autonomous",
    autonomous_attempt_used: 1,
    guided_attempt_no: 0,
    context_revision: 0,
    version: status === "SUCCESS" ? 5 : 4,
    stop_requested_at: null,
    candidate_zp_sha256: "b".repeat(64),
    verification: { validation_mode: "deep", readable_run_count: 1 },
    dataset_id: status === "SUCCESS" ? 12 : null,
    dataset_slug: status === "SUCCESS" ? "agent-output" : null,
    created_at: NOW,
    updated_at: NOW,
  };
}

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function installBeforeUnloadAudit(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const audit = { adds: 0, removes: 0 };
    Object.defineProperty(window, "__viewerBeforeUnloadAudit", { value: audit });
    const add = window.addEventListener.bind(window);
    const remove = window.removeEventListener.bind(window);
    window.addEventListener = ((type: string, listener: EventListenerOrEventListenerObject, options?: boolean | AddEventListenerOptions) => {
      if (type === "beforeunload") audit.adds += 1;
      add(type, listener, options);
    }) as typeof window.addEventListener;
    window.removeEventListener = ((type: string, listener: EventListenerOrEventListenerObject, options?: boolean | EventListenerOptions) => {
      if (type === "beforeunload") audit.removes += 1;
      remove(type, listener, options);
    }) as typeof window.removeEventListener;
  });
}

async function beforeUnloadCount(page: Page, key: "adds" | "removes"): Promise<number> {
  return page.evaluate((counter) => {
    const audit = (window as unknown as { __viewerBeforeUnloadAudit: { adds: number; removes: number } })
      .__viewerBeforeUnloadAudit;
    return audit[counter];
  }, key);
}
