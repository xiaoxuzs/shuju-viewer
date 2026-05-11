## `back/app/services/import_planner/types.py` 逐行解释

> 定义导入规划用到的枚举、异常与不可变数据类 `ImportPlan`。

---

## L1-L14：`DatasetShape`

- **L9-L14**：`DatasetShape(str, Enum)`：字符串枚举，取值：
  - `TOPPIC_HTML`：存在 TopPIC HTML 输出树（`toppic_*_cutoff/data_js/proteins.js`）
  - `PRSM_BUNDLE`：仅 `data/` 下有支持的 `prsm*` 明细（无 HTML 树）
  - `UNSUPPORTED`：在 `planner` 中若走到未支持分支会抛 `ImportLayoutError` 而非返回该值（枚举保留扩展）

---

## L16-L18：`ImportLayoutError`

- 继承 `ValueError`：布局不满足规则、或 prsm bundle 却检测到 TopFD-only 等场景时抛出；`import_jobs` 捕获后转成 `RuntimeError` 给用户可见的失败信息。

---

## L21-L32：`ImportPlan`（frozen dataclass）

- **L25-L26**：`shape`：上述布局枚举。
- **L28-L29**：`spectra_source`：与 `datasets.capabilities` 一致：`"topfd_js"` 或 `"mzml_memory"`。
- **L31-L32**：`need_toppic_multirun_pass`：当为 `True` 时，表示 TopPIC **fast** 入库后还需调用 `assign_toppic_runs_from_prsm_headers`，按 PrSM 文件头把 `identification_matches` 的 `run_id`、`scan_number` 等从占位状态修正为多 run + 真实 scan。
