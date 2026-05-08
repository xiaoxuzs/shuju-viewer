# `back/app/ingest/universal_prsm_js_adapter.py` 逐行解释（prsm*.js bundle → universal schema）

> 来源文件：`back/app/ingest/universal_prsm_js_adapter.py`

## L1-L16（模块定位）

- 该 adapter 用于一种特殊 ZIP：
  - 没有 TopPIC HTML 输出树（没有 `toppic_prsm_cutoff/data_js/...`）
  - 只有 `data/prsm*.js`（PrSM 详情 JS 对象）
  - 以及 1+ 个 mzML 文件（运行期用 mzML memory 谱图 API 读取）
- 导入目标依然是 universal schema 的 7 表子集：
  - datasets / runs / proteins / proteoforms / protein_relation_mapping / identification_matches
- 谱图峰数组不入库，依赖 mzML 内存 store

## L18-L29（导入）

- `json/dataclass/Path/Any`：基础
- `create_engine/text`：写 DB
- `to_int/to_float`：把 TopPIC 字符串数字安全转换
- `load_js_object`：读取 `prsm*.js`

## L31-L38：`UniversalImportStats`

- 返回 dataset_id/run_id 与计数（proteins/proteoforms/matches）

## L40-L41：`_json`

- `json.dumps(..., ensure_ascii=False)`：把 extra_metadata 写成 JSON 字符串（入库时 CAST 为 jsonb）

## L44-L48：`_accession_from_sequence_name`

- accession 兜底规则：无 name 则 `sequence_<id>`

## L50-L65：`ingest_universal_prsm_js` 输入校验

- `root/data` 必须存在
- 必须至少有一个 `prsm*.js`

## L66-L100：创建 engine + dataset 行

- 可选 replace：按 slug 删除旧 dataset（cascade 清理）
- 插入 datasets：
  - `source_software='TopPIC_prsm_js'`
  - `source_root=str(root)`
  - capabilities 写了 has_ms1/has_ms2/has_prsms 等（与 TopPIC adapter 保持一致的“能力语义”）

## L101-L128：按 spectrum_file_name 创建 runs（闭包 `_get_or_create_run`）

- `run_by_file`：`file_name -> run_id`
- `_get_or_create_run(file_name)`：
  - 以 `file_name.strip()` 做 key
  - 插入 runs：
    - `file_path=str(root)`（数据集根）
    - `file_name=key`（通常来自 prsm header 的 spectrum_file_name）
  - 返回 run_id

> 注意：严格的 `run_metadata.mzml_file_path` 写入不在此 adapter 内做，而是在 `import_jobs.py` 的 mzML mapping 校验通过后统一写入（这样保证 mapping strict 且集中）。

## L129-L201：按 annotated_protein 派生 proteins/proteoforms（两个闭包）

- `protein_by_seq`：`sequence_id -> proteins.protein_id`
- `_get_or_create_protein(annotated)`：
  - 用 annotated.sequence_id/sequence_name/sequence_description 插入 proteins
  - extra_metadata 写 source ids
- `proteoform_by_key`：`(sequence_id, proteoform_id) -> proteoforms.proteoform_id`
- `_get_or_create_proteoform(annotated)`：
  - 用 annotated.proteoform_mass 插入 proteoforms.theoretical_mass
  - extra_metadata 写 source ids、sequence_name、source_cutoff="prsm"

## L202-L242：protein_relation_mapping 去重插入

- `relation_keys`：`(protein_id, proteoform_id)` 去重
- 插入 protein_relation_mapping：
  - entity_type 固定 PROTEOFORM
  - extra_metadata 只写 `source_cutoff="prsm"`（bundle 模式等价于单一结果集）

## L243-L302：插入 identification_matches（每个 prsm*.js 一条）

- 取 ms_header.spectrum_file_name：
  - 缺失直接失败（这是 mzML mapping 的关键输入）
- run_id：由 spectrum_file_name 决定
- ms2_scan：从 header.scans 转 int，缺失则失败
- 插入 identification_matches：
  - scan_number=ms2_scan
  - experimental_mass/precursor_mz/precursor_charge/intensity：从 header 提取
  - e_value/q_value/p_value/matched_*：从 prsm_root 提取
  - detail_path：指向当前 prsm*.js 文件
  - extra_metadata：
    - source ids（cutoff/prsm_id/sequence_id/proteoform_id）
    - ms1/ms2 ids/scans（字符串形式）
    - import_mode="prsm_js"

## L304-L314：标记 READY + 返回 stats

- 更新 datasets/runs status 为 READY
- 选择一个默认 run_id（第一个插入的 run）
- stats 的 proteins/proteoforms/matches 用缓存大小/文件数计算

