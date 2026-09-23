# `back/app/spectrum_memory/size_accounting.py` 逐行解释

> 来源文件：`back/app/spectrum_memory/size_accounting.py`
> 模块职责：加载前预留字节与磁盘大小估算，供 LRU 驱逐决策。

## L10-L17（`disk_bytes_for_paths`）

- 对路径列表 `stat().st_size` 求和；OSError 计 0。

## L20-L33（`pre_load_reserve_bytes`）

- 对 spec 中唯一 mzML 路径去重后算磁盘字节。
- `inflated = disk * 4`：XML 解析后内存膨胀启发式。
- 每 run 加 64 KiB 索引开销；下限 1 MiB。
- **加载前**用 reserve 规划驱逐，**加载后**用 `DatasetMzmlBundle.accounted_bytes` 精确记账。

## 与相邻模块的耦合

- **eviction_coordinator.ensure_dataset_resident**：先 `_evict_until_fits(reserve)`，加载后再按 actual 调整。
