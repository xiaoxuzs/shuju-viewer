# `back/app/api/v1/prsms.py` 逐行解释

> 来源文件：`back/app/api/v1/prsms.py`  
> 目标：某 dataset + cutoff 下的 PrSM **列表与详情**。universal schema **无** `prsms` 表：行在 `identification_matches`，业务 id 在 `extra_metadata.source_prsm_id`；列表为过滤/排序/分页；详情用 `(dataset_id, cutoff, source_prsm_id)` 定位并可选读 `detail_path` 明细。

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
  - `jsonb_extract_path_text(im.extra_metadata, 'source_cutoff') = :cutoff`
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

### L89-108：路由、签名与 docstring（为什么用业务 `prsm_id`）

这一段解释了“URL 用业务 id”的设计动机：

- universal 没有 prsms 表，PrSM 存在 identification_matches；
- TopPIC 数字 id 存在 `extra_metadata.source_prsm_id`；
- adapter 将 `(dataset_id, source_cutoff, source_prsm_id)` 当作唯一键；
- UI 展示的是 `PrSM #4534`，URL 也应是 `/prsms/4534`；
- `best_prsm_id` 存的也是业务 id，因此链接才能正确解析。

### L109-147：查找 detail 主行

- **L109-L110**：`require_dataset` + `require_cutoff`。
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

### L148-L171：映射、`load_prsm_detail` 与 `PrsmDetailOut`

- **L148**：`item = prsm_list_item(dict(row))`。
- **L149**：`annotated, ms_header, ms_peaks = load_prsm_detail(row["detail_path"])`（磁盘 PrSM 明细；解析见 `universal_compat` / `prsm_files`）。
- **L150-L158**：若有 `ms_header`：用其补 `precursor_*` / scans；`_as_text` 统一 scans 文本；若有 `annotated` 则补 `proteoform_mass`；取 `spectrum_file_name`。
- **L159-L171**：`PrsmDetailOut(**item, dataset_id=..., run_id=..., proteoform_id=..., spectrum_file_name=..., ms1_ids/ms2_ids/feature_inte` 带 row/header 回退，并附上三大 JSON 块供前端 `parse.ts` 消费。

---

### L174-L177：`_as_text`

- 把任何对象转成字符串：
  - None → None
  - 其它 → `str(value)`
- 用于兼容 ms_header 里某些字段是 list/number 的情况（前端 types 里把 scans/ids 作为 string）。

---

## 附录：源码顶层符号索引（与 `prsms.py` 全文检索对齐）

- `list_prsms`
- `get_prsm`
- `_as_text`
