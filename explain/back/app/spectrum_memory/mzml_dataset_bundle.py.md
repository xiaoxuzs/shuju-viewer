# `back/app/spectrum_memory/mzml_dataset_bundle.py` 逐行解释

> 来源文件：`back/app/spectrum_memory/mzml_dataset_bundle.py`
> 模块职责：单个 dataset 的内存 mzML bundle：路径 dedupe、run_id → scan map、字节 accounting。

## L12-L17（`DatasetMzmlBundle` 字段）

- `run_to_spectra`：run_id → {scan → spectrum dict}。
- `_path_to_spectra`：mzML 绝对路径 → scan map（多 run 共享同一文件时只读一次）。
- `accounted_bytes`：加载后估算的内存占用。

## L19-L38（`load`）

- 遍历 spec.runs：按 resolve 后的 path key 缓存 scan map；每个 run_id 指向对应 map。
- 加载完成后 `_approximate_bytes_internal()` 写入 `accounted_bytes`（下限 4096）。

## L40-L45（`_approximate_bytes_internal`）

- 对所有唯一 path 的 scan map 调用 `approximate_scan_map_bytes` 求和 + 64 KiB 固定开销。

## 与相邻模块的耦合

- **eviction_coordinator**：加载成功后存入 `_bundles[dataset_id]`，`_current_total += accounted_bytes`。
- **get_mzml_run_spectra**：直接返回 `run_to_spectra[run_id]`（只读引用）。
