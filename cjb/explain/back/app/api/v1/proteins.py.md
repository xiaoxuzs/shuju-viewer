# `back/app/api/v1/proteins.py` 逐行解释

> 来源文件：`back/app/api/v1/proteins.py`  
> 某 dataset + cutoff 下的 **protein 列表与详情**；用 `identification_matches.extra_metadata.source_cutoff` 过滤，经 `protein_relation_mapping` 关联 proteoform / match。

---

### L1：模块 docstring

- **L1**：说明这是“某 cutoff 下的蛋白质列表与详情 API”，数据来源为 universal schema。

---

### L3-L11：依赖

- **L3**：`__future__.annotations`：允许更简洁的类型注解（如 `Page[ProteinListItemOut]`）。
- **L5**：FastAPI：`APIRouter` 定义路由；`Depends` 注入 DB session；`HTTPException` 抛 HTTP 错；`Query` 定义 query 参数；`status` 用状态码常量。
- **L6-L7**：SQLAlchemy：
  - `text`：写原生 SQL
  - `Session`：DB 会话
- **L9**：`get_db`：FastAPI 依赖，提供 session。
- **L10**：`require_dataset` / `require_cutoff`：
  - `require_dataset`：验证 slug 存在并返回 dataset 行（含 dataset_id、source_root 等）。
  - `require_cutoff`：只允许 `"prsm"`/`"proteoform"`（当前 registry）。
- **L11**：响应模型：
  - `Page`：分页容器
  - `ProteinListItemOut` / `ProteinDetailOut`
  - `ProteoformListItemOut`：protein detail 页需要附带 proteoforms 列表。

---

### L13：Router

- **L13**：创建路由器并标记 tag 为 `"proteins"`，用于 OpenAPI 分类。

---

### L15-L21：排序字段映射 `SORT_MAP`

- 将前端 `sort` 参数映射到 SQL 的列名（白名单）。
- 目的：
  - 防 SQL 注入（只允许预定义列）
  - 让前端使用语义字段名（如 `best_prsm_e_value`）

---

## 列表接口：`GET /datasets/{slug}/cutoffs/{cutoff}/proteins`

### L24-L37：路由与函数签名

- **L24-L27**：定义路由与响应模型为 `Page[ProteinListItemOut]`。
- **L29-L33**：分页/筛选/排序 query 参数：
  - page：默认 1，>=1
  - page_size：默认 50，范围 1..500
  - search：可选，模糊搜索 name/description
  - sort：默认 `sequence_id`
  - order：默认 asc，正则限制 asc/desc
- **L34**：注入 DB session。
- **L35-L36**：从 path 参数拿 slug/cutoff（FastAPI 会自动注入，这里把默认值写成空字符串以满足类型）。

### L38-L43：函数 docstring（核心过滤逻辑解释）

- **L40-L42**：cutoff 过滤通过 `EXISTS` 子查询实现：
  - protein → `protein_relation_mapping`（关联到 proteoform）
  - proteoform → `identification_matches`（在某 cutoff 下存在 match）
  - 只有在该 cutoff 下出现过鉴定的 protein 才进入列表。

### L44-L45：dataset/cutoff 校验

- **L44**：`require_dataset`：slug → dataset 行（含 `dataset_id`）。
- **L45**：`require_cutoff`：仅允许注册表中的 cutoff。

### L46-L85：构造 base_sql（含可选 search）、count、排序与分页

#### 1) SELECT 字段（L47-L56）

- `proteins` 表的主键在 universal schema 里是 `protein_id`（这里映射成输出的 `id`）。
- 许多 TopPIC 业务字段（sequence_id、sequence_name、统计值、最佳 PrSM）存放在 `proteins.extra_metadata` 里：
  - 用 `jsonb_extract_path_text(..., 'key')` 取值
  - 再 `CAST(... AS integer/double precision)` 转类型
  - 缺省时用 `COALESCE(...,0)` 等。
- `sequence_name`：优先 extra_metadata 的 `source_sequence_name`，否则回退 `p.accession`（L50）。
- `sequence_description` 直接用 `p.description`。

#### 2) WHERE dataset_id + cutoff EXISTS（L57-L68）

- 限定 dataset：`p.dataset_id = :dataset_id`
- cutoff 过滤：`EXISTS (...)`：
  - `protein_relation_mapping prm` 提供 protein_id → entity（proteoform）映射
  - `identification_matches im` 提供 entity 是否在该 cutoff 下出现
  - cutoff string 来自 `im.extra_metadata.source_cutoff`

#### 3) search 条件（L71-L78）

- 若 `search` 非空：追加 `ILIKE :search`（sequence_name 与 description），参数 `%{search}%`。

#### 4) count、ORDER BY、OFFSET/LIMIT（L80-L85）

- **L80**：`count_sql = SELECT count(1) FROM (base_sql) q`。
- **L81-L83**：`SORT_MAP` 白名单列名 + `ORDER BY ... NULLS LAST`。
- **L83-L85**：`OFFSET :offset LIMIT :limit` 及参数。

### L87-L94：执行并组装 `Page`

- **L87-L88**：`scalar` 得 `total`，`execute` 得行集。
- **L89-L94**：`ProteinListItemOut` + `Page[...]`。

---

## 详情接口：`GET /datasets/{slug}/cutoffs/{cutoff}/proteins/{protein_id}`

### L97-L100：路由与签名

- `response_model=ProteinDetailOut`；路径参数 `protein_id` 为 **`proteins.protein_id`**（DB 主键，非 TopPIC 业务 sequence_id）。

### L101-L111：docstring（cutoff 的作用）

- 要求该 protein 在当前 cutoff 至少有一条 match，否则 404。
- 同时，下属 proteoforms 列表也按同 cutoff 过滤（避免跨 cutoff 混入）。

### L114-L144：查询 protein 主体

- SQL 与列表接口 SELECT 一致；`WHERE dataset_id + protein_id` + 同构 `EXISTS` cutoff 过滤。
- **L143-L144**：无行 → **404**。

### L146-L176：查询下属 proteoforms 列表

- 通过 `protein_relation_mapping prm` 找到该 protein 的 proteoforms（entity_type='PROTEOFORM'）。
- JOIN `proteoforms pf` 取 form 字段：
  - `pf.proteoform_id AS id`：DB 主键
  - `source_proteoform_id`：TopPIC 业务 id
  - `sequence_id`/`sequence_name` 等在 extra_metadata 里
  - mass 取 `pf.theoretical_mass`
  - prsm 统计与 best_prsm 字段同样来自 extra_metadata
  - `n_acetylation`/`unexpected_shift_number` 目前返回 NULL（说明后端暂未填这些统计）
- 再用 `EXISTS` 限定该 proteoform 在当前 cutoff 下确有 match（**L165-L171**）。
- **L172**：`ORDER BY proteoform_id`。

### L177-L180：组装 `ProteinDetailOut`

- 展开 protein 字段，并附带 `proteoforms=[ProteoformListItemOut(...)]`。

---

## 附录：源码顶层符号索引（与 `proteins.py` 全文检索对齐）

- `list_proteins`
- `get_protein`

