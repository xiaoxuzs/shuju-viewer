// Read-only visible browser checks on the actual imported dataset.
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
const [origin, slug, output] = process.argv.slice(2);
if (!origin || !slug || !output) throw Error("Explicit owned dataset URL and evidence directory are required");
fs.mkdirSync(output, { recursive: true });
const browser = await chromium.launch({ headless: false });
const context = await browser.newContext({ viewport: { width: 1400, height: 740 } });
const page = await context.newPage();
const record = { passed: false, dataset_slug: slug, pages: [] };
async function capture(name) {
  await page.waitForTimeout(600);
  const filename = name + ".png";
  await page.screenshot({ path: path.join(output, filename) });
  record.pages.push({ name, screenshot: filename, url: page.url(), title: await page.title() });
  console.log(JSON.stringify(record.pages.at(-1)));
}
try {
  await page.goto(origin + "/datasets/" + encodeURIComponent(slug));
  await page.getByRole("link", { name: "Matches", exact: true }).waitFor();
  await capture("01-概览");
  for (const [tab, list, detail] of [["Matches", "02-匹配列表", "03-匹配详情"], ["Peptides", "04-肽段列表", "05-肽段详情"], ["Proteins", "06-蛋白列表", "07-蛋白详情"]]) {
    await page.getByRole("link", { name: tab, exact: true }).click();
    const first = page.locator("table tbody tr").first();
    await first.waitFor();
    await capture(list);
    const links = first.getByRole("link");
    if (await links.count()) {
      await links.first().click();
      await capture(detail);
    }
  }
  record.passed = true;
} catch (error) { record.error = String(error); process.exitCode = 1; }
finally {
  fs.writeFileSync(path.join(output, "页面回读.json"), JSON.stringify(record, null, 2));
  await browser.close();
}
