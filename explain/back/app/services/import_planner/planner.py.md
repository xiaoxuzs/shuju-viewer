## `back/app/services/import_planner/planner.py` 逐行解释

> 来源文件：`back/app/services/import_planner/planner.py`

> 核心：`plan_zip_ingest(ingest_root)` 在**不写库**的前提下，推断 `DatasetShape`、`spectra_source` 以及 TopPIC 场景是否需要 **multirun 后处理**。

---

## L12-L26：错误文案常量

- `_NO_PRSM_TOPPIC`：HTML 树已识别但磁盘上找不到支持的 PrSM 明细（`data/` 或 `.../prsms/`）。
- `_UNSUPPORTED`：既不是合法 TopPIC HTML（缺 proteins 或规则不满足），也不是 `data/` prsm bundle。
- `_PRSM_BUNDLE_NO_MZML`：仅有 `data/prsm*` 时，若 `detect_spectra_source` 返回 `topfd_js`，与 bundle 要求冲突（bundle 必须走 mzML memory），直接报错。

---

## L29-L61：`plan_zip_ingest`

- **L37**：`root = ingest_root.resolve()`。
- **L38-L39**：
  - `toppic = is_toppic_html_tree(root)`
  - `prsm_bundle = has_prsm_files(root / "data")`（仅看 `data/` 直接子文件）
- **L41-L49**（TopPIC HTML 分支）：
  - 若 `not ingest_root_has_supported_prsm_files(root)` → 抛 `ImportLayoutError(_NO_PRSM_TOPPIC)`（**禁止**只有 summary 没有明细的导入）。
  - `src = detect_spectra_source(root)`
  - 返回 `ImportPlan(TOPPIC_HTML, src, need_toppic_multirun_pass=(src == "mzml_memory"))`  
    含义：`mzml_memory` 时 fast ingest 只建默认 run，必须在后续用 PrSM header 批量 UPDATE 才能对齐多 mzML。
- **L51-L59**（PrSM bundle 分支）：
  - `src = detect_spectra_source(root)`
  - 若 `src != "mzml_memory"` → 抛 `ImportLayoutError(_PRSM_BUNDLE_NO_MZML)`（测试 `test_plan_prsm_bundle_rejects_when_topfd_only` 覆盖）。
  - 否则返回 `ImportPlan(PRSM_BUNDLE, "mzml_memory", need_toppic_multirun_pass=False)`（bundle 仍由 `ingest_universal_prsm_js` 处理，不跑 TopPIC multirun pass）。
- **L61**：其它情况 → `ImportLayoutError(_UNSUPPORTED)`。

与 `import_jobs.run_path_import_job` 的衔接：**先 `plan_zip_ingest`，再按需校验 mzML mapping，再按 `plan.shape` 分支调用 adapter**。
