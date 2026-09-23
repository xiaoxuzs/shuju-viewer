# `back/app/services/import_jobs.py` 逐行解释

> 来源文件：`back/app/services/import_jobs.py`
> 模块职责：路径导入后台任务——指纹去重、ingest 编排、进度持久化、数据集删除（仅 DB）。

## 模块定位（L1-L14）

- 任务状态存 `import_jobs` 表，跨 uvicorn reload 可轮询。
- **路径导入**：客户端提交服务端文件夹路径；worker 解析 ingest 根、计算元数据指纹、调用 universal ingest。
- 进度阶段：`fingerprint` → `init` → `proteins` → `matches` → `finalize`。

## Schema bootstrap（L89-L185）

- `ensure_jobs_table`：建 `import_jobs`；`source_path` 列；DROP  legacy `source_zip_name`。
- `ensure_dataset_fingerprint_schema`：加 `source_dataset_fingerprint` + 唯一索引；DROP `source_zip_sha256`。
- `ensure_runs_metadata_schema`：加 `runs.run_metadata` JSONB（mzML 路径映射）。

## 指纹去重（L188-L218）

- `find_dataset_with_fingerprint`：查 `datasets.source_dataset_fingerprint` 是否已存在。

## 进度映射（L250-L503）

- `_PHASE_RANGES`：fingerprint 1–8%、init 8–12%、proteins 12–20%、matches 20–95%、finalize 95–99.5%。
- `_make_adapter_progress_handler`：ingest adapter 的 `ProgressEvent` → 全局百分比。
- `_fingerprint_progress_handler`：扫描文件数 → fingerprint 子窗口。

## `run_path_import_job`（L506-L843）主流程

1. `resolve_ingest_root(user_root)`；可选校验必须在 `DATA_ROOT` 下。
2. `compute_dataset_metadata_fingerprint(ingest_root)`；空目录拒绝；重复指纹抛错。
3. `plan_zip_ingest(ingest_root)` 判定布局与 `spectra_source`。
4. mzml_memory：`build_mapping_from_extracted_dataset` 严格校验映射。
5. **ingest**：
   - `TOPPIC_HTML` → `ingest_universal_toppic(mode=fast)`；必要时 `assign_toppic_runs_from_prsm_headers`。
   - `PRSM_BUNDLE` → `ingest_universal_prsm_js`。
6. **finalize DB**：
   - `UPDATE datasets SET source_root, source_dataset_fingerprint`。
   - 写 `capabilities.spectra_source`。
   - mzml_memory：为每个 run 写 `run_metadata.mzml_file_path`（经 `relocate_incoming_root`）。
7. `IntegrityError`（并发同指纹）→ `delete_dataset` 回滚并抛用户可读错误。
8. 成功：`progress=100`，`stage=success`。

## `start_path_import_background`（L846-L866）

- daemon 线程调用 `run_path_import_job`。

## `delete_dataset`（L882+）

- 删 DB cascade；**不** rmtree 磁盘；删除前 `release_dataset` 释放 spectrum_memory；活跃 job guard（可 bypass）。

## 与相邻模块的耦合

- **fingerprint** / **dataset_ingest_root** / **import_planner** / **ingest adapters** / **mzml_mapping** / **incoming_path_relocate** / **spectrum_memory.release_dataset**。
