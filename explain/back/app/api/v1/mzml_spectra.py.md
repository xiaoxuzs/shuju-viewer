# `back/app/api/v1/mzml_spectra.py` 逐行解释

> 来源文件：`back/app/api/v1/mzml_spectra.py`  
> 目标：在 **`datasets.capabilities.spectra_source == "mzml_memory"`** 时，按 `(dataset_id, run_id, scan_number)` 返回谱图 JSON。  
> 特点：**首次请求该 run 时**才把对应 mzML 读入进程内存（`MzmlStore`）；路径来自 **`runs.run_metadata.mzml_file_path`**，缺失时可从磁盘 **backfill** 并 **`session.commit()`** 持久化。

---

## L1-L4：模块 docstring

- 说明动态谱图 API、懒加载、与 `spectra_source` 的关系。

## L6-L21：依赖

- **L10**：`json`（backfill 时写 `run_metadata` patch）。
- **L16-L20**：`build_mapping_from_extracted_dataset`、`normalize_spectrum_file_name`：与导入期相同的映射逻辑，用于运行时补全。
- **L21**：`STORE`：进程内 mzML 缓存单例（`mzml_store.py`）。

## L24-L30：路由

- `GET /datasets/{dataset_id}/runs/{run_id}/spectra/{scan_number}`，`response_model=dict[str, Any]`。

## L31-L49：查 `runs` 行

- **L38-L47**：`SELECT ... FROM runs WHERE run_id AND dataset_id`；无行 → **404** `run not found`。

## L51-L93：`mzml_file_path` 与 backfill

- **L51-L52**：`run_metadata` 缺省 `{}`，读 `mzml_file_path`。
- **L53-L93**：若为空：
  - 查 `datasets.source_root`、`capabilities`。
  - `build_mapping_from_extracted_dataset(ingest_root=source_root)` 重算映射；异常 → **409** `cannot derive mzML mapping: ...`。
  - 用 `normalize_spectrum_file_name(run.file_name)` 在 mapping 里取 mzML；无键 → **409** `cannot map run.file_name to mzML`。
  - **L77-L83**：`UPDATE runs SET run_metadata = run_metadata || jsonb patch` 写入 `mzml_file_path`。
  - **L85-L91**：`UPDATE datasets SET capabilities = capabilities || '{"spectra_source": "mzml_memory"}'`，保证前端路由一致。
  - **L92-L93**：**`session.commit()`** — `get_db()` 不自动提交；若不 commit，下次请求仍看不到 backfill。

## L95-L114：读盘、懒加载、取 scan 与响应

- **L95-L97**：`Path(mzml_path)` 不存在 → **404** `mzml not found`。
- **L100-L104**：`STORE.is_loaded(run_id)` 为 false 时 `STORE.load_run`；异常 → **500**。
- **L106-L108**：`STORE.get_spectrum`；无该 scan → **404**。
- **L110-L114**：返回 `{ run_id, dataset_id, **spec }`（`spec` 为 mzML 解析字段，供前端消费）。

---

## 与其它模块的耦合

- **`import_jobs.py` / `mzml_mapping.py`**：正常导入应已写入 `mzml_file_path`；本路由的 backfill 面向旧数据或中断的 finalize。
- **`mzml_store.py`**：LRU、gzip、scan 索引。
- **`client.ts::fetchMzmlSpectrum`**：URL 与参数顺序需一致。

---

## 附录：源码顶层符号索引（与 `mzml_spectra.py` 全文检索对齐）

- `mzml_spectrum`
