# `back/app/schemas/protein.py` 逐行解释

> 来源文件：`back/app/schemas/protein.py`

## L1（模块定位）

- 定义 Protein / Proteoform / PrSM 的列表与详情响应模型（Pydantic）。
- 这些模型与前端 `front/src/api/types.ts` 一一对应。

## L3-L8（导入）

- `Any`：PrSM 详情里包含三块大 JSON（ms_header/ms_peaks/annotated_protein），结构不强约束
- `BaseModel/ConfigDict`：Pydantic 模型

## L10-L23：`ProteinListItemOut`

- 用于 proteins 列表：
  - `id`：数据库主键（`proteins.protein_id`）
  - `sequence_id`：TopPIC 业务 sequence id（存 extra_metadata）
  - `sequence_name/sequence_description`
  - `compatible_proteoform_number/prsm_number`
  - `best_prsm_id/best_prsm_e_value`

## L25-L29：`ProteinDetailOut`

- 继承 `ProteinListItemOut`
- 增加 `proteoforms: list[ProteoformListItemOut]`：蛋白详情页需要下属 proteoform 列表

## L31-L46：`ProteoformListItemOut`

- 用于 proteoforms 列表与 protein 详情中的子表：
  - `id`：数据库主键（`proteoforms.proteoform_id`）
  - `proteoform_id`：TopPIC 业务 proteoform id（存 extra_metadata）
  - `sequence_id/sequence_name`
  - `proteoform_mass`
  - `prsm_number/best_prsm_*`
  - `n_acetylation/unexpected_shift_number`：当前实现多为 null，但模型保留字段

## L48-L53：`ProteoformDetailOut`

- 继承 `ProteoformListItemOut`
- 增加：
  - `protein_id`：用于从 proteoform 返回“所属 protein”的链接
  - `prsms: list[PrsmListItemOut]`：该 proteoform 下的 PrSM 摘要列表

## L55-L74：`PrsmListItemOut`

- PrSM 列表行（不含大 JSON）：
  - `id`：数据库主键（`identification_matches.match_id`）
  - `prsm_id`：TopPIC 业务 prsm id（extra_metadata）
  - `sequence_id`：TopPIC 业务 sequence id（extra_metadata）
  - `p_value/e_value/fdr`
  - matched 数量、precursor 信息、proteoform_mass、ms1/ms2 scans

## L76-L89：`PrsmDetailOut`

- 继承 `PrsmListItemOut`，额外包含：
  - `dataset_id/run_id/proteoform_id`：用于谱图 API 与页面跳转
  - `spectrum_file_name`：用于多 run / mzML mapping
  - `ms1_ids/ms2_ids/feature_inte`
  - 三块大 JSON：`ms_header/annotated_protein/ms_peaks`

## L91-L93：`model_rebuild()`

- 由于 `ProteinDetailOut` 和 `ProteoformDetailOut` 使用了前向引用（字符串形式的类型名），需要在模块尾部显式 rebuild，确保 Pydantic 正确解析嵌套类型。

