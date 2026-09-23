import { expect, test } from "@playwright/test";

test("ordinary launch needs no handoff, login or permanent credential", async ({ page }) => {
  await page.route("**/api/v1/**", async route => {
    expect(route.request().url()).not.toContain("/local-session/");
    expect(route.request().headers()["authorization"]).toBeUndefined();
    return route.fulfill({ json: route.request().url().endsWith("/count") ? { count: 0 } : [] });
  });
  await page.goto("/datasets");
  await expect(page.getByRole("button", { name: "Upload local dataset" })).toBeVisible();
  expect(new URL(page.url()).hash).toBe("");
  await expect(page.getByLabel("Viewer operator token", { exact: true })).toHaveCount(0);
});

test("obsolete handoff does not force login or block the ordinary application", async ({ page }) => {
  await page.route("**/api/v1/**", async route => {
    expect(route.request().url()).not.toContain("/local-session/exchange");
    return route.fulfill({ json: route.request().url().endsWith("/count") ? { count: 0 } : [] });
  });
  await page.goto("/datasets#viewer-handoff=expired-synthetic-handoff-not-a-secret-key");
  await expect(page.getByRole("button", { name: "Upload local dataset" })).toBeVisible();
  expect(new URL(page.url()).hash).toBe("");
});
