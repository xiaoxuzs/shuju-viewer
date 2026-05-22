# `back/app/spectrum_memory/config.py` 逐行解释

> 来源文件：`back/app/spectrum_memory/config.py`
> 模块职责：进程级 spectrum memory 池容量配置（单一真值）。

## L7-L15

- 默认 `_DEFAULT_MAX_BYTES = 6 GiB`（本地单进程部署）。
- `max_capacity_bytes()`：读环境变量 `VIEWER_SPECTRUM_MEMORY_MAX_BYTES`；未设置用默认；下限 64 MiB 防误配。

## 与相邻模块的耦合

- **eviction_coordinator.py**：`EvictionCoordinator.__init__` 调用 `max_capacity_bytes()` 设 `_max`。
