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
  await page.getByRole("button", { name: "Upload local dataset" }).click();
  const dialog = page.getByRole("dialog", { name: "Upload local dataset" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Server folder", { exact: false })).toHaveCount(0);
  await expect(dialog.getByText("source path", { exact: false })).toHaveCount(0);
  await expect(dialog.getByText("import source", { exact: false })).toHaveCount(0);

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
  await dialog.getByRole("radio", { name: "DIA-CLIP", exact: true }).click();
  await expect(dialog.getByRole("radio", { name: "TopPIC Native Output", exact: true })).toHaveCount(0);
  await expect(dialog.getByText("DIA-CLIP v1 is a single-run Bottom-Up import", { exact: false })).toBeVisible();
  await expect(dialog.getByText("required context report", { exact: false })).toBeVisible();
  await expect(dialog.getByText("DIA-NN context", { exact: false })).toHaveCount(0);

  await dialog.getByRole("radio", { name: "DDA", exact: true }).click();
  await expect(dialog.getByRole("radio", { name: "Thermo RAW", exact: true })).toBeVisible();
  await expect(dialog.getByRole("radio", { name: "DIA-NN", exact: true })).toHaveCount(0);
  expect(oldPathRequests).toEqual([]);
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
