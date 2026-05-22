# `back/app/services/spectrum_memory_wiring.py` 逐行解释

> 来源文件：`back/app/services/spectrum_memory_wiring.py`
> 模块职责：从 DB 会话构建 `MzmlBundleSpec` 并触发 spectrum_memory 驻留（保持 ORM/SQL 在本层，不侵入 spectrum_memory 包）。

## L17-L26（capabilities 判定）

- `_capabilities_effective`：PrSM-js bundle 默认补 `spectra_source: mzml_memory`。
- `_is_mzml_memory_dataset`：仅当 capabilities 为 `mzml_memory` 才走内存池。

## L28-L36（路径修正）

- `_resolve_path_on_disk`：先 `try_fix_stale_incoming_absolute_path`，再校验文件存在。

## L39-L142（`build_mzml_bundle_spec`）

- 查 `datasets` 行；非 mzml_memory 返回 None。
- 查有鉴定结果的 `runs` 行（EXISTS identification_matches）。
- 对每个 run：
  - 优先 `run_metadata.mzml_file_path`（经 stale 修正）；
  - 否则 lazy 调用 `build_mapping_from_extracted_dataset` 按 `file_name` 映射 mzML，并 backfill 写回 DB。
- 组装 `MzmlBundleSpec(dataset_id, runs=tuple(...))`。

## L145-L151（`ensure_mzml_dataset_resident`）

- 构建 spec 后调用 `ensure_dataset_resident` 并 `session.commit()`。

## 与相邻模块的耦合

- **spectrum_memory**：`ensure_dataset_resident`、`MzmlBundleSpec`。
- **mzml_mapping**：磁盘 layout → mzML 路径映射。
- **datasets.py / mzml_spectra.py**：打开数据集或请求谱图前触发驻留。
