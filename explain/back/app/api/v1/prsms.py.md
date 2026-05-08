## `back/app/api/v1/prsms.py` 逐行解释

> 目标：提供“某 dataset + 某 cutoff 下的 PrSM 列表与详情”API。注意 universal schema 没有 `prsms` 表：PrSM 存在 `identification_matches` 中，TopPIC 的业务 PrSM id 存在 `extra_metadata.source_prsm_id`。因此：
> - 列表：主要就是对 `identification_matches` 做过滤、排序、分页；
> - 详情：用 (dataset_id, cutoff, source_prsm_id) 唯一定位，并可从 `detail_path` 读取原始 `prsm*.js` 细节（annotated_protein / ms_header / peaks）。

---

### L1：模块 docstring

- **L1**：声明这是某 cutoff 下 PrSM 的列表与详情 API。

---

### L3-L12：依赖

- **L3**：future annotations。
- **L5**：FastAPI 基本组件。
- **L6-L7**：SQLAlchemy `text` 与 `Session`。
- **L9**：`get_db` 注入 session。
- **L10**：从 `universal_compat` 导入：
  - `require_dataset`/`require_cutoff`：校验 slug/cutoff
  - `prsm_list_select_sql`：统一的 PrSM list SELECT 模板
  - `prsm_list_item`：把行 dict 映射成前端期望字段
  - `load_prsm_detail`：从 `detail_path` 读取 prsm js（解析见 `app.services.js_parser`）
- **L11**：`to_int/to_float`：容错转换，用于把 `ms_header` 的字符串值补到输出字段。
- **L12**：响应模型：分页 Page、PrSM list/detail。

---

### L14：Router

- **L14**：router tag 为 `"prsms"`。

---

### L16-L24：`SORT_MAP`

- sort 白名单：prsm_id/e_value/p_value/precursor/.../matched counts。
- 与其它列表 API 一样用于防注入与稳定排序字段名。

---

## 列表：`GET /datasets/{slug}/cutoffs/{cutoff}/prsms`

### L27-L41：路由与签名

- response_model=Page[PrsmListItemOut]
- query 参数：
  - page/page_size
  - `proteoform_id`：过滤某个 proteoform（**DB 主键**，描述写明 “Filter by proteoform.id”）
  - `protein_id`：过滤某个 protein（DB 主键）
  - sort/order

### L42-L66：校验 + 动态 WHERE 拼装

- require_dataset + require_cutoff。
- params 初始包含 dataset_id 与 cutoff。
- where_parts 起始包含：
  - `im.dataset_id = :dataset_id`
  - `im.extra_metadata.source_cutoff = :cutoff`
- 如果传 proteoform_id：
  - 加 `im.entity_id = :proteoform_id`（identification_matches.entity_id 存的是 proteoform DB id）
- 如果传 protein_id：
  - 加一个 EXISTS 子查询到 `protein_relation_mapping`：
    - 关系表里 `entity_type='PROTEOFORM'`、`entity_id=im.entity_id`（proteoform）
    - `protein_id=:protein_id`
  - 这样即便 PrSM 记录只直接指向 proteoform，也能通过 mapping 过滤 protein。

### L67-L82：SQL 生成、分页、执行与返回

- **L67**：`base_sql = prsm_list_select_sql(" AND ".join(where_parts))`：
  - 这会生成一个以 `identification_matches im` 为主表的 SELECT（见 universal_compat.py）。
- **L68**：count_sql 包裹 base_sql。
- **L69-L73**：排序与分页拼接。
- **L75-L82**：执行 count 与 rows：
  - rows 先转 dict，再过 `prsm_list_item` 规整字段
  - 构造 `PrsmListItemOut`
  - 返回 Page。

---

## 详情：`GET /datasets/{slug}/cutoffs/{cutoff}/prsms/{prsm_id}`

### L95-L108：docstring（为什么用业务 prsm_id）

这一段解释了“URL 用业务 id”的设计动机：

- universal 没有 prsms 表，PrSM 存在 identification_matches；
- TopPIC 数字 id 存在 `extra_metadata.source_prsm_id`；
- adapter 将 `(dataset_id, source_cutoff, source_prsm_id)` 当作唯一键；
- UI 展示的是 `PrSM #4534`，URL 也应是 `/prsms/4534`；
- `best_prsm_id` 存的也是业务 id，因此链接才能正确解析。

### L109-L147：查找 detail 主行

- require_dataset + require_cutoff。
- SELECT 从 `identification_matches im` 取出：
  - id：`im.match_id`（DB 行主键）
  - dataset_id/run_id
  - prsm_id：CAST(extra_metadata.source_prsm_id AS int)
  - sequence_id/p_value/matched counts 等来自 extra_metadata
  - e_value/q_value(fdr) 等来自列本身
  - precursor 信息、intensity、detail_path
  - `db_proteoform_id = im.entity_id`（proteoform DB 主键）
  - `ms1_ids`/`ms2_ids` 也尝试从 extra_metadata 读取（有的导入模式在这里填）
- WHERE：
  - dataset_id
  - source_cutoff=:cutoff
  - source_prsm_id=:prsm_id（业务 id）
  - LIMIT 1
- 查不到则 404。

### L148-L158：把主行映射为 list item，并加载 detail_path

- **L148**：`item = prsm_list_item(dict(row))`：统一字段名与 shape。
- **L149**：`load_prsm_detail(detail_path)`：
  - 从磁盘读取 `prsm*.js`（或相容格式）并解析出：
    - annotated_protein
    - ms_header
    - ms_peaks（ms.peaks）
- **L150-L156**：如果有 `ms_header`：
  - 用 ms_header 的字段补全 item 中可能缺失的 precursor/scan 信息（容错）
  - `_as_text` 负责把 list/number 等统一转字符串（ms1_scans/ms2_scans 常为 list 或字符串）
- **L156-L157**：如果有 annotated_protein：
  - 用它补 proteoform_mass（当 DB join pf.theoretical_mass 缺失或为空时）
- **L158**：从 ms_header 里取 `spectrum_file_name`，用于 mzML mapping（前端展示/调试与 dynamic spectra）。

### L159-L171：构造 `PrsmDetailOut`

- 展开 `item`（包含 PrsmListItemOut 的字段）。
- dataset_id/run_id：来自 row。
- proteoform_id：这里传的是 `db_proteoform_id`（DB 主键），与前端 `types.ts` 对齐。
- `ms1_ids`/`ms2_ids`：
  - 优先用 row 的 ms1_ids/ms2_ids（extra_metadata）
  - 否则回退到 ms_header 中的 ms1_ids/ids（字段名差异做兼容）
- `feature_inte`：
  - 优先 row.feature_inte（im.intensity）
  - 否则回退 ms_header.feature_inte
- `ms_header`/`annotated_protein`/`ms_peaks`：原始 JSON 直接回传给前端，交由 `front/src/features/prsm/parse.ts` 解析为强类型结构。

---

### L174-L177：`_as_text`

- 把任何对象转成字符串：
  - None → None
  - 其它 → `str(value)`
- 用于兼容 ms_header 里某些字段是 list/number 的情况（前端 types 里把 scans/ids 作为 string）。

# `back/app/api/v1/prsms.py` 逐行解释

> 来源文件：`back/app/api/v1/prsms.py`

## L1-L13（导入与模块定位）

- 模块 docstring：提供某 cutoff 下的 PrSM 列表与详情，读取 universal schema。
- 依赖：
  - `get_db`：DB session
  - `require_dataset/require_cutoff`：校验资源存在、cutoff 合法
  - `prsm_list_select_sql/prsm_list_item`：统一的列表 SELECT 与字段 mapping
  - `load_prsm_detail`：从磁盘 `detail_path` 读取 `prsm*.js` 的详情 JSON
  - `to_float/to_int`：把 `ms_header` 中字符串数字转换为 number（避免前端拿到 string）
  - `Page/PrsmListItemOut/PrsmDetailOut`：响应模型

## L14

- 创建 `router = APIRouter(tags=["prsms"])`

## L16-L24：`SORT_MAP`

- 前端允许传 `sort` 字段名，这里映射到 SQL 里允许排序的列名：
  - 避免直接把用户输入拼接进 SQL（虽然这里仍是字符串拼接，但只从白名单取值）
  - 默认 fallback 到 `e_value`

## L27-L83：`GET /datasets/{slug}/cutoffs/{cutoff}/prsms`（list_prsms）

### L31-L41（分页与过滤参数）

- `page/page_size`：分页
- `proteoform_id`：按 proteoform 主键过滤（`identification_matches.entity_id`）
- `protein_id`：按 protein 主键过滤（通过 `protein_relation_mapping` 做 EXISTS）
- `sort/order`：排序字段与方向

### L42-L66（构造 where 条件）

- 先 `require_dataset` 获取 `dataset_id`
- `require_cutoff` 校验 cutoff
- 基础过滤条件：
  - `im.dataset_id = :dataset_id`
  - `extra_metadata.source_cutoff = :cutoff`
- proteoform 过滤：
  - 直接 `im.entity_id = :proteoform_id`
- protein 过滤：
  - 通过 `EXISTS protein_relation_mapping` 反查该 match 的 proteoform 是否归属于该 protein

### L67-L74（拼 SQL + 分页）

- `base_sql = prsm_list_select_sql(...)`：统一 SELECT（来自 compat 层）
- `count_sql`：用子查询包一层 count
- 排序：
  - `sort_col = SORT_MAP.get(sort, "e_value")`
  - `ORDER BY ... NULLS LAST`（把 NULL 放到最后，避免影响“最好 e-value 在前”）
- `OFFSET/LIMIT`：分页

### L75-L82（执行与返回）

- `total = session.scalar(count_sql)`
- `rows = session.execute(base_sql)` 获取结果
- 对每行调用 `prsm_list_item` 做字段标准化，然后塞进 `Page[PrsmListItemOut]`

## L85-L171：`GET /datasets/{slug}/cutoffs/{cutoff}/prsms/{prsm_id}`（get_prsm）

### L95-L108（docstring：业务 id 语义）

- 强调：路径里的 `prsm_id` 是 **TopPIC 业务编号**（显示用编号），不是数据库自增主键。
- universal schema 里 PrSM 存在 `identification_matches`，业务 id 存在 `extra_metadata.source_prsm_id`。
- 组合唯一键：`(dataset_id, source_cutoff, source_prsm_id)`

### L109-L147（查询 match 摘要 + detail_path）

- 查询 `identification_matches` 取摘要字段：
  - `match_id` → `id`
  - `run_id/dataset_id`
  - 从 `extra_metadata` 解析 `source_prsm_id/source_sequence_id/p_value/...`
  - `detail_path`：磁盘 prsm 文件路径
  - `ms1_ids/ms2_ids/ms1_scans/ms2_scans`：可能在 fast 导入模式下为空或不完整
- `LEFT JOIN proteoforms` 获取 `proteoform_mass`
- 若查不到：404

### L148-L158（按需补齐字段）

- `item = prsm_list_item(dict(row))`：先按列表形状构造基础字段
- `annotated, ms_header, ms_peaks = load_prsm_detail(detail_path)`：
  - 从磁盘读取三块大 JSON
- 若 `ms_header` 存在：
  - 用 `ms_header` 中的 precursor/ms1/ms2 信息补齐数据库里为空的字段（兼容 fast 导入）
  - `ms2_scans` 的 key 用 `ms_header["scans"]`（TopPIC 原始字段名）
- 若 `annotated` 存在：
  - 用 `annotated["proteoform_mass"]` 补齐 proteoform_mass

### L159-L171（返回详情）

- 返回 `PrsmDetailOut`：
  - 基础字段来自 `item`
  - `dataset_id/run_id/proteoform_id` 来自 row
  - `spectrum_file_name` 从 `ms_header` 提取（用于多 run / mzML mapping）
  - `ms1_ids/ms2_ids/feature_inte`：优先用数据库列，否则 fallback 到 `ms_header`
  - 三大 JSON：`ms_header/annotated_protein/ms_peaks` 原样返回给前端解析层

## L174-L177：`_as_text`

- 小工具：把任意值转成字符串（对 `ms_header` 的字段容错），None 保持 None。

