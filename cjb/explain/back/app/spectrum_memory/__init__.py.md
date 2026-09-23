# `back/app/spectrum_memory/__init__.py` 逐行解释

> 来源文件：`back/app/spectrum_memory/__init__.py`
> 模块职责：mzML 全数据集内存池的公开门面；懒加载 `EvictionCoordinator` 单例。

## L1-L6

- docstring：整数据集 mzML 驻留、MRU/LRU、全局字节预算。

## L16-L19（`_get_coordinator`）

- 延迟 import 避免循环依赖。

## L21-L32（`__all__`）

- 导出 DTO、异常、Residency 枚举与五个操作函数。

## L35-L52（公开 API）

| 函数 | 行为 |
|------|------|
| `ensure_dataset_resident` | 按 spec 加载整包 mzML |
| `get_mzml_spectrum` | 单 scan 查询 |
| `get_mzml_run_spectra` | 整 run scan map（只读） |
| `release_dataset` | 驱逐并释放 accounting |
| `residency_of` | ABSENT / LOADING / READY |

## 与相邻模块的耦合

- **eviction_coordinator.py**：实际实现。
- **spectrum_memory_wiring.py**：从 DB 构建 spec 后调用 `ensure_dataset_resident`。
- **import_jobs.py**：删除数据集时 `release_dataset`。
