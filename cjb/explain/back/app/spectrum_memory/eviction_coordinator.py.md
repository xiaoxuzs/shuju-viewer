# `back/app/spectrum_memory/eviction_coordinator.py` 逐行解释

> 来源文件：`back/app/spectrum_memory/eviction_coordinator.py`
> 模块职责：全局可配置字节池；整数据集 mzML bundle 加载、MRU/LRU 驱逐与查询。

## L15-L23（`EvictionCoordinator` 状态）

- `RLock` 保护 `_bundles`、`_queue`、`_current_total`、`_max`。

## L25-L29（`residency_of`）

- 在 `_bundles` 中则为 READY，否则 ABSENT。

## L31-L38（`_evict_until_fits`）

- 当 `_current_total + need_bytes > _max` 时循环 `pop_lru` 并减去 victim 的 `accounted_bytes`。

## L40-L74（`ensure_dataset_resident`）

- 已 resident → 仅 touch MRU。
- 否则：`pre_load_reserve_bytes` → 驱逐 → `DatasetMzmlBundle.load` → 按 actual 再驱逐 → 入账。

## L76-L104（查询 API）

- `get_mzml_spectrum` / `get_mzml_run_spectra`：未 resident 抛 `NotResidentError`；hit 时 touch MRU。
- `get_mzml_run_spectra` docstring 说明返回只读 scan map，供 LC-MS 可视化等构建器使用。

## L106-L111（`release_dataset`）

- 从 `_bundles` 移除并更新 `_current_total`。

## L114-L123（单例）

- `get_coordinator()` 双重检查锁创建进程级单例。

## 与相邻模块的耦合

- **import_jobs.delete_dataset**：`release_dataset` 释放内存。
- **datasets 打开详情**：经 wiring 触发 `ensure_dataset_resident`。
