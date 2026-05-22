## `back/tests/test_import_jobs_layout.py` 逐行解释

> 来源文件：`back/tests/test_import_jobs_layout.py`

> 针对 `prsm_files.ingest_root_has_supported_prsm_files` 与「TopPIC 树判定」的**轻量布局测试**：用 `tmp_path` 造最小目录结构，不跑完整路径导入。

---

## L1-L10：辅助函数

- **L8-L10**：`_is_toppic_tree`：复制 `import_planner.detectors.is_toppic_html_tree` 的判定条件（两个 cutoff 下 `data_js/proteins.js`），用于本文件内独立断言（避免测试依赖 planner 的其它副作用）。

---

## L13-L18：`test_toppic_tree_detection_accepts_prsm_cutoff`

- 在 `toppic_prsm_cutoff/data_js/` 创建占位 `proteins.js`。
- 断言 `_is_toppic_tree(tmp_path)` 为真。

---

## L21-L26：`test_toppic_tree_detection_accepts_proteoform_cutoff`

- 同上，但目录改为 `toppic_proteoform_cutoff`，验证两种 cutoff 名都被接受。

---

## L29-L34：`test_ingest_root_detects_prsm_under_data`

- 在 `data/prsm1.js` 写入最小 `prsm_data = {}`。
- 断言 `ingest_root_has_supported_prsm_files(tmp_path)` 为真。

---

## L37-L42：`test_ingest_root_detects_prsm_under_toppic_prsms`

- PrSM 放在 `toppic_proteoform_cutoff/data_js/prsms/prsm1.js`。
- 断言 `ingest_root_has_supported_prsm_files` 为真（验证 HTML 树常见路径）。

---

## L45-L46：`test_ingest_root_no_prsm_files`

- 空目录：断言为 `False`。
