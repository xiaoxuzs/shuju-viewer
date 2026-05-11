## `back/app/services/import_planner/__init__.py` 逐行解释

> 包入口：对外导出 ZIP 导入**规划**所需的类型与唯一入口函数 `plan_zip_ingest`。

---

## L1-L13

- **L1-L2**：模块 docstring：说明本包负责「解压后的布局检测」与「入库前的前置条件」，在真正写 DB、读 mzML 之前产出不可变 `ImportPlan`。
- **L3**：`from __future__ import annotations`。
- **L5-L6**：从子模块 re-export：
  - `plan_zip_ingest`（`planner.py`）
  - `DatasetShape`、`ImportLayoutError`、`ImportPlan`（`types.py`）
- **L8-L13**：`__all__`：明确公共 API 面，避免 `from import_planner import *` 时泄漏内部实现。
