## `back/tests/test_import_planner.py` 逐行解释

> 覆盖 `plan_zip_ingest` 的规则：**TopPIC HTML 必须有 PrSM 明细**、**bundle 必须 mzml_memory**、**仅有 TopFD spectrum 的 bundle 被拒绝**。

---

## L1-L8：依赖

- `pytest`、`tmp_path`、`plan_zip_ingest`、`ImportLayoutError`、`DatasetShape`。

---

## L11-L17：`test_plan_rejects_toppic_html_without_prsm`

- 只创建 `proteins.js`，不创建任何 `prsm*`。
- 期望 `pytest.raises(ImportLayoutError)` 调用 `plan_zip_ingest`。

---

## L20-L29：`test_plan_accepts_toppic_with_prsm_under_prsms`

- `proteins.js` + `toppic_prsm_cutoff/data_js/prsms/prsm1.js`。
- `plan.shape == TOPPIC_HTML`（通过即表示 planner 接受该布局）。

---

## L32-L40：`test_plan_prsm_bundle_requires_mzml_mode`

- 仅 `data/prsm1.js`（无 TopFD spectrum），`detect_spectra_source` 因而为 `mzml_memory`；本用例期望 **成功** 返回 `ImportPlan`（名称表示 bundle 必须落在 mzML 模式，而非期望抛错）。
- 断言：`PRSM_BUNDLE`、`spectra_source == mzml_memory`、`need_toppic_multirun_pass is False`。

---

## L43-L55：`test_plan_prsm_bundle_rejects_when_topfd_only`

- `data/prsm1.js` + 伪造 `topfd/ms1_json/spectrum1.js` 与 `ms2_json/spectrum1.js`。
- 此时 `detect_spectra_source` 为 `topfd_js`，与 bundle 规则冲突。
- 期望 `ImportLayoutError`。
