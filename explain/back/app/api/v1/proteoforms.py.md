## `back/app/api/v1/proteoforms.py` 逐行解释

> 目标：提供“某 dataset + 某 cutoff 下的 proteoform 列表与详情”API。注意：universal schema 的 `proteoforms` 表是跨 cutoff 共享的，所以必须通过 `identification_matches.extra_metadata.source_cutoff` 判断该 proteoform 是否属于当前 cutoff 的结果集。

---

### L1：模块 docstring

- **L1**：声明该模块负责某 cutoff 下 proteoform 的列表与详情。

---

### L3-L11：依赖

- **L3**：future annotations。
- **L5**：FastAPI 组件。
- **L6-L7**：SQLAlchemy `text` 与 `Session`。
- **L9**：DB session 依赖 `get_db`。
- **L10**：从 `universal_compat` 导入：
  - `require_dataset`/`require_cutoff`：slug/cutoff 校验
  - `prsm_list_select_sql`/`prsm_list_item`：复用 PrSM 列表 SQL 与行映射函数（详情页要带 PrSM 列表）
- **L11**：响应模型：分页 `Page`、PrSM list item、Proteoform list/detail。

---

### L13：Router

- **L13**：router tag 为 `"proteoforms"`。

---

### L15-L20：`SORT_MAP`

- sort 白名单：proteoform_id / prsm_number / best_prsm_e_value / proteoform_mass。
- 与 proteins.py 同样目的：避免注入并稳定 API。

---

## 列表：`GET /datasets/{slug}/cutoffs/{cutoff}/proteoforms`

### L23-L36：路由与签名

- response_model=Page[ProteoformListItemOut]
- query 参数：
  - page/page_size
  - `protein_id` 可选：过滤只看某个 protein 下的 proteoforms（protein_id 指 `proteins.protein_id` DB 主键）
  - sort/order

### L37-L42：docstring（cutoff 过滤的必要性）

- 说明 universal 的 proteoforms 表跨 cutoff 共享，不能仅靠表本身判断归属；
- 因此用 `EXISTS identification_matches` 且 source_cutoff=当前 cutoff 作为唯一可靠判据。

### L43-L66：dataset/cutoff 校验与 where/join 拼装

- **L43-L44**：require_dataset + require_cutoff。
- **L45**：params：dataset_id + cutoff。
- **L46**：join_sql 默认空。
- **L47-L56**：where_sql：
  - `pf.dataset_id = :dataset_id`
  - `EXISTS identification_matches`：
    - entity_type='PROTEOFORM'
    - entity_id = pf.proteoform_id
    - extra_metadata.source_cutoff = :cutoff
- **L57-L65**：如果传了 protein_id：
  - 需要 JOIN `protein_relation_mapping prm` 来限制只看某 protein 下的 proteoforms
  - 条件加 `prm.protein_id = :protein_id`
  - params 加 protein_id

### L67-L82：base_sql（选择字段）

- 输出字段：
  - `pf.proteoform_id AS id`（DB 主键）
  - `source_proteoform_id`（业务 id）
  - `source_sequence_id`、`sequence_name`
  - mass：`pf.theoretical_mass`
  - prsm_number/best_prsm_id/best_prsm_e_value：来自 extra_metadata
  - `n_acetylation`/`unexpected_shift_number` 暂时为 NULL（尚未填充）
- FROM `proteoforms pf` + 可选 join_sql + WHERE where_sql。

### L83-L97：count + 排序 + 分页 + 返回 Page

- count_sql 包住 base_sql。
- sort_col 从 SORT_MAP 取。
- ORDER BY ... NULLS LAST + OFFSET/LIMIT。
- 执行 count 与 rows，映射为 `ProteoformListItemOut` 列表并返回。

---

## 详情：`GET /datasets/{slug}/cutoffs/{cutoff}/proteoforms/{proteoform_id}`

### L100-L115：路由与 docstring（一个常见混淆点）

- path 参数 `proteoform_id` 是 **DB 主键** `proteoforms.proteoform_id`（注释强调“不是 TopPIC 业务号”）。
- cutoff 维度：如果该 proteoform 在该 cutoff 下没有任何 `identification_matches`，则返回 404（避免跨 cutoff 混淆）。

### L116-L153：查询 proteoform 主体

- require_dataset + require_cutoff。
- SELECT：
  - `pf.proteoform_id AS id`：DB 主键
  - `prm.protein_id`：所属 protein（通过 relation mapping 找到；用 LEFT JOIN，意味着可能为 null）
  - `source_proteoform_id`：业务 id（用于 UI 展示）
  - sequence_id/sequence_name/mass/统计字段同列表
- WHERE：
  - dataset_id + proteoform_id 精确匹配
  - EXISTS identification_matches（entity_type='PROTEOFORM', entity_id=pf.proteoform_id, source_cutoff=:cutoff）
- 查不到则 404。

### L154-L170：查询该 proteoform 下的 PrSM 列表

- 使用 `prsm_list_select_sql(...)` 生成标准 PrSM SELECT。
- where 条件：
  - dataset_id
  - entity_id = :proteoform_id（注意：identification_matches.entity_id 指向 proteoform DB 主键）
  - source_cutoff = :cutoff
- ORDER BY `im.e_value ASC`（更好匹配在前）。
- rows 映射：
  - 先 `dict(p)` 再经 `prsm_list_item` 做字段规整（保证输出字段一致）
  - 最后构造 `PrsmListItemOut`。

### L167-L170：组装 `ProteoformDetailOut`

- 展开 pf 字段，并附带 `prsms=[...]`。

