# `back/app/spectrum_memory/contracts.py` 逐行解释

> 来源文件：`back/app/spectrum_memory/contracts.py`
> 模块职责：传入 spectrum_memory 的窄 DTO（无 ORM / FastAPI 类型）。

## L9-L14（`MzmlRunFileSpec`）

- `run_id` + 已 resolve 的 `mzml_path`：一条 run 对应一个 mzML 文件。

## L17-L22（`MzmlBundleSpec`）

- `dataset_id` + `runs` 元组：一个数据集的所有 mzML run 必须作为**整体**加载/驱逐。

## 与相邻模块的耦合

- **spectrum_memory_wiring.py**：从 SQL 查询组装 spec。
- **eviction_coordinator / mzml_dataset_bundle**：消费 spec 加载与索引。
