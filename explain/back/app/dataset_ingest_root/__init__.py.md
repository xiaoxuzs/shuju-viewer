# `back/app/dataset_ingest_root/__init__.py` 逐行解释

> 来源文件：`back/app/dataset_ingest_root/__init__.py`
> 模块职责：导出 ingest 根路径解析的公开 API。

## L1-L9

- **L1**：docstring：从用户选择的（可能嵌套的）文件夹解析 TopPIC / PrSM bundle ingest 根。
- **L3**：从 `resolver` 导入 `find_ingest_root`、`has_dataset_layout`、`resolve_ingest_root`。
- **L5-L9**：`__all__` 限定导出。

## 与相邻模块的耦合

- **imports.py**：`enqueue_import` 在创建 job 前调用 `resolve_ingest_root`。
- **import_jobs.py**：后台任务再次解析/校验 ingest 根。
- **import_planner**：`plan_zip_ingest(ingest_root)` 接收本模块输出路径。
