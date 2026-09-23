import { test, expect } from "@playwright/test";
import { advisoryCapabilityReport } from "./capability-fixtures";

for (const kind of ["matches", "peptides"]) {
  for (const cutoff of [null, 0.01, 0]) {
    test(`${kind}: default ${cutoff} and clearing preserve unknown q-values`, async ({ page }) => {
      const requests: URLSearchParams[] = [];
      const dataset = { id: 81, slug: "q-filter", name: "Q filter sample", analysis_mode: "BOTTOM_UP",
        dataset_mode: "bottom_up", status: "READY", source_software: "Agent-ZP", description: "Test",
        extra_metadata: cutoff === null ? {} : { q_value_cutoff: cutoff }, capabilities: {}, bu_runs: [], runs: [], cutoffs: [] };
      await page.route("**/api/v1/**", async route => {
        const url = new URL(route.request().url());
        let body: unknown = [];
        if (url.pathname.endsWith("/datasets/q-filter")) body = dataset;
        else if (url.pathname.endsWith("/capability-report")) body = advisoryCapabilityReport(81);
        else if (url.pathname.endsWith("/overview")) body = { runs: [] };
        else if (url.pathname.endsWith(`/${kind}`)) {
          requests.push(url.searchParams);
          const filtered = url.searchParams.get("q_filter") !== "false" && (url.searchParams.has("q_max") || cutoff !== null);
          const row = { id: 1, run_id: 1, run_name: "sample", peptide_id: 1, sequence: "PEPTIDE",
            modified_sequence: "PEPTIDE", scan_number: 100, q_value: null, best_q_value: null,
            match_count: 1, protein_count: 1, best_match_id: 1, length: 7, is_decoy_match: null, is_decoy_state: "MISSING" };
          body = { items: filtered ? [] : [row], total: filtered ? 0 : 1, page: 1, page_size: 50 };
        }
        await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
      });
      await page.goto(`/datasets/q-filter/${kind}`);
      const input = page.getByRole("spinbutton", { name: "Q max" });
      await expect(input).toHaveValue(cutoff === null ? "" : String(cutoff));
      await expect.poll(() => requests.length).toBeGreaterThan(0);
      expect(requests.at(-1)?.get("q_filter")).toBe(cutoff === null ? "false" : "true");
      if (cutoff === null) expect(requests.at(-1)?.has("q_max")).toBe(false);
      else expect(requests.at(-1)?.get("q_max")).toBe(String(cutoff));
      await input.fill("0.05");
      await expect.poll(() => requests.at(-1)?.get("q_max")).toBe("0.05");
      await input.fill("");
      await expect(input).toHaveValue("");
      await expect(page.getByRole("cell", { name: "PEPTIDE", exact: true }).first()).toBeVisible();
      // Clearing can reuse the still-fresh unfiltered cache from the first render.
      expect(requests.some(params => params.get("q_filter") === "false" && !params.has("q_max"))).toBe(true);
      expect(new URL(page.url()).searchParams.get("q_max")).toBe("");
      await page.reload();
      await expect(input).toHaveValue("");
      await expect(page.getByRole("cell", { name: "PEPTIDE", exact: true }).first()).toBeVisible();
      expect(requests.at(-1)?.get("q_filter")).toBe("false");
      expect(requests.at(-1)?.has("q_max")).toBe(false);
      await input.fill("0.05");
      await page.getByRole("button", { name: "Reset", exact: true }).click();
      await expect(input).toHaveValue("");
      await expect(page.getByRole("cell", { name: "PEPTIDE", exact: true }).first()).toBeVisible();
    });
  }
}
