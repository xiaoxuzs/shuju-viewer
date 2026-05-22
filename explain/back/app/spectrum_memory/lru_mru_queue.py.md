# `back/app/spectrum_memory/lru_mru_queue.py` 逐行解释

> 来源文件：`back/app/spectrum_memory/lru_mru_queue.py`
> 模块职责：整数据集 bundle 的 MRU/LRU 顺序（OrderedDict：左 LRU，右 MRU）。

## L8-L30（`DatasetMruQueue`）

- `touch(dataset_id)`：存在则 `move_to_end`，否则插入（变为 MRU）。
- `remove(dataset_id)`：从顺序表删除。
- `pop_lru()`：`popitem(last=False)` 弹出最久未 touch 的 dataset_id。
- `__contains__`：是否在队列中。

## 与相邻模块的耦合

- **eviction_coordinator.py**：`_evict_until_fits` 用 `pop_lru` 驱逐；每次 hit 用 `touch` 更新 MRU。
