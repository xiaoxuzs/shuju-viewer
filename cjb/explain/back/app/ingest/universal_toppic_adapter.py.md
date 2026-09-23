# `back/app/ingest/universal_toppic_adapter.py` 逐行解释（TopPIC/TopFD → universal schema）

> 来源文件：`back/app/ingest/universal_toppic_adapter.py`
>
> 注意：该文件很长，本文按“功能块 + 行号段”解释。它是 **TopPIC/TopFD HTML 输出树** 导入 universal schema 的主适配器，也是路径导入后台任务（`import_jobs.run_path_import_job`）调用的核心写模型之一。

---

## L1-L15（模块定位：导入目标与刻意不做的事）

- 说明该 adapter 面向 universal 7 表：
  - `datasets/runs/proteins/peptides/proteoforms/identification_matches/protein_relation_mapping`
- 明确 **不导入谱图峰数组**：
  - TopFD 的 `spectrum*.js` 保留在磁盘
  - 后端 `api/v1/spectra.py` + `services/spectrum_cache.py` 按需读取

## L17-L30（导入）

- `json`、`dataclasses`、`Path`、`typing`；**`typer`**、`rich.console.Console`；**`create_engine`/`text`**、`Connection`；`app.ingest.utils`（`best_prsm`、`ensure_list`、`to_float`、`to_int`）；`load_js_object`；`prsm_files` 中 **`get_prsm_root`、`load_prsm_document`、`prsm_detail_path`**（本文件未直接 import `iter_prsm_files`，列举 PrSM 文件在其它辅助逻辑中完成）。
- **L32-L34**：全局 `console`、`typer.Typer` CLI 根。

## L36-L39：`CUTOFF_DIRS`

- cutoff kind → 目录名：`prsm` → `toppic_prsm_cutoff`，`proteoform` → `toppic_proteoform_cutoff`；导入时遍历（缺则跳过），并写入 match 的 `extra_metadata.source_cutoff`。

## L42-L51：`UniversalImportStats`

- `@dataclass`：`dataset_id`、`run_id`、计数器（含 `skipped_matches`）；供 CLI 打印与 `import_jobs` 成功摘要。

## L54-L77：`ProgressEvent` 与 `_emit`

- **L54-L66**：`ProgressEvent`：`phase` / `cutoff` / `current` / `total` / `message`（docstring 标明典型 phase 含 `init`、`proteins`、`matches`、`finalize`）。
- **L69-70**：`ProgressCallback` 类型别名。
- **L72-L77**：`_emit`：回调异常吞掉，避免进度上报打断导入。

## L80-L137：Typer CLI `ingest(...)`

- **L93-L94**：`--mode` 帮助文案：**仅 `fast`**。
- **L97-L105**：若未传 `--database-url` 则懒加载 `settings.database_url`；`mode` 非 `fast` → 红字 + `typer.Exit(2)`。
- **L107-L115**：`_cli_progress`：终端打印 phase/cutoff/current/total/message。
- **L117-L137**：调用 `ingest_universal_toppic(..., mode="fast", progress_callback=_cli_progress)` 并打印统计。

> CLI **不会**自动调用 `assign_toppic_runs_from_prsm_headers`；多 run 对齐请走 `import_jobs` 或自行在 fast ingest 后调用。

## L140-L201：`_RunRegistry`

- **L151-L173**：`get_default` / `get_or_create`：按 `spectrum_file_name` 懒建 `runs` 行并缓存；空名回退默认 run。
- **L175-L196**：`_insert_run`：`INSERT INTO runs ... RETURNING run_id`。
- **L198-L200**：`created_count` 属性。

## L203-L288：`ingest_universal_toppic`（仅 fast）

- **L213-L224**：docstring：fast summaries；多 run 由 **`assign_toppic_runs_from_prsm_headers`** 另行完成。
- **L225-L229**：`root.resolve()`、存在性；`mode != "fast"` → `ValueError`。
- **L231-L244**：`_emit(init)`、`create_engine`、`begin`；可选 `DELETE` 旧 slug；`_create_dataset`、`_RunRegistry`、`stats.run_id = get_default()`。
- **L251-L272**：按 `CUTOFF_DIRS` 找 `proteins.js`，调用 `_import_proteins_and_forms`。
- **L274-L288**：`finalize` 事件 + `UPDATE datasets/runs SET status='READY'`；返回 `stats`。

## L291-L329：`_create_dataset`

- **L292-L329**：`INSERT INTO datasets`（`TOP_DOWN`、`TopPIC_TopFD`、`source_root`、`capabilities` JSON 字符串等）`RETURNING dataset_id`。

## L332-L438：`_import_proteins_and_forms`（读 `proteins.js`）

- `doc = load_js_object(proteins_file)`
- 兼容两种嵌套路径取 `protein_list.proteins.protein`
- `ensure_list`：把被压扁的单元素对象转成 list
- 逐 protein：
  - `source_seq_id` 缺失则跳过
  - 若 protein 未插入过：`_insert_protein(...)`
  - 遍历 `compatible_proteoform`：
    - 若 proteoform 未插入过：`_insert_proteoform(...)`
    - 插入 protein_relation_mapping：`_insert_relation(...)`（去重）
    - fast 模式：调用 `_import_fast_prsm_summaries(...)`
- 同时按 25 个 protein 的粒度 emit progress（proteins phase）

## L440-L605：`_insert_protein` / `_insert_proteoform` / `_insert_relation`

- `_insert_protein`（**L440** 起）：
  - 计算 accession/decoy
  - 汇总 prsm_number 与 best_prsm（最小 e-value）
  - 把 TopPIC 的业务字段塞进 `extra_metadata`
- `_insert_proteoform`：
  - `theoretical_mass` 尝试从 prsm 摘要提取
  - `extra_metadata` 写 source ids、cutoff、prsm_number、best_prsm 等
- `_insert_relation`：
  - protein_relation_mapping 记录 protein → proteoform 的归属关系
  - `extra_metadata` 写 source ids 与 cutoff

## L607-L719：`_import_fast_prsm_summaries`（fast 模式登记 match）

- 仅从 `proteins.js` 摘要写 `identification_matches`：`scan_number=-1` 占位、`detail_path` 经 `prsm_detail_path` 解析（多后缀）；缺文件则 skip；`import_mode="fast"`。
- **full 路径已移除**；明细头字段由 **`assign_toppic_runs_from_prsm_headers`** 批量 `UPDATE`。

## L721-L853：`assign_toppic_runs_from_prsm_headers`

- **调用时机**：`import_jobs` 在 `plan.need_toppic_multirun_pass` 时，于 **`ingest_universal_toppic` 成功之后**调用。
- **L738-L748**：选出 `detail_path IS NOT NULL` 的 matches；`n_total==0` 则返回 0。
- **L753-L847**：新建 `_RunRegistry`，循环每行：读文件、`get_prsm_root`、取 `ms_header.scans` 为 **MS2 scan**（`_first_int`）、`get_or_create(spectrum_file_name)`；合并 `extra_metadata`（`import_mode="fast_multirun"`）；`UPDATE identification_matches` 写 `run_id`、`scan_number`、precursor 相关、`e_value`/`q_value` 等；每 50 条或最后一条 `_emit(matches, …)`。
- **L849-L853**：若 `updated != n_total` 则 `RuntimeError`；否则返回 `updated`。

---

## 附录：源码中其余顶层符号（与 `universal_toppic_adapter.py` 对照）

以下符号在本文主流程小节中**未逐一枚举**，但在源码中仍为顶层定义，可用编辑器全局搜索对齐：`assign_toppic_runs_from_prsm_headers`（已专节）、`_accession_from_sequence_name`、`_annotation_summary`、`_as_text`、`_extract_proteoform_mass`、`_first_int`、`_first_text`、`_json_dumps`、`_looks_decoy` 以及各 `_import_*` / `_insert_*` 辅助函数。

