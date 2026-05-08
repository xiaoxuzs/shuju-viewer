## `docs/dataset-ir-v0.md` 逐行解释

> 这是一份“数据层统一契约（Dataset IR）”的草案规范，覆盖：数据准入模块、入库标准、capabilities、SpectrumV0、Adapter 接口与迁移路线。它是面向“未来多格式接入”的设计文档；当前仓库实现已采纳其中部分思想（例如 capabilities、按需读取、统一匹配表思路），但也存在与文档早期版本不一致之处（例如 universal schema 最终没有 cutoffs/prsms 表，而是 identification_matches+extra_metadata 虚拟 cutoff）。

本 explain 以“章节含义 + 与当前实现的对应关系”来解释整份文档（因为原文已经非常详细，逐行重复解释会高度冗余）。

---

### L1-L8：标题、版本与目标

- 定义该规范的版本、最后更新日期与目标：明确数据库允许接收什么数据，以及外部数据如何通过准入模块变成可入库/可展示/可画谱的数据。

---

### L10-L36：核心结论（“数据库是标准”）

- 给出流程：外部数据 → 准入模块 → 校验 → adapter/normalize → 再校验 → 入库/拒绝/降级。
- 强调 Adapter 的职责是让外部格式符合内部标准，而不是让数据库/前端适配所有原始格式。

---

### L38-L55：当前数据库定位（历史描述）

- 这一段描述了当时的表：datasets/cutoffs/proteins/proteoforms/prsms（属于早期形态）。
- 当前仓库已经演进为 universal schema（见 `docs/universal_schema.sql`），因此这部分应理解为“设计背景”，不是当前实现的真实表结构。

---

### L57-L102：数据准入模块（Import Gateway）

- 定义 detect_format/validate_raw_package/adapter.normalize/validate_database_payload/import_to_database/verify_visibility 的内部流程。
- 与当前实现的对应：
  - `services/import_jobs.py` 负责“包级校验 + 解压 + 布局识别”
  - `ingest/universal_toppic_adapter.py` 与 `ingest/universal_prsm_js_adapter.py` 扮演 adapter
  - `datasets.capabilities` 在导入阶段写入，驱动前端功能开关

---

### L104-L155：Dataset 入库标准与 capabilities

- 定义 slug/name/source_path/capabilities 等必需与建议字段。
- 当前实现：
  - universal schema 的 datasets 表包含 slug/dataset_name/source_root/capabilities/extra_metadata 等
  - 并新增 `source_zip_sha256` 支持 ZIP 去重导入

---

### L158-L206：Cutoff / ResultSet 设计

- 文档建议把 cutoffs 理解为 ResultSet/AnalysisView。
- 当前实现差异：
  - universal schema 没有 cutoffs 表；
  - cutoff 以字符串存于 `identification_matches.extra_metadata.source_cutoff`；
  - `api/v1/universal_compat.py` 提供 registry（kinds/id/label）。

---

### L209-L352：Protein / Proteoform 入库标准

- 逐项列出蛋白与形态需要的字段、建议字段与约束。
- 当前实现的映射方式：
  - 结构字段存在 proteins/proteoforms 表
  - TopPIC 业务字段与统计值存 `extra_metadata`，由 API 层用 `jsonb_extract_path_text` 映射成前端字段
  - protein ↔ proteoform 的归属通过 `protein_relation_mapping`

---

### L354-L488：PrSM 入库标准（历史描述）

- 文档用 `prsms` 表承载 PrSM 的思想与字段需求。
- 当前实现差异：
  - universal schema 无 prsms 表；
  - PrSM 存于 `identification_matches`（entity_type='PROTEOFORM'），并用 extra_metadata 存 source_prsm_id 等；
  - 详情文件路径用 `detail_path` 指向 prsm*.js，实现懒加载。

---

### L490-L592：Spectrum 存储策略与 SpectrumV0

- 强调谱图大对象不应入库，应保持在磁盘或标准化文件中。
- 定义 SpectrumV0 的最小字段与 envelopes 的要求（对 topdown_prsm 完整功能）。
- 当前实现：
  - TopFD JS 模式：后端 `spectra.py` 从 `topfd/ms1_json/ms2_json` 按需读；
  - mzML-memory 模式：`mzml_spectra.py` + `mzml_store.py` 首次请求 lazy-load mzML。

---

### L594-L637：Capabilities 驱动降级展示

- 文档提出 capability 作为“前端是否展示完整 PrSM 页面”的开关。
- 当前实现已落地：datasets.capabilities 在导入时写入，前端 PrSM 详情页会根据 capability 决定 spectra source 与展示策略。

---

### L639-L777：建议新增管理表（import_runs/source_files）与 Adapter 标准

- 这部分属于未来扩展规划。
- 当前仓库已实现的管理能力主要是 `import_jobs`（ZIP 导入任务持久化）；import_runs/source_files 仍是可选二期。

---

### L779-L944：命令建议、迁移路线、验收标准与变更记录

- 给出未来 CLI 的 `--format` 设想、校验规则分层、迁移阶段 A/B/C/...、以及 DoD 验收标准。
- 对维护者的实际作用：
  - 当接入新格式时，应以“写 Adapter + capability 准确声明 + 校验/拒绝/降级策略明确”为主线，而不是直接改前端去读新格式。

