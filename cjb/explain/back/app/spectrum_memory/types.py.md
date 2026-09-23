# `back/app/spectrum_memory/types.py` 逐行解释

> 来源文件：`back/app/spectrum_memory/types.py`
> 模块职责：驻留状态枚举与 spectrum_memory 异常层次。

## L8-L11（`Residency`）

- `ABSENT`：未加载；`LOADING`：预留（当前实现未单独暴露 loading 中间态）；`READY`：bundle 在池中。

## L14-L23（异常）

- `SpectrumMemoryError`：基类。
- `NotResidentError`：查询前未 `ensure_dataset_resident`。
- `CapacityError`：全局预算不足，即使 LRU 驱逐后仍放不下。

## 与相邻模块的耦合

- **eviction_coordinator.py**：抛出/返回上述类型。
- **mzml_spectra API**：捕获并转为 HTTP 503/404。
