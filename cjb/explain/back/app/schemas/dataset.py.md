# `back/app/schemas/dataset.py` 逐行解释

> 来源文件：`back/app/schemas/dataset.py`
> 模块职责：数据集列表/详情与删除响应的 Pydantic 模型。

## L10-L20（`CutoffOut`）

- 虚拟 cutoff 卡片：`kind`（prsm/proteoform）、`label`、三种实体计数。
- `id` 为合成整数（见 `universal_compat.cutoff_id`），非 DB 表主键。

## L23-L40（`DatasetOut`）

- `source_path`：对应 `datasets.source_root`（ingest 根在磁盘上的路径）。
- `capabilities`：JSON 能力集，含 `spectra_source`（`topfd_js` | `mzml_memory`）。
- `updated_at` 可选：universal schema 无此列，读路径通常返回 null。
- `cutoffs`：嵌套 cutoff 统计列表。

## L43-L51（`DatasetDeletedOut`）

- DELETE 应答：`deleted_db` 是否删库行；`deleted_disk` 恒 False（当前删除 API 不删磁盘树，见 `import_jobs.delete_dataset` docstring）。

## 与相邻模块的耦合

- **datasets.py** 组装 `DatasetOut`；指纹列 `source_dataset_fingerprint` 不在 API 输出中暴露。
- **front DatasetsPage** 展示 slug/name/cutoffs；详情页读 `capabilities`。
