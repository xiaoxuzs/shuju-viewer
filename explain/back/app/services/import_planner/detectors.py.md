## `back/app/services/import_planner/detectors.py` 逐行解释

> **只读**检测：判断解压根是否为 TopPIC HTML 树，以及谱图来源是 TopFD JS 还是 mzML memory（不读 mzML 内容）。

---

## L8-L13：`is_toppic_html_tree`

- **L8**：`_TOPPIC_CUTOFF_DIRS`：两种 cutoff 目录名（与 `universal_toppic_adapter.CUTOFF_DIRS` 的 value 一致）。
- **L10-L13**：在 `ingest_root` 下任一路径存在 `.../data_js/proteins.js` 即视为 TopPIC HTML 树（prsm 或 proteoform cutoff 均可）。

---

## L15-L25：`detect_spectra_source`

- **L18-L22**：检查 `topfd/ms1_json` 与 `topfd/ms2_json` 下是否存在 `spectrum*.js`（`any(...glob("spectrum*.js"))`）。
- **L23-L25**：**两者都有** → `"topfd_js"`；否则 → `"mzml_memory"`（与旧版 `import_jobs` 内联逻辑一致，现集中到 planner）。
