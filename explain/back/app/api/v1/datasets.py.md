# `back/app/api/v1/datasets.py` 逐行解释

> 来源文件：`back/app/api/v1/datasets.py`

## L1-L3

- 模块 docstring：该 API 读取 universal schema，并以“兼容旧前端”的形状输出 dataset + cutoff 信息。

## L5-L12

- 导入 FastAPI / SQLAlchemy / 依赖注入 / schema：
  - `get_db`：提供 SQLAlchemy Session（读路径都用 raw SQL + `text()`）
  - `cutoff_id/cutoff_label/require_dataset`：universal schema 的兼容层工具（cutoff 合成 id、label，以及按 slug 找 dataset）
  - `CutoffOut/DatasetOut/DatasetDeletedOut`：Pydantic 输出模型
  - `import_jobs`：复用服务层的删除逻辑与导入任务保护逻辑

## L14

- 创建 `router = APIRouter(tags=["datasets"])`：
  - `tags` 会出现在 `/docs` 的分组中，方便浏览。

## L17-L67：`_cutoffs_payload(...)`

- **目的**：universal schema 没有 `cutoffs` 表，但前端仍然需要每个数据集显示两张 cutoff 卡（`prsm` / `proteoform`）以及它们的 protein/proteoform/prsm 计数。
- **核心策略**：
  - cutoff 来自 `identification_matches.extra_metadata->>'source_cutoff'`
  - 计数要按 cutoff 过滤，否则两个 cutoff 的数字会混在一起

### L25-L53（SQL）

- CTE `cutoff_matches`：
  - 取该 dataset 下所有 match
  - 抽取 `source_cutoff` 字符串
  - 保留 `entity_type`/`entity_id`（entity 通常是 PROTEOFORM）
- 主查询：
  - `prsm_count`：直接 `count(*)`（每条 match 代表一条 PrSM）
  - `proteoform_count`：`count(DISTINCT entity_id) FILTER (entity_type='PROTEOFORM')`
  - `protein_count`：通过 `protein_relation_mapping` 把 proteoform 映射回 protein，再做 distinct 计数

### L55-L66（合成输出）

- 把 SQL 结果做成字典 `by_cutoff`
- 然后按固定顺序 `("prsm", "proteoform")` 输出 `CutoffOut[]`：
  - `id`：通过 `cutoff_id(kind)` 合成稳定整数（前端依赖，不要改）
  - `label`：通过 `cutoff_label(kind)` 给展示文案
  - 若某个 cutoff 在数据库里不存在（比如没有该 cutoff 的 match），计数返回 0

## L69-L95：`GET /datasets`

- 查询 `datasets` 表基本字段（含 capabilities）
- 对每条 dataset 调用 `_cutoffs_payload(...)` 填充 cutoff 统计
- 返回 `DatasetOut[]`

## L97-L115：`GET /datasets/{slug}`

- 通过 `require_dataset(session, slug)`：
  - slug 不存在会直接抛 404（在 compat 层里做）
- 返回 `DatasetOut`（同样附带 `_cutoffs_payload`）

## L117-L142：`DELETE /datasets/{slug}`

- 删除数据集（DB + disk），逻辑委托给 `app.services.import_jobs.delete_dataset`：
  - 若 slug 不存在：抛 `LookupError` → 转换为 404
  - 若存在正在运行/排队的导入任务：抛 `RuntimeError` → 转换为 409（防止竞争删除）
  - 若要删除的磁盘路径不在 `DATA_ROOT` 下：抛 `ValueError` → 转换为 400（安全护栏）
- 返回 `DatasetDeletedOut`，告诉前端：
  - 是否删除了数据库行（`deleted_db`）
  - 是否删除了磁盘目录（`deleted_disk`）
  - 删除的目录路径与是否存在

---

## 补充：`_capabilities_out` 与 `spectra_source`（约 L17-L24）

- **目的**：`datasets.capabilities` 为 JSONB，早期 **`data/prsm*.js` 直导** 行可能未写入 `spectra_source`。
- **逻辑**：若 `capabilities` 里 **`spectra_source` 为 null** 且 **`source_software == "TopPIC_prsm_js"`**，则在 API 输出中 **合并** `spectra_source: "mzml_memory"`（不写回 DB，仅响应层推断）。
- **调用点**：列表与单条 `GET /datasets`、`GET /datasets/{slug}` 构造 `DatasetOut` 时传入 `source_software`，统一经 `_capabilities_out` 归一化，供 **`PrsmDetailPage`** 选择 TopFD 静态谱图或 mzML 动态谱图。

