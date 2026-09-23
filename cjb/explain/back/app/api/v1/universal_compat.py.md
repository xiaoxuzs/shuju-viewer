# `back/app/api/v1/universal_compat.py` 逐行解释

> 来源文件：`back/app/api/v1/universal_compat.py`  
> 兼容层：cutoff 合成 id/label、`require_dataset` / `require_cutoff`、PrSM 列表共用 SQL（`prsm_list_select_sql`）与行映射（`prsm_list_item`）、从 `detail_path` 读 PrSM 明细（`load_prsm_detail`）。

---

## L1-L13：模块说明与导入

- **L1**：模块 docstring：在保持 legacy API 形状的前提下读 universal schema。
- **L3-L12**：`Path`、`Any`、`HTTPException`/`status`、`text`、`Session`；`load_prsm_document`、`get_prsm_root`（`prsm_files`）。

---

## L14-L37：Cutoff registry（注释 + 常量）

- **L14-L23**：注释说明：无 `cutoffs` 表，`source_cutoff` 为字符串；前端仍要稳定 id、label、顺序。
- **L25**：`_CUTOFF_KIND_ORDER = ("prsm", "proteoform")`。
- **L27-L30**：`_CUTOFF_LABELS`。
- **L32-L35**：注释 + `_CUTOFF_IDS`（**契约数字，勿改**）。
- **L37**：`VALID_CUTOFFS`。

---

## L40-L72：公开校验与 cutoff 元数据 API

- **L40-L42**：`cutoff_kinds()` → `_CUTOFF_KIND_ORDER`。
- **L45-L66**：`require_dataset`：`SELECT` 含 `dataset_id`、`dataset_name`、`slug`、`description`、`source_software`、`source_root`、`capabilities`、`created_at`；无行 → **404**。
- **L69-L72**：`require_cutoff`：不在 `VALID_CUTOFFS` → **404**。
- **L75-L77**：`cutoff_id`。
- **L80-L82**：`cutoff_label`。
- **L85-L86**：`source_cutoff_filter_sql()`：返回 `jsonb_extract_path_text(extra_metadata, 'source_cutoff') = :cutoff` 片段。

---

## L89-L102：extra_metadata → SQL 表达式小函数

- **L89-L90**：`source_prsm_id_sql`。
- **L93-L94**：`source_sequence_id_sql`。
- **L97-L98**：`source_proteoform_id_sql`。
- **L101-L102**：`json_text(field, key)`。

---

## L105-L126：`prsm_list_select_sql(where_sql="")`

- 组装带可选 `WHERE {where_sql}` 的 `SELECT`：`im.match_id AS id`、各 `source_*` / `p_value` / matched 计数自 `extra_metadata`、`im.e_value`/`q_value`、前体列、`LEFT JOIN proteoforms` 得 `proteoform_mass`、`ms1_scans`/`ms2_scans` 文本字段等。

---

## L129-L145：`prsm_list_item(row)`

- 将 SQL 行 dict 规范为与 `PrsmListItemOut` 一致的键集合。

---

## L148-L160：`load_prsm_detail(detail_path)`

- **L149-L150**：`detail_path` 假值 → `(None, None, None)`。
- **L151-L153**：`Path` 不存在 → 同上。
- **L154-L155**：`load_prsm_document`。
- **L156-L159**：`get_prsm_root` 后取 `annotated_protein`、`ms.ms_header`、`ms.peaks`（缺省用 `{}` / `or None`）。
- **L160**：返回三元组。

---

## 附录：源码顶层符号索引（与 `universal_compat.py` 全文检索对齐）

- `cutoff_kinds`、`require_dataset`、`require_cutoff`、`cutoff_id`、`cutoff_label`
- `source_cutoff_filter_sql`、`source_prsm_id_sql`、`source_sequence_id_sql`、`source_proteoform_id_sql`、`json_text`
- `prsm_list_select_sql`、`prsm_list_item`、`load_prsm_detail`
