## `docs/universal_schema.sql` 逐行解释

> 目标：定义 Universal Viewer 的 PostgreSQL 数据库“通用/统一 schema”。它用少量核心表统一承载 bottom-up（肽段/PSM）与 top-down（proteoform/PrSM）两种分析模式，并通过 `identification_matches` 与 `protein_relation_mapping` 这两张“多态/适配层”表把不同来源软件的结果统一到相同查询接口。

说明：该 SQL 文件很长、以 DDL + COMMENT 为主，且很多 comment 已经是“逐行解释”。因此本解释会按块（表/索引/约束）对应文件中的行范围说明“创建了什么、为什么这样设计、与当前代码如何对接”，同时点出和当前项目实际使用的子集（TopPIC/TopFD top-down）。

---

### L1-L5：文件头与使用方式

- **L1-L2**：声明这是 Universal Viewer 的数据库 schema，目标数据库为 PostgreSQL。
- **L3-L4**：给出 `psql` 执行方式：把该文件导入到名为 `Universal_Viewer` 的数据库。
- **L5**：空行分隔。

---

## `datasets` 表（L6-L45）

### L6-L25：表结构与约束

- **L6-L25**：`CREATE TABLE datasets`：
  - `dataset_id BIGSERIAL PRIMARY KEY`：内部主键。
  - `dataset_name`：展示名。
  - `slug`：短标识，UNIQUE（前端 URL 与 API 路由使用）。
  - `analysis_mode`：BOTTOM_UP/TOP_DOWN（CHECK 约束，L20-L22）。
  - `source_software`：来源软件（TopPIC/MaxQuant 等）。
  - `source_root`：导入后的根目录路径（当前后端大量依赖它定位文件）。
  - `status`：IMPORTED/PARSING/READY/ERROR（CHECK，L23-L24）。
  - `description`：可空说明。
  - `capabilities JSONB`：能力声明（当前代码用它决定 spectra_source 等行为）。
  - `extra_metadata JSONB`：扩展字段。
  - `created_at`：导入时间。
  - `source_zip_sha256`：导入源 zip 指纹（用于去重；当前后端 import_jobs 会写入/查询）。

### L27-L39：COMMENT

- 这些 `COMMENT ON ...` 是对字段语义的“内置文档”。当前后端 API 的 `require_dataset` 会查询其中部分字段（dataset_id, dataset_name, slug, description, source_root, created_at）。

### L42-L45：唯一索引（zip 指纹）

- **L42-L44**：`uq_datasets_source_zip_sha256`：对非 NULL 的 sha256 建唯一索引。
- 作用：同一 zip 不允许重复导入（除非删库后指纹变为 NULL/或删除记录）。

---

## `runs` 表（L47-L78）

- `runs` 表把一个 dataset 下的“运行/原始文件”作为实体。
- 当前项目在 top-down 场景主要用它来存放：
  - run_id（供 mzML-memory API 使用）
  - run_metadata（其中 `mzml_file_path` 是严格映射结果）

关键列：
- `run_id BIGSERIAL PRIMARY KEY`
- `dataset_id` 外键 → datasets（ON DELETE CASCADE）
- `file_path`/`file_name`：记录原始文件路径/名
- `analysis_mode`/`status`：同 datasets 有 CHECK
- `instrument_metadata`/`sample_metadata`/`run_metadata`：JSONB 扩展
- `created_at`

后端 `mzml_spectra.py` 会按 `(run_id, dataset_id)` 查询 `run_metadata` 并取 `mzml_file_path`。

补充：`run_metadata` 在本项目里是“mzML-memory 模式的关键契约字段”，导入流程会在 finalize 阶段写入 `{"mzml_file_path": ".../xxx.mzML"}`，并在运行期由 `back/app/services/mzml_store.py` 按 run_id 懒加载到内存。

---

## `proteins` 表（L80-L103）

- 存储基础蛋白实体（top-down 与 bottom-up 共用根节点）。
- 当前项目的 top-down 导入把 TopPIC 的 `sequence_id/name` 等放到 `extra_metadata`：
  - API `proteins.py` 通过 `jsonb_extract_path_text(extra_metadata,'source_sequence_id')` 等读出并映射到前端字段。

约束：
- `UNIQUE(dataset_id, accession, is_decoy)`：同一 dataset 同 accession+decoy 唯一。

---

## `peptides` 表（L105-L126）

- bottom-up 专用（当前 TopPIC/TopFD top-down 流程基本不使用）。
- schema 预留：未来可以接入 MaxQuant/FragPipe 等 PSM 数据。

---

## `proteoforms` 表（L128-L146）

- top-down 专用实体：记录 PTM/截短等导致的“蛋白形态”。
- 当前项目在 universal adapter 中主要写：
  - `theoretical_mass`
  - `extra_metadata`（存 TopPIC 的 source_proteoform_id、sequence_name、prsm_number、best_prsm_id 等统计）
- API `proteoforms.py` 用 extra_metadata 映射到前端字段。

---

## `identification_matches` 表（L148-L201）

这是整个 schema 的核心“统一匹配表”：

- 统一替代：
  - bottom-up 的 PSM（peptide-spectrum match）
  - top-down 的 PrSM（proteoform-spectrum match）
- 通过 `entity_type` + `entity_id` 指向不同实体（peptides 或 proteoforms）。

关键列（与当前代码强相关）：
- `match_id`：主键（在很多 API 里作为内部 id）
- `dataset_id` / `run_id`
- `scan_number`：用于 mzML 精确定位（mzML-memory 模式需要）
- `ms_level`：默认 2
- `entity_type`：CHECK('PEPTIDE','PROTEOFORM')
- `entity_id`：多态指针（当前 top-down 模式指向 proteoforms.proteoform_id）
- `experimental_mass` / `precursor_mz` / `precursor_charge` / `intensity`
- `score` / `e_value` / `q_value`
- `detail_path`：指向 prsm*.js（后端 `load_prsm_detail` 使用）
- 当前实现中 `detail_path` 可指向 `prsm*.(js|json|txt)`，读取逻辑由后端 `services/prsm_files.py` 做兼容与 wrapper 归一化
- `extra_metadata`：存 TopPIC 的 `source_cutoff/source_prsm_id/source_sequence_id` 等业务字段

当前 API：
- `prsms.py` 列表/详情：就是以 identification_matches 为主表查询；
- `proteoforms.py` 详情里列 PrSM：同样查询 identification_matches；
- `datasets.py` 统计 cutoffs：也从 identification_matches.extra_metadata 聚合。

---

## `protein_relation_mapping` 表（L203-L227）

这张表解决“protein 与下属实体（peptide/proteoform）”的多对多归属：

- `protein_id` 指向 proteins.protein_id
- `entity_type` 指 'PEPTIDE' 或 'PROTEOFORM'
- `entity_id` 指向对应实体主键

当前 top-down 流程：
- 主要用于：
  - proteins 列表/详情：判断某 protein 在某 cutoff 下是否存在匹配（EXISTS join mapping + identification_matches）
  - prsms 列表按 protein_id 过滤：通过 mapping 把 PrSM（->proteoform）归属到 protein

---

## 索引（L230-L260）

- 为 runs、proteins、peptides、proteoforms、identification_matches、protein_relation_mapping 提供常用查询索引。
- 当前项目比较关键的索引：
  - `ix_identification_matches_dataset_run_scan`：mzML 按 run+scan 定位时的性能
  - `ix_identification_matches_entity`：按 proteoform 查 PrSM 时的性能
  - `ix_protein_relation_mapping_entity`：由 entity 找 protein 的 join 性能

---

## `import_jobs` 表（L266-L305）

虽然 universal schema 主要是“生物结果表”，但这里也包含了导入任务表：

- 用于持久化 ZIP 导入后台任务状态（支持 uvicorn 重启后前端继续轮询）。
- 字段与后端 `services/import_jobs.py` 的写入逻辑一致：
  - status/stage/stage_label/stage_detail/message/error/progress
  - dataset_slug/dataset_name/description/source_zip_name
  - created_at/updated_at
- 索引：
  - `ix_import_jobs_status_updated_at`：便于 GC/查询最新任务
  - `ix_import_jobs_dataset_slug`：按 slug 查任务（删除保护/重复导入判定）

---

### 与当前代码的对接总结（只点最关键）

- **datasets**：`require_dataset`、datasets 列表 API、导入删除逻辑
- **runs**：mzML-memory 模式（`runs.run_metadata.mzml_file_path`）
- **proteins/proteoforms**：主要字段放在 extra_metadata；API 用 jsonb_extract_path_text 映射
- **identification_matches**：PrSM 统一表（detail_path + extra_metadata.source_prsm_id/source_cutoff）
- **protein_relation_mapping**：protein ↔ proteoform 归属与过滤的关键
- **import_jobs**：ZIP 导入后台任务持久化

