## `back/app/api/v1/universal_compat.py` 逐行解释

> 目标：提供“兼容层/工具函数”，让 API 层能以稳定的方式读取 universal schema，并维持前端期望的字段形状。核心内容包括：
> - cutoff registry：universal schema 没有 cutoffs 表，但前端需要 cutoff 的 id/label/排序；
> - `require_dataset`/`require_cutoff`：API 通用校验；
> - PrSM 列表的共享 SQL（`prsm_list_select_sql`）与行映射（`prsm_list_item`）；
> - `load_prsm_detail`：从 `identification_matches.detail_path` 指向的 `prsm*.js` 文件中解析出 annotated_protein/ms_header/peaks。

---

### L1：模块 docstring

- **L1**：说明该模块提供“兼容性 helper”，用于把 universal schema 读成旧 API 形状（主要是前端类型所需形状）。

---

### L3-L13：依赖

- **L3**：future annotations。
- **L5**：`Path`：用于定位 detail_path 并检查文件存在性。
- **L6**：`Any`：表示 JSON-like 字典值类型。
- **L8**：FastAPI HTTPException/status：在 helper 中直接抛 API 层的错误码。
- **L9-L10**：SQLAlchemy text + Session：用原生 SQL 查询 datasets。
- **L12**：`app.services.prsm_files`：
  - `load_prsm_document`：读取 `detail_path` 指向的 PrSM 明细文件（兼容 `.js/.json/.txt`，并处理 JS 赋值包裹）
  - `get_prsm_root`：把 wrapper 形态统一成 PrSM root（避免到处写 `doc["prsm_data"]["prsm"]`）

---

## Cutoff registry（L15-L37）

### L18-L23：为什么需要 registry

- universal schema 没有 cutoffs 表；
- cutoff 只是一个字符串，存放在 `identification_matches.extra_metadata.source_cutoff`（例如 `"prsm"` / `"proteoform"`）；
- 前端仍希望获得：
  - 稳定的 integer id（React key、UI 展示）
  - label（UI 文案）
  - 固定顺序（cutoff 卡片顺序）

### L25-L30：kind 顺序与 label

- **L25**：`_CUTOFF_KIND_ORDER = ("prsm","proteoform")`：顺序重要，决定 UI 展示顺序。
- **L27-L30**：`_CUTOFF_LABELS`：kind → 人类可读 label。

### L32-L37：稳定 synthetic ids 与 VALID_CUTOFFS

- **L32-L35**：`_CUTOFF_IDS`：用 enumerate 生成 `{prsm:1, proteoform:2}`。
  - 注释强调“不要改这些数字”，因为前端把 `cutoff.id` 当作 API 合同的一部分。
- **L37**：`VALID_CUTOFFS`：有效 cutoff 集合。

---

### L40-L42：`cutoff_kinds`

- 返回 ordered tuple（供 datasets API 生成 cutoff 列表时使用）。

---

## dataset/cutoff 校验 helpers（L45-L70）

### L45-L65：`require_dataset`

- 执行 SQL 查询 `datasets` 表，选出：
  - dataset_id, dataset_name, slug, description, source_root, created_at
- WHERE slug=:slug
- 若无行：抛 HTTP 404 “dataset not found: {slug}”
- 否则返回 dict(row)（方便调用方用 `dataset["dataset_id"]` 等）。

### L67-L70：`require_cutoff`

- 如果 cutoff 不在 VALID_CUTOFFS：抛 404 “cutoff not found: {cutoff}”
- 否则返回 cutoff（让调用处可以写 `cutoff = require_cutoff(cutoff)` 的风格）。

---

## cutoff metadata helpers（L73-L85）

- **L73-L75**：`cutoff_id`：返回 synthetic id（1/2）。
- **L78-L80**：`cutoff_label`：返回 label 字符串。
- **L83-L84**：`source_cutoff_filter_sql`：返回一段 SQL 片段，用于重复使用（`jsonb_extract_path_text(extra_metadata,'source_cutoff')=:cutoff`）。

---

## JSON / extra_metadata SQL helpers（L87-L101）

这些函数返回 SQL 表达式字符串，集中管理 extra_metadata 的字段读取方式：

- **L87-L89**：`source_prsm_id_sql(table_alias="im.extra_metadata")`：返回 CAST(jsonb_extract_path_text(...,'source_prsm_id') AS integer)
- **L91-L93**：`source_sequence_id_sql`
- **L95-L97**：`source_proteoform_id_sql`
- **L99-L100**：`json_text(field,key)`：抽象出 `jsonb_extract_path_text(field,'key')`

目的：避免在多个 API 文件里复制粘贴复杂的 jsonb_extract_path_text + CAST 逻辑。

---

## PrSM list SQL（L103-L124）

### L103-L124：`prsm_list_select_sql(where_sql="")`

- 接收一段 where_sql（例如 `"im.dataset_id=:dataset_id AND ..."`），若非空则拼 `WHERE {where_sql}`。
- 返回一个标准 SELECT：
  - id：`im.match_id`
  - prsm_id/sequence_id：从 extra_metadata 的 source_* 字段 CAST 出来
  - p_value/matched counts：从 extra_metadata 读取并 CAST
  - e_value/q_value(fdr)/precursor_*：来自 identification_matches 列
  - proteoform_mass：LEFT JOIN `proteoforms pf` 的 theoretical_mass（允许为空）
  - ms1_scans/ms2_scans：从 extra_metadata 读文本
- 该 SQL 被 `proteoforms.py` 与 `prsms.py` 的列表/详情复用，保证字段一致。

---

## PrSM row mapping（L127-L143）

### `prsm_list_item(row)`

- 把 DB 行 dict 映射成前端类型字段的 dict：
  - 保留 id、prsm_id、sequence_id 等字段
  - 统一键名与 `front/src/api/types.ts::PrsmListItemOut` 一致
- 该映射是“输出合同层”，让 SQL 的列名变化不影响上层调用（只要 row 包含这些 key）。

---

## `load_prsm_detail`（L148-L160）

### 功能

- 从 `identification_matches.detail_path` 指向的文件加载 prsm 详情 JSON。

### 细节（L148-L160）

- **L147-L148**：detail_path 为空 → 返回三段 None（annotated/header/peaks）。
- **L149-L151**：文件不存在 → 返回 None（不抛错，表示“无细节可用”，由上层决定如何处理）。
- **读取与归一化**：
  - 用 `load_prsm_document(path)` 解析文件内容（支持 `.js/.json/.txt`）。
  - 用 `get_prsm_root(doc)` 统一 wrapper，得到 `prsm_root`。
- **L154-L157**：
  - annotated：`prsm_root["annotated_protein"]`
  - ms：`prsm_root["ms"]`
  - header：`ms["ms_header"]`
  - peaks：`ms["peaks"]`
- **L158**：返回三段 dict 或 None。

这种“宽松读取”策略让系统可以同时兼容：
- full TopPIC tree 导入产生的 detail_path
- prsm_js-only 模式下的 prsm 文件形状（只要字段名接近）

# `back/app/api/v1/universal_compat.py` 逐行解释

> 来源文件：`back/app/api/v1/universal_compat.py`

## L1-L1

- 模块 docstring：该文件是 universal schema 的“兼容层”，把数据库里的真实结构转换成前端期望的旧形状（尤其是 cutoff、PrSM 列表 SQL 等）。

## L3-L13（导入）

- `Path`：用于读取 `detail_path` 指向的 `prsm*.js` 文件
- FastAPI 异常：`HTTPException/status`，用于 `require_dataset/require_cutoff` 的 404/错误提示
- SQLAlchemy：`text` + `Session`（统一用 raw SQL 查 universal schema）
- `load_prsm_document/get_prsm_root`：用于读取并归一化 `detail_path` 指向的 PrSM 明细文件（支持 `.js/.json/.txt`）

## L15-L37（cutoff registry）

### L19-L23（为何需要 registry）

- universal schema 没有 `cutoffs` 表，cutoff 只是 `identification_matches.extra_metadata.source_cutoff` 的字符串。
- 但前端需要：
  - 稳定的整数 `cutoff.id`（用于 React key / UI 渲染）
  - 人类可读的 label
  - 固定显示顺序（先 prsm 再 proteoform）

### L25-L37（核心常量）

- `_CUTOFF_KIND_ORDER = ("prsm", "proteoform")`：全局顺序的“唯一来源”
- `_CUTOFF_LABELS`：kind → label
- `_CUTOFF_IDS`：kind → 合成稳定 id（1/2），**属于前后端契约，不允许随意改**
- `VALID_CUTOFFS`：合法集合，用于 `require_cutoff` 校验

## L40-L42：`cutoff_kinds()`

- 返回固定顺序的 cutoff 元组；其它模块（尤其导入进度的 per-cutoff 切片）会复用它。

## L45-L65：`require_dataset(session, slug)`

- 用 slug 查 `datasets` 表（返回 dataset_id、name、source_root 等）
- 若不存在：抛 404（这是 API 层对“资源不存在”的统一语义）

## L67-L70：`require_cutoff(cutoff)`

- 若 cutoff 不在 `VALID_CUTOFFS`：抛 404
- 这保证了 `/datasets/{slug}/cutoffs/{cutoff}/...` 下的所有资源都不会出现奇怪 kind

## L73-L80：`cutoff_id` / `cutoff_label`

- 将 cutoff kind 映射成前端需要的稳定 id 与 label

## L83-L100（SQL 片段 helpers）

- `source_cutoff_filter_sql()`：生成 `WHERE` 子句片段，统一使用 `jsonb_extract_path_text(extra_metadata, 'source_cutoff') = :cutoff`
- `source_prsm_id_sql` / `source_sequence_id_sql` / `source_proteoform_id_sql`：
  - 统一把 `extra_metadata` 中的业务 id 字段 cast 为 integer
  - 这样 API 里不需要重复写 cast 逻辑
- `json_text(field, key)`：小工具，生成 jsonb 的 extract SQL

## L103-L124：`prsm_list_select_sql(where_sql="")`

- **目的**：PrSM 列表页与 Proteoform 详情页都需要“PrSM 摘要行”的统一 SELECT。
- universal schema 没有 `prsms` 表，所以这里从 `identification_matches` 查：
  - `match_id` → 列表行 `id`
  - `source_prsm_id` → 列表/详情使用的业务 `prsm_id`
  - `p_value`/`matched_fragment_number`/`matched_peak_number` 等来自 `extra_metadata`
  - `e_value/q_value`、`experimental_mass`、`precursor_charge/mz` 来自 match 主列
  - `proteoform_mass` 通过 `LEFT JOIN proteoforms` 补齐（可能为 null）
  - `ms1_scans/ms2_scans` 来自 `extra_metadata`
- `where_sql` 由调用者拼接并传入（例如按 dataset_id+cutoff、或加 protein/proteoform 过滤）

## L127-L143：`prsm_list_item(row)`

- **目的**：把 SQL row 变成前端需要的字段结构（键名对齐 `PrsmListItemOut`）
- 为什么单独做：
  - 保持列表/详情构造一致
  - 避免多个 API 复制粘贴相同 mapping

## L148-L160：`load_prsm_detail(detail_path)`

- **目的**：PrSM 详情页需要三个大 JSON：`annotated_protein`、`ms_header`、`ms_peaks`
- 规则：
  - `detail_path` 为空或文件不存在 → 返回 `(None, None, None)`（由上层决定如何降级）
  - 用 `load_prsm_document(path)` 读取并解析明细文件
  - 用 `get_prsm_root(doc)` 统一 wrapper 形态
  - 从 `prsm_root` 里取：
    - `annotated_protein`
    - `ms.ms_header`
    - `ms.peaks`

