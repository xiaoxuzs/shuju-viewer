# `back/app/ingest/universal_toppic_adapter.py` 逐行解释（TopPIC/TopFD → universal schema）

> 来源文件：`back/app/ingest/universal_toppic_adapter.py`
>
> 注意：该文件很长，本文按“功能块 + 行号段”解释。它是 **TopPIC/TopFD HTML 输出树** 导入 universal schema 的主适配器，也是 ZIP 后台导入（`import_jobs.py`）调用的核心写模型之一。

---

## L1-L15（模块定位：导入目标与刻意不做的事）

- 说明该 adapter 面向 universal 7 表：
  - `datasets/runs/proteins/peptides/proteoforms/identification_matches/protein_relation_mapping`
- 明确 **不导入谱图峰数组**：
  - TopFD 的 `spectrum*.js` 保留在磁盘
  - 后端 `api/v1/spectra.py` + `services/spectrum_cache.py` 按需读取

## L17-L36（导入与 CLI 外壳）

- 引入 `typer`：提供 CLI 命令 `python -m app.ingest.universal_toppic_adapter ingest ...`
- `Console/tqdm`：用于 CLI 进度输出（与后台任务的 progress_callback 是两套体系，但复用同一导入逻辑）
- `create_engine/text/Connection`：写入 universal schema（raw SQL）
- `best_prsm/ensure_list/to_int/to_float`：解析 TopPIC 的字符串数字与“单元素数组压扁”
- `load_js_object`：解析 `proteins.js` / `prsm*.js`

## L37-L40：`CUTOFF_DIRS`

- cutoff kind → TopPIC 输出目录名映射：
  - `"prsm"` → `toppic_prsm_cutoff`
  - `"proteoform"` → `toppic_proteoform_cutoff`
- 意义：
  - 导入时会遍历两个 cutoff 目录（若缺失则跳过）
  - cutoff 信息最终写入 `extra_metadata.source_cutoff`

## L43-L52：`UniversalImportStats`

- 导入统计：dataset_id/run_id + 计数（proteins/proteoforms/relations/matches/skipped）
- 被：
  - CLI 打印
  - 后台导入任务写入 job 成功的 stage_detail

## L54-L78：进度事件 `ProgressEvent` 与 `_emit`

- `ProgressEvent`：
  - `phase`: `"init" | "proteins" | "matches" | "finalize"`
  - `cutoff`: per-cutoff 阶段带 cutoff_kind
  - `current/total`: 局部进度
  - `message`: 文字提示
- `_emit`：
  - 用 try/except 吞掉回调异常，避免“进度上报”影响导入正确性
- 该机制被 `import_jobs.py` 用来转换成全局 0..100 进度条。

## L81-L124：Typer CLI 命令 `ingest(...)`

- 解析 CLI 参数：
  - `root/slug/name/mode/replace` 等
  - `database_url` 若不传，fallback 到 `settings.database_url`（CLI 与 API 用同库）
- 调用核心函数 `ingest_universal_toppic(...)` 并打印 stats

## L126-L193：`_RunRegistry`（多 run 懒创建）

- 目的：把 PrSM 的 `ms_header.spectrum_file_name` 映射成 `runs.run_id`
- 行为：
  - `get_default()`：
    - fast 导入（不读 prsm*.js）时只有一个默认 run
    - 缺 spectrum_file_name 的记录也落到默认 run
  - `get_or_create(file_name)`：
    - full 导入会读每个 PrSM 详情
    - 每个 distinct spectrum_file_name 都创建一个 runs 行
    - 这样 `identification_matches.run_id` 能区分多 mzML/RAW 文件

## L195-L293：`ingest_universal_toppic(...)`（核心入口）

### 输入校验（L218-L223）

- root 必须存在
- mode 必须是 `fast` 或 `full`

### 建立连接 + 可选 replace（L224-L230）

- `engine = create_engine(database_url)`
- `with engine.begin()`：事务块
- 若 replace：`DELETE FROM datasets WHERE slug=:slug`（依赖 cascade 清旧数据）

### 创建 dataset + 默认 run（L231-L238）

- `_create_dataset(...)` 插入 datasets（status=IMPORTED、capabilities=JSONB）
- 初始化 `_RunRegistry`
- `runs.get_default()`：保证 stats.run_id 总有值

### 缓存/去重结构（L239-L243）

- `protein_by_source_seq`: `source_sequence_id -> proteins.protein_id`
- `proteoform_by_source_key`: `(source_sequence_id, source_proteoform_id) -> proteoforms.proteoform_id`
- `relation_keys`: 避免重复插入 protein_relation_mapping
- `fast_match_keys`: fast 模式避免重复插入 identification_matches

### 遍历 cutoff 并导入（L244-L277）

- 对每个 cutoff_kind：
  - 找 `toppic_*_cutoff/data_js/proteins.js`，缺失则跳过
  - 调用 `_import_proteins_and_forms(...)`：
    - 导入 proteins/proteoforms/relation
    - fast 模式：同时登记 PrSM 摘要（不打开 prsm*.js）
  - 若 mode==full：
    - 再调用 `_import_prsm_matches(...)` 逐个打开 `prsm*.js` 导入 identification_matches 的完整信息（scan、precursor、ms ids 等）

### finalize（L278-L292）

- datasets.status 与 runs.status 标记 READY
- 发出 finalize progress event
- 返回 stats

## L295-L334：`_create_dataset`

- 插入 datasets：
  - `analysis_mode='TOP_DOWN'`
  - `source_software='TopPIC_TopFD'`
  - `source_root=str(root)`（导入时记录的绝对路径）
  - `capabilities` 默认包含 has_ms1/has_ms2/has_prsms 等
- 返回 dataset_id

## L336-L435：`_import_proteins_and_forms`（读 proteins.js）

- `doc = load_js_object(proteins_file)`
- 兼容两种嵌套路径取 `protein_list.proteins.protein`
- `ensure_list`：把被压扁的单元素对象转成 list
- 逐 protein：
  - `source_seq_id` 缺失则跳过
  - 若 protein 未插入过：`_insert_protein(...)`
  - 遍历 `compatible_proteoform`：
    - 若 proteoform 未插入过：`_insert_proteoform(...)`
    - 插入 protein_relation_mapping：`_insert_relation(...)`（去重）
    - fast 模式：调用 `_import_fast_prsm_summaries(...)`
- 同时按 25 个 protein 的粒度 emit progress（proteins phase）

## L436-L551：`_insert_protein` / `_insert_proteoform` / `_insert_relation`

- `_insert_protein`：
  - 计算 accession/decoy
  - 汇总 prsm_number 与 best_prsm（最小 e-value）
  - 把 TopPIC 的业务字段塞进 `extra_metadata`
- `_insert_proteoform`：
  - `theoretical_mass` 尝试从 prsm 摘要提取
  - `extra_metadata` 写 source ids、cutoff、prsm_number、best_prsm 等
- `_insert_relation`：
  - protein_relation_mapping 记录 protein → proteoform 的归属关系
  - `extra_metadata` 写 source ids 与 cutoff

## L603-L715：`_import_fast_prsm_summaries`（fast 模式登记 match）

- 不打开 `prsm*.js`，只从 `proteins.js` 的 prsm 摘要登记 identification_matches：
  - `scan_number=-1`
  - precursor/ms ids/scans 等字段多数为空（后续详情页读取 prsm*.js 再补齐）
  - `detail_path` 指向 `prsms/prsm{ID}.js`，若文件不存在则跳过并计入 skipped
  - `extra_metadata` 写：
    - `source_cutoff/source_prsm_id/source_sequence_id/source_proteoform_id`
    - `p_value/matched_fragment_number/matched_peak_number`
    - `import_mode="fast"`

## L717-...：`_import_prsm_matches`（full 模式逐个打开 prsm*.js）

- full 模式会：
  - 遍历 `prsms/prsm*.js`
  - 解析 `annotated_protein` 得到 `sequence_id/proteoform_id` 并映射到 DB proteoform_id
  - 从 `ms_header` 取 scan/precursor/ms ids
  - 用 `_RunRegistry.get_or_create(spectrum_file_name)` 做多 run 映射
  - 插入更完整的 identification_matches（并 emit matches progress）

> 说明：后续如果你希望我把该文件“从第一行到最后一行每个函数都解释到”，我会继续分段读取未展示部分并把剩余函数补齐到本解释文件里（当前已覆盖到 fast/full 两条主路径与关键写入点）。

