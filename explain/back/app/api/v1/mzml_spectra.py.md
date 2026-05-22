# `back/app/api/v1/mzml_spectra.py` 逐行解释

> 来源文件：`back/app/api/v1/mzml_spectra.py`
> 模块职责：mzML-memory 模式下按 `(dataset_id, run_id, scan_number)` 返回谱图 JSON；从 `spectrum_memory` 池读取（数据集需先驻留）。

## L1-L5（模块 docstring）

- `spectra_source == mzml_memory` 的数据集在 `GET /datasets/{slug}` 时经 wiring 预载整包 mzML 到内存池。
- 本路由只读池内数据，不单独 lazy-load 单 run 到旧 `mzml_store`。

## L17-L24（依赖）

- `spectrum_memory_wiring.ensure_mzml_dataset_resident`：backfill 路径后重新驻留。
- `get_mzml_spectrum` / `release_dataset` / `NotResidentError` / `CapacityError`。
- `try_fix_stale_incoming_absolute_path`：修正 `.incoming` stale 路径。

## L34-L98（查 run + backfill `mzml_file_path`）

- 无 run 行 → 404。
- `run_metadata.mzml_file_path` 缺失时：从 `datasets.source_root` 重算 mapping 并 commit 写回（兼容旧导入）。
- stale 路径修正后若变更，再次 commit 并 `release_dataset` + 重新 `ensure_mzml_dataset_resident`。

## L128-L142（取谱）

- `get_mzml_spectrum(dataset_id, run_id, scan_number)`。
- `NotResidentError` → 409，提示用户先在数据集列表打开该数据集预载。
- 无 scan → 404；成功返回 `{ run_id, dataset_id, **spec }`。

## 与相邻模块的耦合

- **datasets.py**：打开详情时触发 `ensure_mzml_dataset_resident`。
- **spectrum_memory** 替代 **mzml_store** 作为 mzML-memory 主路径。
- **client.ts::fetchMzmlSpectrum**。
