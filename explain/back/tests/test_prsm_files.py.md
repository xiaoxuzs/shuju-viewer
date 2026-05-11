## `back/tests/test_prsm_files.py` 逐行解释

> 单元测试 `prsm_files`：**多后缀列举与排序**、`prsm_detail_path` 优先级、`load_prsm_document` + `get_prsm_root` + `extract_spectrum_file_name` 的端到端行为。

---

## L1-L12：导入

- 从 `app.services.prsm_files` 导入被测函数。

---

## L15-L24：`_prsm_doc`

- 构造最小合法 PrSM 文档：`prsm.ms.ms_header.spectrum_file_name`（默认 `sample.mzML`），供写入临时文件后解析。

---

## L27-L35：`test_iter_prsm_files_supports_configured_suffixes`

- 在同一目录放 `prsm2.json`、`prsm1.js`、`prsm3.txt` 与无关 `other.js`。
- 断言：`has_prsm_files`；`iter_prsm_files` 按默认 key（文件名）顺序为 `prsm1.js, prsm2.json, prsm3.txt`；`prsm_detail_path(..., 2)` 选中 `.json`（后缀优先级：js 先于 json，但 id=2 时只有 json 命中）。

---

## L38-L45：`test_load_prsm_document_normalizes_wrappers`

- `prsm_data = {...}` 包裹写入 `.js` 文件。
- `load_prsm_document` → `get_prsm_root` 应能取到内层 `prsm`，且 `extract_spectrum_file_name` 返回 header 中的文件名。
