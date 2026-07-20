import { expect, test, type Page, type Route } from "@playwright/test";

const THEME_STORAGE_KEY = "viewer.theme";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/datasets", async (route) => fulfillJson(route, []));
});

test("switches to dark mode", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/datasets");

  await selectTheme(page, "Dark");

  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("html")).toHaveAttribute("data-resolved-theme", "dark");
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
});

test("keeps the explicit dark selection after refresh and direct navigation", async ({ page }) => {
  await page.goto("/datasets");
  await selectTheme(page, "Dark");
  await expect.poll(() => page.evaluate((key) => window.localStorage.getItem(key), THEME_STORAGE_KEY))
    .toBe("dark");

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-resolved-theme", "dark");
  await expect(page.getByRole("button", { name: "Theme: Dark" })).toBeVisible();

  await page.goto("/datasets?direct=true");
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  await page.goto("/datasets?next=true");
  await page.goBack();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("follows live system color-scheme changes", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/datasets");

  await expect(page.locator("html")).toHaveAttribute("data-theme", "system");
  await expect(page.locator("html")).toHaveAttribute("data-resolved-theme", "light");

  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-resolved-theme", "dark");
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);

  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-resolved-theme", "light");
  await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
});

test("switches back to light mode and persists the override", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/datasets");
  await selectTheme(page, "Dark");
  await selectTheme(page, "Light");

  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.locator("html")).toHaveAttribute("data-resolved-theme", "light");
  await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
  await expect.poll(() => page.evaluate((key) => window.localStorage.getItem(key), THEME_STORAGE_KEY))
    .toBe("light");
});

async function selectTheme(page: Page, label: "Light" | "Dark" | "System") {
  await page.getByRole("button", { name: /^Theme:/ }).click();
  await page.getByRole("menuitemradio", { name: label, exact: true }).click();
}

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}
