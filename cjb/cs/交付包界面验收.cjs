// Real local UI smoke test. Requires a locally installed Playwright browser.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

(async () => {
  const [rootArg, phase, reportArg] = process.argv.slice(2);
  const root = fs.realpathSync(rootArg);
  const relative = path.relative(os.tmpdir(), root);
  if (relative.startsWith('..') || !path.basename(path.dirname(root)).startsWith('viewer-cjb-check-')) {
    throw new Error('Only a disposable relocation directory is allowed.');
  }
  const { chromium, expect } = require(path.join(root, 'front/node_modules/@playwright/test'));
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto('http://127.0.0.1:15173/datasets');
    await expect(page.getByRole('button', { name: 'Upload local dataset' })).toBeVisible({ timeout: 30000 });
    if (phase === 'empty') {
      const response = await page.request.get('http://127.0.0.1:15173/api/v1/datasets');
      expect(await response.json()).toEqual([]);
      await page.getByRole('button', { name: 'Upload local dataset' }).click();
      const dialog = page.getByRole('dialog', { name: 'Upload local dataset' });
      await expect(dialog).toBeVisible();
      await dialog.getByRole('radio', { name: 'Top-Down', exact: true }).click();
      await dialog.getByRole('radio', { name: 'mzML', exact: true }).click();
      await expect(dialog.locator('#import-files')).toHaveAttribute('accept', '.mzML,.mzml');
      await page.screenshot({ path: path.join(root, '.runtime/empty-upload-ui.png'), fullPage: true });
    } else {
      await page.goto('http://127.0.0.1:15173/datasets/delivery-smoke');
      await expect(page.getByText('Delivery smoke (synthetic)', { exact: true }).first()).toBeVisible({ timeout: 30000 });
      await page.waitForLoadState('networkidle');
    }
    expect(errors).toEqual([]);
    const result = { phase, result: 'passed', pageErrors: errors, finalUrl: page.url() };
    fs.writeFileSync(reportArg, JSON.stringify(result, null, 2), 'utf8');
    console.log(JSON.stringify(result));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
