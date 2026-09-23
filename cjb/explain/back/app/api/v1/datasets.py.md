# `back/app/api/v1/datasets.py` 逐行解释

> 来源文件：`back/app/api/v1/datasets.py`

## L1-L3

- 模块 docstring：该 API 读取 universal schema，并以“兼容旧前端”的形状输出 dataset + cutoff 信息。

## L5-L16

- `typing.Any`；FastAPI / SQLAlchemy；`get_db`、`cutoff_id`、`cutoff_label`、`require_dataset`；`CutoffOut`、`DatasetOut`、`DatasetDeletedOut`；`import_jobs`（删除与活动导入护栏）。

## L17

- `router = APIRouter(tags=["datasets"])`：`tags` 出现在 `/docs` 分组中。

## L19-L24：`_capabilities_out`

- **目的**：`datasets.capabilities` 为 JSONB；早期 **`data/prsm*.js` 直导** 行可能未写入 `spectra_source`。
- **逻辑**：若 `capabilities` 里 **`spectra_source` 为 null** 且 **`source_software == "TopPIC_prsm_js"`**，则在 API 响应中合并 `spectra_source: "mzml_memory"`（**不写回 DB**，仅输出层推断）。
- **调用点**：`list_datasets` / `get_dataset_detail` 构造 `DatasetOut` 时传入 `source_software`，供前端路由谱图能力。

## L27-L76：`_cutoffs_payload(...)`

- **目的**：universal schema 没有独立 `cutoffs` 表，但前端需要每个数据集两张 cutoff 卡（`prsm` / `proteoform`）及 protein / proteoform / prsm 计数。
- **策略**：cutoff 来自 `identification_matches.extra_metadata->>'source_cutoff'`；计数按 cutoff 过滤，避免两 cutoff 数字混在一起。

### L35-L60（SQL）

- CTE `cutoff_matches`：该 `dataset_id` 下所有 match，抽出 `source_cutoff`、`entity_type`、`entity_id`。
- 主查询：`prsm_count = count(*)`；`proteoform_count` 为 `entity_type='PROTEOFORM'` 的 distinct `entity_id`；`protein_count` 经 `protein_relation_mapping` 映射到 protein 再 distinct。
- `WHERE cm.cutoff IS NOT NULL` + `GROUP BY cm.cutoff`。

### L65-L76（合成 `CutoffOut[]`）

- `by_cutoff` 字典后，固定顺序 `("prsm", "proteoform")` 输出；`cutoff_id` / `cutoff_label`；缺失 cutoff 时计数为 0。

## L79-L106：`GET /datasets`

- 查询 `datasets` 基本字段（含 `capabilities`）；每条调用 `_cutoffs_payload`；返回 `DatasetOut[]`。

## L109-L129：`GET /datasets/{slug}`

- `require_dataset(session, slug)`：不存在则 compat 层 404。
- **mzML 预载**：`spectrum_memory_wiring.ensure_mzml_dataset_resident`；`CapacityError` → 507；映射失败 → 500。
- 返回 `DatasetOut`（`_capabilities_out` + `_cutoffs_payload`）。

## L132-L157：`DELETE /datasets/{slug}`

- 委托 `import_jobs.delete_dataset(slug)`（**仅删 DB 行** + 清理 import_jobs；磁盘 import 树保留，`deleted_disk` 恒 False）：
  - `LookupError` → **404**
  - `RuntimeError`（活动导入任务等）→ **409**
- 返回 `DatasetDeletedOut`（`deleted_db` / `deleted_disk` / `folder` / `folder_existed`）。

---

## 附录：源码顶层符号索引（与 `datasets.py` 全文检索对齐）

- `_capabilities_out`
- `_cutoffs_payload`
- `list_datasets`
- `get_dataset_detail`
- `delete_dataset`
