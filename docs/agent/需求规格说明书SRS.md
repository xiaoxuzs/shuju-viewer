# Viewer 需求规格说明书（SRS）

> 文档版本：v1.0　　编写日期：2026-07-29　　文档性质：**内部工程文档**
> 详细程度：**接口级**——每个 REST 端点、前端路由与关键内部模块均有独立编号需求。
> 上游文档：[产品需求文档PRD.md](产品需求文档PRD.md)　　下游文档：[项目开发计划.md](项目开发计划.md)

---

## 1. 引言

### 1.1 目的

本文把 PRD 中的产品意图翻译为**可实现、可验证**的规格：接口签名、输入输出、错误语义、数据结构、性能与安全指标。开发与测试以本文为准；本文与代码冲突时以代码为准并回改本文。

### 1.2 范围

覆盖 `back/`（FastAPI 后端）、`front/`（React 前端）、`docs/universal_schema.sql`（数据库）三者构成的 Viewer 系统，以及 [规划中] 的陌生谱图 Agent 子系统。

**不覆盖**：`E:\viewer-two`（`.zp` 二进制层，独立仓库，本文只定义其对外接口的使用约束）、上游质谱鉴定软件、ThermoRawFileParser 内部实现。

### 1.3 编号约定

| 前缀 | 域 |
| --- | --- |
| `FR-META` | 元信息 |
| `FR-DS` | 数据集管理 |
| `FR-IMP` | 路径导入 |
| `FR-UPL` | 上传导入 |
| `FR-ING` | 导入中间层（内部模块） |
| `FR-TD` | Top-Down 读接口 |
| `FR-JS` | TopFD JS 谱图接口 |
| `FR-MZ` | mzML 谱图接口 |
| `FR-BU` | Bottom-Up 接口 |
| `FR-SPM` | 谱图内存与派生数据 |
| `FR-AGT` | 陌生谱图 Agent（[规划中]） |
| `UI` | 前端界面 |
| `EIF` | 外部接口 |
| `NFR` | 非功能需求 |

状态与优先级标记沿用 PRD §0。所有 REST 路径省略统一前缀 `/api/v1`（`FR-META-01` 除外）。

### 1.4 参考文档

`docs/universal_schema.sql`（数据库真值）、`docs/developer/*`（16 篇模块文档）、`budocs/决策登记表.md`（BU 的 19 条锁定决策）、`budocs/验收测试矩阵.md`、`cs/性能测验约定.md`、`AGENTS.md`、[陌生谱图Agent总体设计.md](陌生谱图Agent总体设计.md)、[Agent状态机与上下文设计.md](Agent状态机与上下文设计.md)、[ZP转换接入与安全边界.md](ZP转换接入与安全边界.md)。

---

## 2. 系统概述

### 2.1 部署架构

```mermaid
flowchart LR
    B["浏览器<br/>React SPA"]
    V["Vite 开发服务器<br/>:5173"]
    F["FastAPI<br/>:8000"]
    P[("PostgreSQL 14+")]
    D["DATA_ROOT<br/>数据集文件 + .viewer-derived"]
    T["ThermoRawFileParser"]
    Z["zp-binary-layer<br/>（规划中）"]
    W["agent_worker<br/>（规划中）"]

    B --> V -->|"/api 代理"| F
    F --> P
    F --> D
    F --> T
    W -.-> P
    W -.-> D
    W -.-> Z
    F -.-> Z
```

前端通过 Vite 的 `/api` 代理访问后端（`http://127.0.0.1:8000`），axios 基址为 `/api/v1`。规划中的 `agent_worker` 是**独立进程**，与 FastAPI 通过 PostgreSQL 协作，不通过 HTTP 相互调用。

### 2.2 技术栈

| 层 | 技术 | 版本 |
| --- | --- | --- |
| 后端运行时 | Python | ≥ 3.12 |
| Web 框架 | FastAPI / uvicorn | 0.136.0 / 0.46.0 |
| ORM 与驱动 | SQLAlchemy / psycopg | 2.0.49 / 3.3.3（**读路径使用 raw SQL，不用 ORM 映射**） |
| 校验 | pydantic / pydantic-settings | 2.13.3 / 2.14.0 |
| 质谱解析 | pyteomics / lxml / numpy | 4.7.5 / 6.1.0 / 2.4.4 |
| 列式读取 | pyarrow | 24.0.0 |
| 数据库 | PostgreSQL | 14+ |
| 前端框架 | React / React Router | 18.3.1 / 6.29.0 |
| 服务端状态 | TanStack Query | 5.67.2 |
| 构建 | Vite / TypeScript | 6.1.0 / 5.6.3 |
| 样式 | Tailwind CSS + Radix 原语 | 3.4 |
| 可视化 | d3 / three | 7.9.0 / 0.184.0 |
| 测试 | pytest / Playwright | 9.0.3 / 1.60.0 |
| 包管理 | uv（后端）/ pnpm（前端） | — |
| 规划新增 | LangGraph + PostgreSQL Checkpointer | 待定版本 |

**关键架构约定**：数据库迁移**不使用 Alembic**，采用 `back/migrations/*.sql` 手工脚本；部分表结构（`import_jobs`、指纹列）在应用启动时用原生 SQL 补齐。

### 2.3 配置项

来源 `back/app/core/config.py`。

| 配置 | 默认值 | 含义 |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/histone_viewer` | 数据库连接 |
| `DATA_ROOT` | `{repo}/shuju` | 数据集与上传根目录 |
| `IMPORT_PATH_MUST_BE_UNDER_DATA_ROOT` | `false` | 是否强制导入路径位于数据根下 |
| `API_CORS_ORIGINS` | `http://localhost:5173` | 允许的跨域来源 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `SPECTRUM_CACHE_SIZE` | `256` | TopFD JS 谱图 LRU 条数 |
| `IMPORT_NATIVE_FOLDER_PICKER` | `true` | 是否启用原生文件夹对话框 |
| `IMPORT_PICKER_LOOPBACK_ONLY` | `true` | 对话框是否仅限本机 |
| `IMPORT_UPLOAD_ENABLED` | `true` | 是否启用上传导入 |
| `IMPORT_UPLOAD_DIR_NAME` | `.viewer-uploads` | 上传子目录名 |
| `IMPORT_UPLOAD_DISK_RESERVE_BYTES` | 5 GiB | 接受上传前的最小剩余磁盘 |
| `IMPORT_UPLOAD_MAX_FILE_BYTES` | `0`（不限） | 单文件上限 |
| `IMPORT_UPLOAD_MAX_TOTAL_BYTES` | `0`（不限） | 会话总量上限 |
| `IMPORT_UPLOAD_MAX_FILES` | `5000` | 会话文件数上限 |
| `IMPORT_UPLOAD_CHUNK_BYTES` | 8 MiB | 流式写入缓冲 |
| `VIEWER_SPECTRUM_MEMORY_MAX_BYTES` | 6 GiB（下限 64 MiB） | 全局谱图内存预算 |
| `RAW_CONVERSION_TIMEOUT_SECONDS` | `3600` | 单文件 RAW 转换超时 |
| `RAW_CONVERSION_FORCE` | `false` | mzML 已存在时是否强制重转 |
| `THERMO_RAW_FILE_PARSER_EXE` | 自动发现 | 转换器路径覆盖 |
| `BU_UNIPROT_ENABLED` | `false` | 是否允许联网取 UniProt 序列 |
| `BU_FRAGMENT_MATCH_ROOT` | `{repo}/BU- Fragment Match` | PFMB 侧车生成目录 |
| `PFMB_BRIDGE_EXE` / `PFMB_V2_BRIDGE_EXE` | 见配置文件 | PFMB 生成程序 |
| `PFMB_V2_REFERENCE_ROOTS` | 逗号分隔路径 | 预置 PFMB v2 侧车搜索根 |
| `VIEWER_ENV` | `development` | `test` 时强制隔离（见 NFR-SEC-05） |
| `ZP_BINARY_REPOSITORY` | [规划中] | `.zp` 只读仓库或镜像 |
| `ZP_BINARY_BASE_COMMIT` | [规划中] | 人工批准的基线 commit |
| `ZP_BINARY_DEFAULT_FORMAT_VERSION` | [规划中] | 人工批准的格式版本 |

---

## 3. 数据模型

### 3.1 已实现：universal schema（8 张表）

真值文件 `docs/universal_schema.sql`。设计要点：**没有 `cutoffs` 表、没有独立 `prsms` 表**，这两个概念通过 `identification_matches.extra_metadata` 的 JSONB 字段承载。

| 表 | 用途 | 主键 | 关键列 |
| --- | --- | --- | --- |
| `datasets` | 导入批次 / 项目入口 | `dataset_id` | `slug`（唯一）、`analysis_mode`（`BOTTOM_UP`/`TOP_DOWN`）、`source_software`、`source_root`、`status`、`capabilities`（JSONB）、`extra_metadata`（JSONB）、`source_dataset_fingerprint`（CHAR(32)）、`source_import_kind` |
| `runs` | 单次质谱采集 | `run_id` | `dataset_id`（FK CASCADE）、`file_path`、`file_name`、`analysis_mode`、`instrument_metadata`、`sample_metadata`、`run_metadata`（JSONB，含 `mzml_file_path`、`raw_format`） |
| `proteins` | 蛋白根实体（跨 cutoff 共享） | `protein_id` | `dataset_id`、唯一约束 `(dataset_id, accession, is_decoy)`、`base_sequence`、`gene_name`、`description` |
| `peptides` | BU 肽段实体 | `peptide_id` | `dataset_id`、唯一约束 `(dataset_id, sequence)` |
| `proteoforms` | TD 蛋白形式实体 | `proteoform_id` | `dataset_id`、`modifications`（JSONB）、`theoretical_mass` |
| `identification_matches` | **统一的 PSM / PrSM 表** | `match_id` | `dataset_id`、`run_id`、`entity_type`（`PEPTIDE`/`PROTEOFORM`）+ `entity_id` 多态引用、`e_value`、`q_value`、`pep`、`scan_number`、`precursor_mz`、`precursor_charge`、`detail_path`、`detail_cache`、`extra_metadata` |
| `protein_relation_mapping` | 蛋白 ↔ 肽段/蛋白形式 多对多 | `mapping_id` | `dataset_id`、`protein_id`、`entity_type` + `entity_id`、`start_position`、`end_position`、`is_unique` |
| `import_jobs` | 异步导入任务登记 | `job_id`（UUID） | `status`、`stage`、`progress`、`dataset_slug`、`source_path`、`import_type`、时间戳 |

#### 3.1.1 关键 JSONB 约定

| 位置 | 键 | 含义 |
| --- | --- | --- |
| `datasets.capabilities` | `spectra_source` | `topfd_js` / `mzml_memory` / `mixed` / `zp`（[规划中]） |
| `datasets.capabilities` | `analysis_shape` | 用于判定「仅谱图」模式 |
| `datasets.capabilities` | `has_ms2_pfmb` | 是否有 PFMB 侧车，控制前端 PFMB 区块 |
| `runs.run_metadata` | `mzml_file_path` | run ↔ mzML 严格绑定路径 |
| `runs.run_metadata` | `raw_format` | `mzml` / `bruker_d` / `thermo_raw` |
| `identification_matches.extra_metadata` | `source_cutoff` | `"prsm"` / `"proteoform"`，TD 的虚拟 cutoff 归属 |
| `identification_matches.extra_metadata` | `source_prsm_id` | TopPIC 业务 PrSM 编号（**不是数据库主键**） |
| `identification_matches.extra_metadata` | `diaclip` | DIA-CLIP 来源标识与证据字段 |

#### 3.1.2 必需索引

| 索引 | 表 | 用途 |
| --- | --- | --- |
| `(source_dataset_fingerprint, source_import_kind)` 部分唯一索引 | `datasets` | 重复导入检测（指纹非空时生效） |
| `idx_im_dataset_q` | `identification_matches` | BU 列表按 q-value 过滤 |
| `idx_im_dataset_run` | `identification_matches` | BU 按 run 过滤 |

### 3.2 [规划中]：Agent 业务表（5 张）

设计见 [Agent状态机与上下文设计.md](Agent状态机与上下文设计.md) §5。LangGraph checkpointer 使用**独立表或独立 schema**，与下述业务表分离。

| 表 | 用途 | 关键约束 |
| --- | --- | --- |
| `agent_import_cases` | Case 主记录，`case_id` 同时作为 LangGraph `thread_id` | `0 <= autonomous_attempt_used <= 3`、`context_revision >= 1`、`guided_attempt_no >= 0`；含 `version`（乐观并发）、`lease_owner` / `lease_expires_at`（执行租约） |
| `agent_attempts` | 每轮尝试与验证摘要 | `UNIQUE(case_id, attempt_kind, attempt_no)` |
| `agent_messages` | Case 内消息流 | `UNIQUE(case_id, sequence_no)`；`UNIQUE(case_id, idempotency_key) WHERE idempotency_key IS NOT NULL` |
| `agent_artifacts` | 产物**元数据**（大二进制不入库） | `storage_ref` 为 Case 目录内的受控相对引用；含 `sha256`、`size_bytes` |
| `agent_notifications` | 通知 | `kind ∈ {NEEDS_USER, REVIEW_REQUIRED, FAILED}`；红色角标 = `COUNT(*) WHERE active AND kind='NEEDS_USER'` |

**明确不设计**：`user_id`、用户级 `read_at`。无登录系统时增加这些列会制造虚假的隔离承诺（PR-AGT-11）。

---

## 4. 功能需求

### 4.1 元信息

| 编号 | 方法 | 路径 | 功能 | 响应 | 优先级 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| FR-META-01 | GET | `/health`（**无 `/api/v1` 前缀**） | 健康检查 | `{"status": "ok"}` | P0 | [已实现] |
| FR-META-02 | — | — | 启动时自动补齐 `import_jobs` 表与 `datasets` 指纹列 | — | P0 | [已实现] |
| FR-META-03 | — | — | CORS 来源可配置，允许携带凭据 | — | P0 | [已实现] |

### 4.2 数据集管理

| 编号 | 方法 | 路径 | 功能 | 关键入参 | 响应 | 优先级 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FR-DS-01 | GET | `/datasets` | 数据集列表 | — | `list[DatasetOut]` | P0 | [已实现] |
| FR-DS-02 | GET | `/datasets/{slug}` | 数据集详情 | 路径 `slug` | `DatasetOut` | P0 | [已实现] |
| FR-DS-03 | DELETE | `/datasets/{slug}` | 删除数据集 | 查询 `cancel_import`（bool，默认 false） | `DatasetDeletedOut` | P0 | [已实现] |

**`DatasetOut` 字段规格**：`id`、`slug`、`name`、`description`、`source_path`、`capabilities`（dict）、`analysis_mode`（`TOP_DOWN`/`BOTTOM_UP`/null）、`dataset_mode`（默认 `top_down`）、`status`、`source_software`、`extra_metadata`、`runs`（`DatasetRunSummary[]`）、`bu_runs`（`BuRunSummary[]`）、`created_at`、`updated_at`（可为 null——`datasets` 表无此列）、`cutoffs`（`CutoffOut[]`）。

| 编号 | 需求 | 优先级 | 状态 |
| --- | --- | --- | --- |
| FR-DS-04 | TD 数据集的 `cutoffs` 固定为两项，顺序 `("prsm", "proteoform")`，合成 id 固定为 `1`/`2`——**前端依赖此约定，不得变更** | P0 | [已实现] |
| FR-DS-05 | `CutoffOut` 的 `protein_count` / `proteoform_count` / `prsm_count` 由 SQL 聚合并严格按 `extra_metadata.source_cutoff` 过滤 | P0 | [已实现] |
| FR-DS-06 | BU 数据集的 `cutoffs` 为空数组（锁定决策） | P0 | [已实现] |
| FR-DS-07 | 删除仅删数据库行；`deleted_disk` 恒为 `false`，磁盘目录保留 | P0 | [已实现] |
| FR-DS-08 | 存在活跃导入任务且 `cancel_import=false` 时，删除返回 `409`；`cancel_import=true` 时先取消任务再删除 | P0 | [已实现] |
| FR-DS-09 | 判定「活跃任务」时须忽略僵死任务：`queued` 超 15 分钟、`running` 超 120 分钟 | P1 | [已实现] |

### 4.3 路径导入

| 编号 | 方法 | 路径 | 功能 | 关键入参 | 响应 | 优先级 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FR-IMP-01 | POST | `/imports/pick-folder` | 在 API 宿主机弹出原生文件夹对话框 | — | `ImportPickFolderOut{path, cancelled}` | P1 | [已实现] |
| FR-IMP-02 | POST | `/imports` | 提交路径导入任务 | `ImportEnqueueIn` | `202` + `ImportJobCreatedOut{job_id, status}` | P0 | [已实现] |
| FR-IMP-03 | GET | `/imports/{job_id}` | 查询任务状态 | 路径 `job_id` | `ImportJobOut` | P0 | [已实现] |

**`ImportEnqueueIn` 规格**：`source_path`（必填，服务器上的绝对路径或家目录路径）、`slug`（必填，唯一）、`name`（必填）、`description`（可选）、`import_type`（可选枚举，省略时走向后兼容的自动识别）。

**`ImportJobOut` 规格**：`job_id`、`status`（`queued`/`running`/`success`/`failed`）、`message`、`error`、`dataset_slug`、`progress`（0–100 浮点）、`stage`（机器可读阶段码）、`stage_label`（人类可读阶段文案，**当前为英文**，与前端整体文案语言一致）、`stage_detail`（自由文本细节行）、`created_at`、`updated_at`。

| 编号 | 需求 | 优先级 | 状态 |
| --- | --- | --- | --- |
| FR-IMP-04 | `import_type` 枚举取值：`TD_RAW`、`TD_MZML`、`TD_TOPPIC_HTML`、`TD_PRSM_BUNDLE`、`TD_TOPPIC_NATIVE`、`BU_DIA_NN`、`BU_DIA_CLIP`、`DDA_RAW`，并保留旧别名（`TOPPIC`、`PRSM`、`MZML_ONLY` 等） | P0 | [已实现] |
| FR-IMP-05 | 原生对话框在 `IMPORT_NATIVE_FOLDER_PICKER=false` 或非本机请求时返回 `403` | P1 | [已实现] |
| FR-IMP-06 | 导入在守护线程中异步执行，HTTP 请求立即返回 `202` | P0 | [已实现] |
| FR-IMP-07 | TD 阶段序列：`queued` → `fingerprint` → `raw_conversion` → `init` → `proteins` → `matches` → `finalize` → `success`/`failed` | P0 | [已实现] |
| FR-IMP-08 | BU 阶段序列在 `init` 与 `matches` 之间增加 `runs`、`peptides` | P0 | [已实现] |
| FR-IMP-08b | 数据库提交后另有 `derived_data` 阶段（派生数据构建），其失败不影响导入成功状态 | P1 | [已实现] |
| FR-IMP-09 | 进度分配：`fingerprint` 1–8%、`raw_conversion` 8–12%、`matches` 约 20–95%（TD）/ 50–92%（BU）；`progress=100` 仅在 `status=success` 时出现 | P1 | [已实现] |
| FR-IMP-10 | 完成状态的任务记录保留 7 天后回收 | P2 | [已实现] |
| FR-IMP-11 | `IMPORT_PATH_MUST_BE_UNDER_DATA_ROOT=true` 时，导入根须位于 `DATA_ROOT` 子树内，否则拒绝 | P1 | [已实现] |

### 4.4 上传导入

| 编号 | 方法 | 路径 | 功能 | 关键入参 | 响应 | 优先级 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FR-UPL-01 | POST | `/import-uploads` | 创建上传会话 | `ImportUploadCreateIn{import_type}` | `ImportUploadCreatedOut` | P0 | [已实现] |
| FR-UPL-02 | PUT | `/import-uploads/{upload_id}/files` | 流式写入单个文件 | 查询 `relative_path`；请求体为原始字节流；头 `Content-Length` | `ImportUploadFileOut` | P0 | [已实现] |
| FR-UPL-03 | POST | `/import-uploads/{upload_id}/start` | 结束上传并转为导入任务 | `ImportUploadStartIn{parameters: slug/name/description}` | `202` + `ImportJobCreatedOut` | P0 | [已实现] |
| FR-UPL-04 | GET | `/import-uploads/{upload_id}` | 查询上传会话状态 | — | `ImportUploadSessionOut` | P0 | [已实现] |
| FR-UPL-05 | DELETE | `/import-uploads/{upload_id}` | 删除上传会话 | — | `204` | P1 | [已实现] |

| 编号 | 需求 | 优先级 | 状态 |
| --- | --- | --- | --- |
| FR-UPL-06 | 上传文件落盘位置固定为 `DATA_ROOT/{IMPORT_UPLOAD_DIR_NAME}/{uuid}/files/`，会话元数据写 `manifest.json` | P0 | [已实现] |
| FR-UPL-07 | `relative_path` 须拒绝：`..` 片段、绝对路径、URL 编码绕过、Windows 盘符根；落盘目标须通过相对性校验 | P0 | [已实现] |
| FR-UPL-08 | 上传树中拒绝符号链接与 junction | P0 | [已实现] |
| FR-UPL-09 | 会话文件数上限 5000；单文件与总量上限可配置（默认不限）；写入缓冲 8 MiB | P1 | [已实现] |
| FR-UPL-10 | 剩余磁盘低于 `IMPORT_UPLOAD_DISK_RESERVE_BYTES`（默认 5 GiB）时拒绝接受上传 | P1 | [已实现] |
| FR-UPL-11 | `start` 后须先校验布局再入队；校验失败不创建导入任务 | P0 | [已实现] |
| FR-UPL-12 | 上传导入与路径导入在得到受控 `source_root` 后**汇合到同一 worker**（`enqueue_path_import`） | P0 | [已实现] |
| FR-UPL-13 | 后端**不做服务端 ZIP 解压**；客户端逐文件上传 | — | [已实现]（明确不支持 ZIP） |
| FR-UPL-14 | 断点续传与 24 小时会话过期清理 | P2 | [规划中] |

### 4.5 导入中间层（内部模块）

这些需求不对应 HTTP 端点，但是导入正确性的核心，且 `AGENTS.md` 对其模块边界有强制约束。

| 编号 | 需求 | 实现位置 | 优先级 | 状态 |
| --- | --- | --- | --- | --- |
| FR-ING-01 | 根路径解析：把用户选择的多层嵌套目录 `resolve()` 后解析出唯一导入根 | `back/app/dataset_ingest_root/resolver.py` | P0 | [已实现] |
| FR-ING-02 | 指纹算法：递归 `scandir`（**不跟随符号链接**），每文件生成 `相对路径\|size\|mtime_ns`，排序后取 UTF-8 文本的 MD5，返回 32 位小写 hex 与文件数 | `back/app/fingerprint/dataset_metadata_fingerprint.py` | P0 | [已实现] |
| FR-ING-03 | 指纹模块**不读文件内容**，且不得依赖 FastAPI / SQLAlchemy / ingest | 同上 | P0 | [已实现] |
| FR-ING-04 | 重复识别业务键为 `(source_dataset_fingerprint, source_import_kind)`；冲突时导入失败并在错误信息中给出已有 slug 与名称 | `back/app/services/import_jobs.py` | P0 | [已实现] |
| FR-ING-05 | 布局探测：识别 TopPIC HTML 树、PrSM bundle、TopPIC Native、DIA-NN、mzML-only、RAW 六类形态，输出 `ImportPlan` | `back/app/services/import_planner/` | P0 | [已实现] |
| FR-ING-06 | 显式 `import_type` 与探测结果不一致时拒绝导入并说明差异 | `back/app/services/import_selection.py` | P0 | [已实现] |
| FR-ING-07 | TopPIC HTML 判定：存在 `toppic_prsm_cutoff` 或 `toppic_proteoform_cutoff` 且含 `proteins.js` 与 PrSM 详情文件 | `import_planner/detectors.py` | P0 | [已实现] |
| FR-ING-08 | TopPIC HTML 入库走 `ingest_universal_toppic`；谱图源按 `topfd/ms1_json` 与 `topfd/ms2_json` 是否齐全判定为 `topfd_js`，否则回退 `mzml_memory` | `back/app/ingest/universal_toppic_adapter.py` | P0 | [已实现] |
| FR-ING-09 | PrSM bundle 入库走 `ingest_universal_prsm_js`，必须存在 mzML | `back/app/ingest/universal_prsm_js_adapter.py` | P1 | [已实现] |
| FR-ING-10 | TopPIC Native（`*_toppic_prsm.xml` + `*_ms2.msalign`）先在 `.viewer-derived/toppic-native/{fingerprint}/` 生成 prsm 树，再复用 PrSM bundle 适配器 | `back/app/ingest/td/toppic_native_output.py` | P1 | [已实现] |
| FR-ING-11 | DIA-NN 入库走 `ingest_universal_diann`，读取 `all_report.parquet` / `target_report.parquet`，导入阈值 q < 0.01（锁定决策） | `back/app/ingest/bu/universal_diann_adapter.py` | P0 | [已实现] |
| FR-ING-12 | DIA-CLIP 入库走 `ingest_universal_diaclip`，复用 DIA-NN 布局并叠加 DIA-CLIP 结果 TSV；v1 仅支持单 run，多 run 输入须拒绝 | `back/app/ingest/bu/universal_diaclip_adapter.py` | P1 | [部分实现] |
| FR-ING-13 | 独立 mzML / RAW 入库走 `ingest_mzml_only`，写入 `analysis_shape=mzml_only` | `back/app/ingest/mzml_only_adapter.py` | P1 | [已实现] |
| FR-ING-14 | mzML 严格映射：从 `prsm*.js` 提取 `ms.ms_header.spectrum_file_name`，与目录内 mzML 做 1:1 规范化匹配；冲突或缺失即导入失败。**此步不读 mzML 内容** | `back/app/services/mzml_mapping.py` | P0 | [已实现] |
| FR-ING-15 | Thermo RAW 在导入期经 ThermoRawFileParser 转换为**索引化非压缩** mzML；单文件超时默认 3600 秒；转换失败即导入失败 | `back/app/raw_conversion/` | P0 | [已实现] |
| FR-ING-16 | 导入提交后生成派生数据：每个 mzML run 的扫描索引与色谱摘要侧车；生成失败以警告形式记录，不回滚导入 | `back/app/services/post_import_derived_data.py` | P1 | [已实现] |
| FR-ING-17 | DIA-NN 导入后准备 PFMB 侧车（生成或定位既有 v1/v2 侧车），并据此设置 `capabilities.has_ms2_pfmb` | `back/app/pfmb/sidecar_prepare.py` | P1 | [已实现] |
| FR-ING-18 | 数据集目录被移动后，须能修正数据库中的陈旧绝对路径 | `back/app/services/incoming_path_relocate.py` | P1 | [已实现] |
| FR-ING-19 | 编排层**禁止**手写递归扫盘与 MD5，必须调用指纹模块公开 API（`AGENTS.md` 强制约束） | — | P0 | [已实现] |
| FR-ING-20 | 主业务代码**禁止**写死本机盘符；基准路径通过 `VIEWER_BENCH_DATASET_ROOT` 或 `cs/` 脚本顶部常量提供 | — | P0 | [已实现] |

### 4.6 Top-Down 读接口

| 编号 | 方法 | 路径 | 功能 | 关键入参 | 响应 | 优先级 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FR-TD-01 | GET | `/datasets/{slug}/cutoffs/{cutoff}/proteins` | 蛋白列表 | `page`、`page_size`（≤500）、`search`、`sort`、`order` | `Page[ProteinListItemOut]` | P0 | [已实现] |
| FR-TD-02 | GET | `/datasets/{slug}/cutoffs/{cutoff}/proteins/{protein_id}` | 蛋白详情 + 下属 proteoform | 路径 `protein_id`（**数据库主键**） | `ProteinDetailOut` | P0 | [已实现] |
| FR-TD-03 | GET | `/datasets/{slug}/cutoffs/{cutoff}/proteoforms` | 蛋白形式列表 | `page`、`page_size`、`protein_id`、`sort`、`order` | `Page[ProteoformListItemOut]` | P0 | [已实现] |
| FR-TD-04 | GET | `/datasets/{slug}/cutoffs/{cutoff}/proteoforms/{proteoform_id}` | 蛋白形式详情 + PrSM 列表 | 路径 `proteoform_id`（**数据库主键**） | `ProteoformDetailOut` | P0 | [已实现] |
| FR-TD-05 | GET | `/datasets/{slug}/cutoffs/{cutoff}/prsms` | PrSM 列表 | `page`、`page_size`、`proteoform_id`、`protein_id`、`sort`、`order` | `Page[PrsmListItemOut]` | P0 | [已实现] |
| FR-TD-06 | GET | `/datasets/{slug}/cutoffs/{cutoff}/prsms/{prsm_id}` | PrSM 详情 | 路径 `prsm_id`（**TopPIC 业务编号，非数据库主键**） | `PrsmDetailOut` | P0 | [已实现] |

| 编号 | 需求 | 优先级 | 状态 |
| --- | --- | --- | --- |
| FR-TD-07 | `cutoff` 路径段仅接受 `prsm` / `proteoform`，其他值返回 `404` | P0 | [已实现] |
| FR-TD-08 | 蛋白在数据模型中跨 cutoff 共享，列表须通过 `EXISTS identification_matches WHERE source_cutoff = :cutoff` 关联链过滤，保证列表与当前 cutoff 的可见集合一致 | P0 | [已实现] |
| FR-TD-09 | 蛋白形式同样通过 `EXISTS ... source_cutoff` 判定「在该 cutoff 下出现过鉴定」，否则不显示 | P0 | [已实现] |
| FR-TD-10 | `search` 对蛋白名称与描述做 `ILIKE` 匹配 | P1 | [已实现] |
| FR-TD-11 | `PrsmDetailOut` 须包含三个来自磁盘 `prsm*.js` 的大 JSON：`ms_header`、`ms_peaks`、`annotated_protein`；按需读取解析，不预先入库 | P0 | [已实现] |
| FR-TD-12 | `prsm_id` 通过 `extra_metadata.source_prsm_id` 定位，`detail_path` 指向磁盘详情文件 | P0 | [已实现] |
| FR-TD-13 | `page_size` 上限 500，超出须被拒绝或截断 | P1 | [已实现] |
| FR-TD-14 | 读路径统一使用 raw SQL（`sqlalchemy.text`），不使用 ORM 映射 | P1 | [已实现] |

### 4.7 TopFD JS 谱图接口

| 编号 | 方法 | 路径 | 功能 | 响应 | 优先级 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| FR-JS-01 | GET | `/datasets/{slug}/spectra/ms1/{spec_id}` | 读 `topfd/ms1_json/spectrum{id}.js` | `dict` | P0 | [已实现] |
| FR-JS-02 | GET | `/datasets/{slug}/spectra/ms2/{spec_id}` | 读 `topfd/ms2_json/spectrum{id}.js` | `dict` | P0 | [已实现] |

| 编号 | 需求 | 优先级 | 状态 |
| --- | --- | --- | --- |
| FR-JS-03 | 路径解析顺序：优先用数据库中的 `datasets.source_root`；不可用时回退 `DATA_ROOT/<slug_dir>`，保证数据目录跨机器/盘符搬迁后仍可用 | P0 | [已实现] |
| FR-JS-04 | 谱图文件按路径做 LRU 缓存，容量由 `SPECTRUM_CACHE_SIZE`（默认 256）控制 | P1 | [已实现] |
| FR-JS-05 | TopFD `spectrum*.js` **不入库**，仅按需读取 | P0 | [已实现] |

### 4.8 mzML 谱图接口

| 编号 | 方法 | 路径 | 功能 | 关键入参 | 响应 | 优先级 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FR-MZ-01 | GET | `/datasets/{dataset_id}/runs/{run_id}/spectra/{scan_number}` | 按扫描号取单张谱图 | 路径均为数字 id | `dict`（`scan`、`native_id`、`ms_level`、`rt_seconds`、`mz[]`、`intensity[]`、MS2 的 `precursor`） | P0 | [已实现] |
| FR-MZ-02 | GET | `/datasets/{dataset_id:int}/runs/{run_id:int}/chromatogram` | TIC/BPC 色谱图（数字 id 路由） | 查询 `type ∈ {tic, bpc}` | `BuChromatogramOut` | P1 | [已实现] |
| FR-MZ-03 | GET | `/datasets/{dataset_id}/runs/{run_id}/scan-index` | 分页扫描元数据索引 | `ms_level`、`offset`、`limit`（≤2000） | `dict` | P1 | [已实现] |

| 编号 | 需求 | 优先级 | 状态 |
| --- | --- | --- | --- |
| FR-MZ-04 | 单张谱图读取须使用字节级预建索引，**不得全文件迭代** | P0 | [已实现] |
| FR-MZ-05 | mzML 路径来自 `runs.run_metadata.mzml_file_path`，峰数组不入库 | P0 | [已实现] |
| FR-MZ-06 | 数字 `dataset_id` 路由与 slug 路由须能正确区分，不得互相误匹配 | P0 | [已实现] |
| FR-MZ-07 | gzip 压缩 mzML 不支持随机访问，须明确报错而非静默降级 | P1 | [已实现] |
| FR-MZ-08 | 派生索引缺失或过期时返回 `409`，且错误详情须包含可执行的补齐命令 | P1 | [已实现] |
| FR-MZ-09 | 色谱图返回点数须降采样至不超过 8000 点 | P1 | [已实现] |

### 4.9 Bottom-Up 接口

#### 4.9.1 总览与列表

| 编号 | 方法 | 路径 | 功能 | 关键入参 | 响应 | 优先级 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FR-BU-01 | GET | `/datasets/{slug}/overview` | BU 数据集总览（计数 + run 列表） | — | `BuOverviewOut` | P0 | [已实现] |
| FR-BU-02 | GET | `/datasets/{slug}/overview/rt-mz` | RT–m/z 热图 | `run_id`、`q_max`、`bins_rt`、`bins_mz`、`decoy` | `BuRtMzHeatmapOut` | P1 | [已实现] |
| FR-BU-03 | GET | `/datasets/{slug}/proteins` | 蛋白列表 | `page`、`page_size`、`search`、`decoy` | `Page[BuProteinListItemOut]` | P0 | [已实现] |
| FR-BU-04 | GET | `/datasets/{slug}/proteins/{protein_id}` | 蛋白详情（含序列覆盖数据） | 路径 `protein_id` | `BuProteinDetailOut` | P0 | [已实现] |
| FR-BU-05 | GET | `/datasets/{slug}/peptides` | 肽段列表 | `page`、`page_size`、`search`、`q_max` | `Page[BuPeptideListItemOut]` | P0 | [已实现] |
| FR-BU-06 | GET | `/datasets/{slug}/peptides/{peptide_id}` | 肽段详情 | 路径 `peptide_id` | `BuPeptideDetailOut` | P0 | [已实现] |
| FR-BU-07 | GET | `/datasets/{slug}/matches` | 匹配列表 | `page`、`page_size`、`q_max`、`run_id`、`peptide_id`、`protein_id`、`charge`、`search`、`decoy`、`sort`、`order` | `Page[BuMatchListItemOut]` | P0 | [已实现] |
| FR-BU-08 | GET | `/datasets/{slug}/matches/{match_id}` | 匹配详情 | 路径 `match_id` | `BuMatchDetailOut` | P0 | [已实现] |

#### 4.9.2 谱图与色谱证据

| 编号 | 方法 | 路径 | 功能 | 关键入参 | 响应 | 优先级 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FR-BU-09 | GET | `/datasets/{slug}/matches/{match_id}/xic` | 前体 XIC | `ppm`（默认 10） | `BuXicOut` | P0 | [部分实现] |
| FR-BU-10 | GET | `/datasets/{slug}/matches/{match_id}/spectrum/ms2` | 带 b/y 标注的 MS2 | `ppm`、`scan`、`rt` | `BuSpectrumV1` | P0 | [部分实现] |
| FR-BU-11 | GET | `/datasets/{slug}/matches/{match_id}/spectrum/ms1` | MS1 谱图 | — | `BuSpectrumV1` | P0 | [部分实现] |
| FR-BU-12 | GET | `/datasets/{slug}/matches/{match_id}/product-xic` | 单条产物离子 XIC | `mz`、`ppm` | `BuProductXicOut` | P1 | [已实现] |
| FR-BU-13 | POST | `/datasets/{slug}/matches/{match_id}/product-xics` | 批量产物离子 XIC | `BuProductXicBatchIn` | `BuProductXicBatchOut` | P1 | [已实现] |
| FR-BU-14 | GET | `/datasets/{slug}/matches/{match_id}/mobility-slice` | 离子迁移率切片（Bruker） | — | `BuMobilitySliceOut` | P1 | [已实现] |
| FR-BU-15 | GET | `/datasets/{slug}/runs/{run_id}/chromatogram` | TIC/BPC（slug 路由） | `type ∈ {tic, bpc}` | `BuChromatogramOut` | P0 | [已实现] |
| FR-BU-16 | GET | `/datasets/{slug}/runs/{run_id}/dia-windows` | DIA 隔离窗口 | — | `BuDiaWindowsOut` | P1 | [已实现] |

#### 4.9.3 PFMB 预计算碎片匹配

| 编号 | 方法 | 路径 | 功能 | 响应 | 优先级 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| FR-BU-17 | GET | `/datasets/{slug}/matches/{match_id}/ms2-slots` | PFMB 时间槽列表 | `BuMs2SlotListOut` | P1 | [已实现] |
| FR-BU-18 | GET | `/datasets/{slug}/matches/{match_id}/ms2-annotation/{prsm_index}` | 单个 PFMB 标注 | `BuMs2AnnotationOut` | P1 | [已实现] |
| FR-BU-19 | GET | `/datasets/{slug}/matches/{match_id}/ms2-annotation-matrix` | 完整标注矩阵 | `BuMs2AnnotationMatrixOut` | P1 | [已实现] |

#### 4.9.4 BU 通用约束

| 编号 | 需求 | 优先级 | 状态 |
| --- | --- | --- | --- |
| FR-BU-20 | BU 路径**不含 cutoff 段**，URL 统一为 `/datasets/{slug}/...`，无 `/bu/` 前缀（锁定决策） | P0 | [已实现] |
| FR-BU-21 | 路由层只做 schema 校验、守卫与 service 调用，**不得包含 SQL** | P1 | [已实现] |
| FR-BU-22 | `decoy` 参数语义须与锁定决策 D19 一致 | P0 | [已实现] |
| FR-BU-23 | match 级 MS2/XIC/MS1（FR-BU-09/10/11）**仅支持 mzML run**；Bruker `.d` 须返回 `404` 而非崩溃 | P1 | [部分实现] |
| FR-BU-24 | MS2 扫描解析支持按 `scan` 精确指定或按 `rt` 就近查找，规则须确定 | P0 | [已实现] |
| FR-BU-25 | 批量产物离子 XIC 上限 8 条 | P1 | [已实现] |
| FR-BU-26 | 蛋白序列覆盖依赖 `base_sequence`；DIA-NN 报告缺少肽段位置时须从 FASTA/UniProt 解析，离线时降级为列表模式而非报错 | P1 | [部分实现] |
| FR-BU-27 | PFMB 数据为**中性质量而非 m/z**，且约 38% 强度为零；接口与 UI 不得与实测 b/y 的 m/z 混同 | P0 | [已实现] |
| FR-BU-28 | 总览接口**不得预取** match 级谱图；蛋白页不得请求 MS2/XIC | P1 | [已实现] |
| FR-BU-29 | 数据库须存在 `idx_im_dataset_q` 与 `idx_im_dataset_run` 索引，列表查询须命中索引扫描 | P0 | [已实现] |

### 4.10 谱图内存与派生数据

| 编号 | 需求 | 实现位置 | 优先级 | 状态 |
| --- | --- | --- | --- | --- |
| FR-SPM-01 | 全局谱图内存池以**字节预算**管理，默认 6 GiB，下限 64 MiB，通过 `VIEWER_SPECTRUM_MEMORY_MAX_BYTES` 配置 | `back/app/spectrum_memory/config.py` | P0 | [已实现] |
| FR-SPM-02 | 驻留粒度为**整个数据集的 bundle**（含其全部映射 run），不是单 run | `spectrum_memory/mzml_dataset_bundle.py` | P0 | [已实现] |
| FR-SPM-03 | 超预算时按最近最少使用顺序淘汰整个数据集；访问时更新最近使用序 | `spectrum_memory/eviction_coordinator.py` | P0 | [已实现] |
| FR-SPM-04 | 同一数据集的并发载入须**单飞**：首个请求载入，其余等待同一事件，不得重复载入 | 同上 | P0 | [已实现] |
| FR-SPM-05 | 载入前须预留字节额度，避免预算被并发击穿 | `spectrum_memory/size_accounting.py` | P1 | [已实现] |
| FR-SPM-06 | 容量不足与未驻留须有独立的错误类型 | `spectrum_memory/types.py` | P1 | [已实现] |
| FR-SPM-07 | 路径提交式读取完成后须显式释放数据集驻留 | `spectrum_memory/__init__.py` | P1 | [已实现] |
| FR-SPM-08 | 扫描索引与色谱摘要以侧车文件持久化于 `.viewer-derived/`，支持独立补齐命令 | `back/app/services/derived_data_backfill.py` | P1 | [已实现] |
| FR-SPM-09 | `services/mzml_store.py`（per-run 缓存，上限 4 run）已被内存池取代，标记为废弃 | — | P2 | [已实现]（待清理） |

### 4.11 陌生谱图 Agent（[规划中]）

以下全部为 [规划中]。设计来源见 §1.4 三份 Agent 设计文档。

#### 4.11.1 Case 与消息 API

| 编号 | 方法 | 路径 | 功能 | 优先级 |
| --- | --- | --- | --- | --- |
| FR-AGT-01 | POST | `/agent-import-cases` | 创建 Case（通常由 planner 兜底调用） | P0 |
| FR-AGT-02 | GET | `/agent-import-cases` | Case 列表，支持状态筛选 | P0 |
| FR-AGT-03 | GET | `/agent-import-cases/{case_id}` | Case 摘要 | P0 |
| FR-AGT-04 | GET | `/agent-import-cases/{case_id}/messages` | 按序号分页取消息 | P0 |
| FR-AGT-05 | POST | `/agent-import-cases/{case_id}/messages` | 提交用户回答 | P0 |
| FR-AGT-06 | POST | `/agent-import-cases/{case_id}/stop` | 请求安全停止 | P0 |
| FR-AGT-07 | GET | `/agent-import-cases/{case_id}/attempts` | 尝试与验证摘要 | P0 |
| FR-AGT-08 | GET | `/agent-import-cases/{case_id}/artifacts` | 允许展示的产物元数据 | P1 |
| FR-AGT-09 | GET | `/agent-notifications/count` | 待回答 Case 数量 | P0 |
| FR-AGT-10 | GET | `/agent-notifications` | 活跃通知列表 | P0 |
| FR-AGT-11 | GET | `/agent-events` | 可选 SSE 状态事件 | P2 |

**FR-AGT-12**（P1）：所有 Agent route 只做 schema 校验、工作区查找与 service 调用；**不得在 route 内运行 Agent、扫描大文件或执行转换**。

#### 4.11.2 状态机

**FR-AGT-13**（P0）：Case 主状态枚举与可执行性、角标计数规则如下。

| 状态 | 含义 | 可执行 | 计入红色角标 |
| --- | --- | --- | --- |
| `CREATED` | 已建立，等待 Worker | 是 | 否 |
| `ANALYZING` | Agent 1 分析或复盘中 | 是 | 否 |
| `STRATEGY_READY` | 已生成可执行策略 | 是 | 否 |
| `BUILDING` | Agent 2 生成候选实现中 | 是 | 否 |
| `VERIFYING` | 确定性验证节点运行中 | 是 | 否 |
| `NEEDS_USER` | 等待用户回答或确认 | 否 | **是** |
| `ACCEPTANCE_CHECK` | 验证通过，提交暂存结果为持久数据集 | 是 | 否 |
| `READY_FOR_REVIEW` | 技术门禁通过，等待人工接纳 | 否 | 否（独立 `REVIEW_REQUIRED` 通知） |
| `SUCCESS` | 当前数据集已成功导入 | 否 | 否 |
| `FAILED` | 不可恢复的系统或安全失败 | 否 | 否（独立 `FAILED` 通知） |
| `STOPPING` | 收到停止请求，等待安全点 | 仅清理 | 否 |
| `STOPPED` | 已停止 | 否 | 否 |

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| FR-AGT-14 | 初始配额：`interaction_mode=autonomous`、`autonomous_attempt_limit=3`、`autonomous_attempt_used=0`、`guided_attempt_no=0` | P0 |
| FR-AGT-15 | 每次自主验证失败先 `autonomous_attempt_used += 1`，再路由：`< 3` 自动进入下一轮，`== 3` 必须进入 `NEEDS_USER` | P0 |
| FR-AGT-16 | 用户回答时：断言状态为 `NEEDS_USER`，然后 `context_revision += 1`、`interaction_mode = guided`、`guided_attempt_no += 1`、状态置 `ANALYZING` | P0 |
| FR-AGT-17 | guided 轮失败后立即回到 `NEEDS_USER`，**不恢复**自主配额，且须基于新失败证据生成新的具体问题 | P0 |
| FR-AGT-18 | 验证通过必须先经 `ACCEPTANCE_CHECK` 完成持久化提交（**不重跑验证**），提交成功才进入 `SUCCESS` 或 `READY_FOR_REVIEW`；提交失败按状态图回落 | P0 |
| FR-AGT-19 | 任一可执行状态均可因用户停止转入 `STOPPING`，最终只进入 `STOPPED` 或明确的停止失败状态 | P0 |
| FR-AGT-20 | 一次自主尝试包含 7 个固定步骤：策略生成/修订 → 候选代码生成 → 代码范围检查 → `.zp` 测试与样本转换 → 深度验证 → Viewer 暂存导入与契约检查 → 基于确定性报告生成下一步说明 | P0 |

#### 4.11.3 工作流编排

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| FR-AGT-21 | 使用显式 `StateGraph`，**不使用自由运行的通用 supervisor 循环** | P0 |
| FR-AGT-22 | 图状态字段限定为：`case_id`、`workspace_id`、`source_mode`、`source_root_ref`、`dataset_fingerprint`、`selected_analysis_type`、`user_hint`、`status`、`interaction_mode`、三个计数、四个产物 id、`pending_question_id`、`last_error_code`、`stop_requested` | P0 |
| FR-AGT-23 | 图状态**禁止**存入：完整 RAW/mzML/Parquet/PFMB/`.zp` 内容、完整仓库快照、超大 stdout/stderr、连接串、API key、`.env` | P0 |
| FR-AGT-24 | 节点序列：`claim_case` → `assemble_context` → `analyze_source` → `validate_strategy` → `build_candidate` → `inspect_diff` → `run_binary_tests` → `convert_sample` → `deep_validate_zp` → `staging_import` → `verify_viewer_contract` → `review_evidence` → `route_after_verification` → `interrupt_for_user`/`acceptance`/`success` | P0 |
| FR-AGT-25 | 节点副作用要求：同输入重复执行结果可识别、写文件用 Case 专属路径、数据库写入带 `case_id + operation_id` 幂等键、中断前的副作用须已提交且可重放检查、节点只返回小型可序列化状态 | P0 |
| FR-AGT-26 | LangGraph 只负责节点顺序与条件分支、保存状态、中断等待、从检查点恢复、记录节点输出；**不负责**上传大文件、指纹计算、写 universal schema、写 `.zp`、判断科学有效性、执行未受控命令 | P0 |
| FR-AGT-27 | checkpoint 与业务表职责分离：checkpoint 用于恢复执行，业务表用于查询、审计与 UI | P0 |

#### 4.11.4 并发与幂等

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| FR-AGT-28 | 用户提交回答须携带 `If-Match: "<case.version>"` 与 `Idempotency-Key`；服务端仅在「状态为 `NEEDS_USER`」「版本一致」「问题 id 一致」「幂等键未使用」四条同时满足时接受 | P0 |
| FR-AGT-29 | 版本冲突返回 `409 AGENT_CASE_VERSION_CONFLICT` | P0 |
| FR-AGT-30 | Worker 领取 Case 使用 `SELECT ... FOR UPDATE SKIP LOCKED` + 更新租约与版本，运行期周期续租 | P0 |
| FR-AGT-31 | 租约到期后其他 Worker 可从检查点恢复，但**必须先检查当前尝试是否已有完成产物**，避免重复副作用 | P0 |
| FR-AGT-32 | 同一 Case 的 `sequence_no` 严格递增且无重复 | P0 |
| FR-AGT-33 | 第一阶段不要求 Redis；Worker 通过数据库租约领取任务，不使用 FastAPI 后台线程承担长任务 | P1 |

#### 4.11.5 上下文管理

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| FR-AGT-34 | 上下文分层：原始文件 → 产物（清单/样本/日志/哈希）→ 结构化事实 → Case 摘要 → 节点 Prompt；**原始文件不进入模型** | P0 |
| FR-AGT-35 | 每轮只注入：上一轮失败摘要、最小必要日志片段、修改过的文件差异、当前确定性验证结果、最新用户回答 | P0 |
| FR-AGT-36 | **禁止**每轮原样重放完整历史对话；每次验证结束生成新的结构化摘要，旧日志按产物 id 按需读取 | P0 |
| FR-AGT-37 | 文件抽样工具须为窄接口：`list_manifest`、`read_text_sample`、`inspect_tabular_schema`、`inspect_xml_tags`、`inspect_mzml_metadata`、`inspect_binary_header` | P0 |
| FR-AGT-38 | 抽样规则：路径必须在 Case `source_root` 内、不跟随符号链接与 junction、默认不读完整大文件、返回内容须标注截断状态/字节范围/文件哈希、**pickle 等不安全格式不得直接反序列化** | P0 |

#### 4.11.6 Agent 输出契约

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| FR-AGT-39 | Agent 1 必须输出结构化 `ImportStrategy`（不能只输出说明文字），必需字段：`schema_version`、`case_id`、`context_revision`、`proposed_source_type`、`evidence`、`source_roles`、`scientific_mapping`、`reuse_plan`、`required_changes`、`format_decision`、`unknowns`、`user_questions` | P0 |
| FR-AGT-40 | `format_decision` 取值：`NO_FORMAT_CHANGE` / `EXTENSION_ONLY` / `FORMAT_REVIEW_REQUIRED` | P0 |
| FR-AGT-41 | 策略拒绝条件（不得进入 Agent 2）：角色基数不明确、RT/m/z/charge 等关键单位无法确定、文件关联无证据、需从不受信 pickle 反序列化、需丢弃未知列或数组、用户选择与文件证据冲突且无法解释、需改核心 block 但无 `FORMAT_REVIEW_REQUIRED`、计划绕过 `ZpWriter` 或验证器 | P0 |
| FR-AGT-42 | Agent 2 必须输出 `CandidateImplementation`：`base_repo_commit`、`changed_files`、`forbidden_files_changed`、`new_source_type`、`new_step_names`、`format_change`、`test_commands`、`artifacts` | P0 |
| FR-AGT-43 | 确定性差异检查须验证：改动全在允许路径、无 `.env`/密钥/数据库文件/原始数据、未修改源数据、未新增第二个 Writer、未在 Runner/Registry 加业务判断、未把 Viewer 依赖引入 `viewer-two`、未删除或跳过验证器、未改动基线 commit 以外的未跟踪文件 | P0 |

#### 4.11.7 验证门禁

**FR-AGT-44**（P0）：验证节点**不是 Agent**，执行固定 9 项检查——候选差异范围检查、`.zp` 二进制层测试、输入副本转换、`validate_zp(mode="deep")`、输入身份前后对比、目标文件原子提交检查、Viewer 临时数据集入库、Viewer 关键 API DTO 检查、至少一个适用可视化页面的数据可用性检查。最终结论由这些门禁决定，**不由 Agent 1 的自然语言结论决定**。

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| FR-AGT-45 | 深度验证是硬门禁：`validate_zp(path, mode="deep")` 须返回 valid，并生成可关联的证书，记录 `.zp` 的 SHA-256、格式版本、大小与验证耗时，保留验证问题的稳定错误码 | P0 |
| FR-AGT-46 | 原子性：源文件始终只读、目标文件不得已存在、转换写 Case 内临时文件、完整验证后才提交、失败只清理 Case 自有临时文件、不得覆盖源/正式 `.zp`/其他 Case 产物 | P0 |
| FR-AGT-47 | 「转换成功」只表示生成候选文件，**不表示导入成功**；至少完成深度验证与暂存导入后才能进入验收 | P0 |

#### 4.11.8 沙箱与权限

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| FR-AGT-48 | Case 目录结构固定：`.viewer-agent/cases/{case_id}/` 下 `source-view/`（只读源视图）、`repo/`（固定 commit 的临时 worktree）、`work/{intermediate,logs}/`、`output/{candidate.zp,validation-certificate.json}`、`artifacts/{strategy,candidate,patch,verification}` | P0 |
| FR-AGT-49 | 权限矩阵：`source-view` 只读；`repo`/`work`/`output`/`artifacts` 仅当前 Case 可写；Viewer 正式仓库只读；`viewer-two` 开发工作区只读且不作为运行基线；正式数据库 Agent 2 **无连接权限**；暂存库只通过受控验证工具访问；网络默认关闭 | P0 |
| FR-AGT-50 | 命令白名单：第一阶段只允许模板化命令（受控 pytest 路径、受控检查脚本）。禁止任意 shell 字符串拼接、`shell=True`、动态装包、git push/remote/凭据读取、任意数据库 CLI、Case 根目录外写路径、删除仓库根/用户目录/数据根/共享上传目录 | P0 |
| FR-AGT-51 | 候选代码基线必须是人工批准的完整 commit SHA，在临时 worktree 中工作；每个 Case 记录 `base_repo_commit`；Agent 不得修改 `ZP_BINARY_*` 配置 | P0 |

#### 4.11.9 错误分类

**FR-AGT-52**（P0）：错误码须分四类，且**基础设施类不计入 3 次科学修复轮次**。

| 类别 | 错误码 | 路由 |
| --- | --- | --- |
| 用户可补充 | `SOURCE_ROLE_UNKNOWN`、`UNIT_AMBIGUOUS`、`RUN_ASSOCIATION_AMBIGUOUS`、`MISSING_REQUIRED_COMPANION_FILE`、`SCIENTIFIC_SEMANTIC_UNKNOWN` | 进入 `NEEDS_USER` |
| Agent 可自主修复 | `ADAPTER_FIELD_MAPPING_FAILED`、`SCHEMA_VALIDATION_FAILED`、`REFERENCE_INTEGRITY_FAILED`、`TEST_EXPECTATION_MISMATCH`、`VIEWER_STAGING_MAPPING_FAILED` | 自主阶段可继续下一轮 |
| 必须人工工程评审 | `FORMAT_REVIEW_REQUIRED`、`VALIDATOR_CHANGE_REQUESTED`、`CORE_BLOCK_CHANGE_REQUIRED`、`DEFAULT_VERSION_CHANGE_REQUIRED`、`NEW_BINARY_ENCODING_REQUIRED` | 停止自动轮次 |
| 基础设施 | `MODEL_PROVIDER_UNAVAILABLE`、`WORKER_LEASE_LOST`、`DATABASE_UNAVAILABLE`、`SANDBOX_START_FAILED`、`DISK_SPACE_LOW` | 不计入科学轮次 |

**FR-AGT-53**（P1）：源数据在处理期间被修改时返回 `SOURCE_CHANGED` 并停止，不得继续。

#### 4.11.10 通知语义

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| FR-AGT-54 | 仅三种情况产生红色角标：3 轮自主失败需回答、guided 单轮失败需再次回答、Agent 发现科学语义无法安全推断需确认 | P0 |
| FR-AGT-55 | 普通状态变化（分析中、生成中、测试中、导入中、成功）不计数 | P0 |
| FR-AGT-56 | 解除通知须在**同一事务**内完成 5 步：接受回答 → 旧 `NEEDS_USER` 置 inactive → Case 进入 `ANALYZING` → 创建 guided attempt → `context_revision` 与 `version` 递增 | P0 |
| FR-AGT-57 | 仅打开抽屉**不解除**通知 | P1 |
| FR-AGT-58 | Case 停止后活跃通知须解除 | P1 |

#### 4.11.11 停止语义

**FR-AGT-59**（P0）：停止流程为 8 步——设置 `stop_requested_at` → 进入 `STOPPING` → Worker 在安全点检查标志 → 终止后续节点 → 只清理 Case 自有临时文件 → 保留消息/策略/验证摘要/审计记录 → **不删除本地模式源文件** → 服务器上传文件的清理由既有上传所有权规则决定，不得仅按 Case 路径删除。

**FR-AGT-60**（P0）：不得用强制杀线程模拟可靠停止；运行中的外部转换器须有独立进程句柄、超时与终止策略。

#### 4.11.12 故障恢复

**FR-AGT-61**（P0）：故障恢复矩阵如下，其中「模型服务不可用」与「转换策略错误」必须分开计数。

| 故障 | 恢复方式 |
| --- | --- |
| 浏览器关闭 | Case 不受影响，重新查询服务器 |
| FastAPI 重启 | Worker 与检查点独立，API 恢复后查询 |
| Worker 崩溃 | 租约到期后从检查点恢复 |
| 模型请求失败 | 当前节点有限重试，**不消耗科学修复轮次** |
| Agent 输出 JSON 无效 | 同节点格式修复，超限记基础设施失败 |
| 转换进程超时 | 记稳定错误码，清理自有临时文件 |
| 验证失败 | 计入一次科学修复尝试 |
| PostgreSQL 暂时不可用 | 不继续产生副作用，恢复后重领 Case |
| 源数据被修改 | 停止并返回 `SOURCE_CHANGED` |

#### 4.11.13 Viewer `.zp` 接入模块

| 编号 | 需求 | 建议位置 | 优先级 |
| --- | --- | --- | --- |
| FR-AGT-62 | `ZpImportAdapter`：打开已通过深度验证的 `.zp`、通过 version-neutral 逻辑 API 读取、判定数据集模式、写入 universal schema、保存 `.zp` 产物元数据、支持暂存与正式两种目标 | `back/app/ingest/zp/{adapter,contracts,validation}.py` + `mappings/{top_down,bottom_up,spectra_only}.py` | P0 |
| FR-AGT-63 | TD / BU / 仅谱图三种映射保持**独立模块**，不得塞进一个巨大函数 | 同上 | P0 |
| FR-AGT-64 | `ZpImportAdapter` 禁止解析 `.zp` 私有字节布局、禁止调用 Writer、禁止修改 `.zp` 内容、禁止把业务映射塞进 API route | 同上 | P0 |
| FR-AGT-65 | `ZpSpectrumReaderService`：按 dataset/run metadata 定位 `.zp`、用公开 Reader API 读目标数组、转换为 Viewer 现有谱图 DTO、对物理版本透明、缓存目录或轻量索引（**不跨 Reader 实例缓存全部峰数组**）、校验文件身份变化与版本支持 | `back/app/spectrum_zp/{locator,reader_service,cache,contracts}.py` | P0 |
| FR-AGT-66 | 数据集元数据须记录 `spectra_source="zp"` 与 `zp` 子对象（`artifact_path`、`format_version`、`sha256`、`validation_mode`、`validation_certificate`、`binary_layer_commit`、`source_profile`）；**前端不得收到磁盘绝对路径** | — | P0 |
| FR-AGT-67 | 依赖方向单向：Viewer 依赖 `zp-binary-layer` 公开 API；`zp-binary-layer` **不得**依赖 Viewer、FastAPI、SQLAlchemy、前端或数据库 | — | P0 |
| FR-AGT-68 | 可视化复用优先匹配现有 DTO；只有现有 DTO 无法表达已确认的新科学语义时才设计新 API 与新组件，**不得因来源改为 `.zp` 就复制一套图表** | — | P0 |

---

## 5. 前端界面需求

### 5.1 路由规格

| 编号 | 路由 | 守卫 | 页面 | 优先级 | 状态 |
| --- | --- | --- | --- | --- | --- |
| UI-01 | `/` | — | 重定向到 `/datasets` | P0 | [已实现] |
| UI-02 | `/datasets` | — | `DatasetsPage` | P0 | [已实现] |
| UI-03 | `/datasets/:slug` | `DatasetModeGate` | 按模式分流 | P0 | [已实现] |
| UI-04 | `/datasets/:slug`（TD 索引） | — | `DatasetPage`（cutoff 卡片） | P0 | [已实现] |
| UI-05 | `/datasets/:slug`（BU 索引） | `BuModeOnly` | `BuOverviewPage` | P0 | [已实现] |
| UI-06 | `/datasets/:slug`（仅谱图索引） | — | `SpectraOnlyPage` | P1 | [已实现] |
| UI-07 | `/datasets/:slug/:cutoff/proteins` | `TdCutoffModeGate` | `ProteinsPage` | P0 | [已实现] |
| UI-08 | `/datasets/:slug/:cutoff/proteins/:proteinId` | `TdCutoffModeGate` | `ProteinDetailPage` | P0 | [已实现] |
| UI-09 | `/datasets/:slug/:cutoff/proteoforms` | `TdCutoffModeGate` | `ProteoformsPage` | P0 | [已实现] |
| UI-10 | `/datasets/:slug/:cutoff/proteoforms/:proteoformId` | `TdCutoffModeGate` | `ProteoformDetailPage` | P0 | [已实现] |
| UI-11 | `/datasets/:slug/:cutoff/prsms` | `TdCutoffModeGate` | `PrsmsPage` | P0 | [已实现] |
| UI-12 | `/datasets/:slug/:cutoff/prsms/:prsmId` | `TdCutoffModeGate` | `PrsmDetailPage` | P0 | [已实现] |
| UI-13 | `/datasets/:slug/proteins` | `BuModeOnly` | `BuProteinsPage` | P0 | [已实现] |
| UI-14 | `/datasets/:slug/proteins/:proteinId` | `BuModeOnly` | `BuProteinDetailPage` | P0 | [已实现] |
| UI-15 | `/datasets/:slug/peptides` | `BuModeOnly` | `BuPeptidesPage` | P0 | [已实现] |
| UI-16 | `/datasets/:slug/peptides/:peptideId` | `BuModeOnly` | `BuPeptideDetailPage` | P0 | [已实现] |
| UI-17 | `/datasets/:slug/matches` | `BuModeOnly` | `BuMatchesPage` | P0 | [已实现] |
| UI-18 | `/datasets/:slug/matches/:matchId` | `BuModeOnly` | `BuMatchDetailPage` | P0 | [已实现] |
| UI-19 | `*` | — | 重定向到 `/datasets` | P1 | [已实现] |
| UI-20 | `/agent-import-cases/:caseId` | — | Agent Case 页 | P0 | **[规划中]** |

### 5.2 模式守卫与能力门控

| 编号 | 需求 | 优先级 | 状态 |
| --- | --- | --- | --- |
| UI-21 | `DatasetModeGate` 按 `analysis_mode` 与仅谱图判定分流；BU 走 `BuDatasetLayout` + 嵌套页，仅谱图走 `SpectraOnlyPage`，其余在索引路由渲染 `DatasetPage` 并把子路径重定向回数据集首页 | P0 | [已实现] |
| UI-22 | `TdCutoffModeGate` 把 BU 与仅谱图数据集从 TD 的 cutoff 路由重定向出去 | P0 | [已实现] |
| UI-23 | `BuModeOnly` 把非 BU 数据集重定向到 `/datasets/:slug` | P0 | [已实现] |
| UI-24 | PrSM 详情页按 `capabilities.spectra_source` 选择谱图取数方式：`topfd_js` 用 spec id，`mzml_memory` 用 scan number | P0 | [已实现] |
| UI-25 | BU match 详情页按 `capabilities.has_ms2_pfmb` 决定是否渲染 PFMB 区块 | P1 | [已实现] |
| UI-26 | BU 页面按 `run.raw_format` 门控：`mzml` 启用 XIC/MS1/MS2，`bruker_d` 启用 DIA 窗口图与迁移率切片 | P1 | [已实现] |
| UI-27 | DIA-CLIP 来源须有独立的呈现标识 | P1 | [已实现] |

### 5.3 交互与状态呈现

| 编号 | 需求 | 优先级 | 状态 |
| --- | --- | --- | --- |
| UI-28 | 统一的加载态、错误态、空态组件；图表另有独立的加载/错误/空/不支持四态 | P0 | [已实现] |
| UI-29 | 图表渲染异常须由错误边界捕获，不得白屏整页 | P0 | [已实现] |
| UI-30 | 图表查询在 `404`/`409`/`422` 上**不重试** | P1 | [已实现] |
| UI-31 | 全局页面切换遮罩须等到路由数据与图表首帧就绪后才解除，安全超时 45 秒 | P1 | [已实现] |
| UI-32 | BU 列表过滤条件写入 URL 查询参数，链接可分享复现 | P1 | [已实现] |
| UI-33 | 支持浅色/深色/跟随系统三态主题，持久化到本地存储；图表配色须随主题切换 | P1 | [已实现] |
| UI-34 | 进行中的上传/导入任务引用持久化到本地存储，刷新后可恢复跟踪 | P1 | [已实现] |
| UI-35 | 谱图支持纵轴百分比/绝对值切换、滚轮缩放、框选缩放、全屏模态与重置缩放 | P0 | [已实现] |
| UI-36 | 产物离子选择上限 8 条，超出须阻止并提示 | P1 | [已实现] |
| UI-37 | 派生数据缺失导致的 `409` 须在 UI 上展示可执行的补齐命令 | P1 | [已实现] |
| UI-38 | 左上角常驻信息按钮 + 通知抽屉；红色角标仅统计待回答 Case | P0 | **[规划中]** |
| UI-39 | 界面须显示「共享工作区」，不得显示任何用户名 | P0 | **[规划中]** |
| UI-40 | 导入类型选择中新增 `Unknown / Other` 与一行说明输入 | P0 | **[规划中]** |

### 5.4 前端约定与技术债

| 编号 | 说明 |
| --- | --- |
| UI-41 | 界面文案以英文为主，代码注释中英混排；**未引入 i18n 框架**，`index.html` 的 `lang="en"` |
| UI-42 | 服务端状态统一走 TanStack Query（`staleTime` 30 秒、重试 1 次、失焦不重取）；无全局客户端状态库在用 |
| UI-43 | `zustand`、`@tanstack/react-table`、`@tanstack/react-virtual` 已声明依赖但**代码中未使用** |
| UI-44 | `features/bu-viewer/` 是 `features/bu/` 的镜像副本且**未挂载到路由**；须确定权威副本（PRD Q6） |
| UI-45 | 表格为手写实现或 `BuDataTable`，未使用 TanStack Table；图表为自研 d3 + three，未引入 Plotly/ECharts |
| UI-46 | `git diff front/src/features/prsm` 须保持为空——BU 开发不得改动 TD 的 PrSM 图表（锁定约束） |

---

## 6. 外部接口需求

| 编号 | 外部系统 | 接口形式 | 约束 | 状态 |
| --- | --- | --- | --- | --- |
| EIF-01 | PostgreSQL 14+ | SQLAlchemy + psycopg | 非 SQLite 时连接池 `pool_size=10`、`max_overflow=20`；读路径 raw SQL | [已实现] |
| EIF-02 | ThermoRawFileParser 1.4.5 | 子进程 CLI | 只支持 Thermo RAW；输出须为索引化非压缩 mzML；超时可配置 | [已实现] |
| EIF-03 | PFMB Bridge（v1 / v2） | 子进程可执行文件 | 可通过预置 v2 参考侧车根目录绕过生成；可禁用 numba JIT | [已实现] |
| EIF-04 | UniProt | HTTP 取 FASTA | 默认**关闭**（`BU_UNIPROT_ENABLED=false`）；离线时序列覆盖降级 | [已实现] |
| EIF-05 | Bruker TDF | 可选依赖 `tdfpy` | 未安装时相关功能须优雅降级 | [已实现] |
| EIF-06 | `zp-binary-layer` | Python 公开 API：`inspect_source`、`convert_source_to_zp`、`validate_zp`、`open_zp` | 单向依赖；不得触碰私有字节布局；须绑定批准的 commit 与格式版本 | **[规划中]** |
| EIF-07 | LLM 服务商 | HTTP | 由编排层调用，**不把通用网络能力交给代码沙箱**；不可用时记基础设施错误 | **[规划中]** |
| EIF-08 | LangGraph PostgreSQL Checkpointer | 库调用 | 使用独立表或 schema，与业务表分离 | **[规划中]** |

**EIF-06 的强制边界**（来自 `.zp` 层架构约束，共 10 条）：`BaseBlockTool` 只能创建/更新 typed block 且不能写 `.zp`、不能设输出路径、不能调验证器；`PipelineRunner` 不得按 source type / MS level / 鉴定类型分支；`StepRegistry` 只注册与查找，不选择计划；`ZpWriter` 是唯一允许写最终 `.zp` 的生产组件；Writer 不得修补缺失的 block/index/string pool/引用；v1 冻结格式不得被静默重新解释；核心 block 字段变化必须进入版本评审；验证器不得为通过测试而放宽。

---

## 7. 非功能需求

### 7.1 性能

| 编号 | 指标 | 目标 | 验证方式 | 状态 |
| --- | --- | --- | --- | --- |
| NFR-PERF-01 | 指纹计算墙钟时间 | 基准数据集 `MZ20160222DS_histone49_html` ≤ **0.5 秒** | `cs/指纹性能测验.py` | [已实现] |
| NFR-PERF-02 | LC-MS 三维数据接口 | ≤ **0.5 秒** | `cs/LCMS三维验收说明.md` | [已实现] |
| NFR-PERF-03 | 列表分页 | 单页 ≤ 500 条 | 接口参数约束 | [已实现] |
| NFR-PERF-04 | 扫描索引分页 | 单页 ≤ 2000 条 | 接口参数约束 | [已实现] |
| NFR-PERF-05 | 色谱图点数 | 降采样 ≤ 8000 点 | 接口实现 | [已实现] |
| NFR-PERF-06 | BU 列表查询 | 须命中 `idx_im_dataset_q` / `idx_im_dataset_run` 索引扫描 | `budocs/验收测试矩阵.md` | [已实现] |
| NFR-PERF-07 | 单张 mzML 谱图读取 | 使用字节索引，不全文件迭代 | `back/tests/test_mzml_scan_reader.py` | [已实现] |
| NFR-PERF-08 | 单 Case 模型成本 | 建立基线后设上限 | 待补埋点 | [规划中] |

### 7.2 容量

| 编号 | 指标 | 值 | 状态 |
| --- | --- | --- | --- |
| NFR-CAP-01 | 全局谱图内存预算 | 默认 6 GiB，下限 64 MiB，可配置 | [已实现] |
| NFR-CAP-02 | TopFD JS 谱图缓存 | 默认 256 条 | [已实现] |
| NFR-CAP-03 | 上传会话文件数 | ≤ 5000 | [已实现] |
| NFR-CAP-04 | 上传写入缓冲 | 8 MiB | [已实现] |
| NFR-CAP-05 | 磁盘保留阈值 | 5 GiB | [已实现] |
| NFR-CAP-06 | 单数据集匹配量 | 已验证约 110,026 条（DIA-NN 基准） | [已实现] |
| NFR-CAP-07 | PFMB 记录量 | 已验证 834,455 条（每 RT 槽一条，**不是每前体一条**） | [已实现] |
| NFR-CAP-08 | 大二进制产物 | **不得存入 PostgreSQL**，只存元数据与哈希 | [规划中]（Agent） |

### 7.3 可靠性

| 编号 | 需求 | 状态 |
| --- | --- | --- |
| NFR-REL-01 | 导入任务失败不得留下半成品数据集可见于列表 | [已实现] |
| NFR-REL-02 | 派生数据生成失败以警告记录，不回滚已成功的导入 | [已实现] |
| NFR-REL-03 | 僵死任务须有超时判定（排队 15 分钟 / 运行 120 分钟）且不阻塞删除 | [已实现] |
| NFR-REL-04 | 数据目录搬迁后陈旧绝对路径须可修正 | [已实现] |
| NFR-REL-05 | Agent Case 在浏览器关闭、API 重启、Worker 崩溃后均可恢复 | [规划中] |
| NFR-REL-06 | 暂存数据集失败时清理暂存库记录，**不删除源文件** | [规划中] |

### 7.4 安全

| 编号 | 需求 | 状态 |
| --- | --- | --- |
| NFR-SEC-01 | 上传路径拒绝 `..`、绝对路径、URL 编码绕过、盘符根；落盘目标须通过相对性校验 | [已实现] |
| NFR-SEC-02 | 拒绝上传树中的符号链接与 junction | [已实现] |
| NFR-SEC-03 | 上传存储严格限制在 `DATA_ROOT/{IMPORT_UPLOAD_DIR_NAME}` 下 | [已实现] |
| NFR-SEC-04 | 原生文件夹对话框默认仅 localhost；禁用或非本机时返回 `403` | [已实现] |
| NFR-SEC-05 | `VIEWER_ENV=test` 时：不加载 `.env`、强制临时 `DATA_ROOT` 与临时库、**拒绝连接生产库名**（`Universal_Viewer`） | [已实现] |
| NFR-SEC-06 | 删除数据集只允许影响数据库；不得删除 `DATA_ROOT` 之外的任何路径 | [已实现] |
| NFR-SEC-07 | 前端不得收到磁盘绝对路径（`.zp` 与 Case 引用均用受控相对引用） | [规划中] |
| NFR-SEC-08 | Agent 沙箱权限与命令白名单（见 FR-AGT-48~51） | [规划中] |
| NFR-SEC-09 | **系统当前无鉴权**：可保证 Case 数据不互相污染、消息顺序一致、提交幂等、单写、任务不丢；**不能保证**用户间不可见、已读状态按人区分、操作可追责、费用可归属 | 明确声明 |

### 7.5 兼容性

| 编号 | 需求 | 状态 |
| --- | --- | --- |
| NFR-COMP-01 | 前端浏览器目标：现代 Chromium（E2E 仅覆盖 Chromium） | [已实现] |
| NFR-COMP-02 | 数据集目录跨机器/盘符搬迁后仍可读谱图（`source_root` → `DATA_ROOT` 回退） | [已实现] |
| NFR-COMP-03 | 前端 API 语义须保持稳定：前端只消费统一形状（dataset / protein / proteoform / prsm / spectrum），不理解原始格式差异 | [已实现] |
| NFR-COMP-04 | cutoff 合成 id（1/2）为前端依赖的稳定契约，不得变更 | [已实现] |
| NFR-COMP-05 | PFMB v2 的 JSON 头须仍可读 | [已实现] |
| NFR-COMP-06 | `.zp` 须对 v1/v2/v3 物理版本对上层透明；不支持的版本须明确失败 | [规划中] |

### 7.6 可维护性

| 编号 | 需求 | 状态 |
| --- | --- | --- |
| NFR-MNT-01 | 指纹、根路径解析、导入编排三者为独立模块，仅通过窄接口协作；编排层禁止内联算法实现 | [已实现] |
| NFR-MNT-02 | 后端 lint 使用 Ruff（行宽 120、目标 py312） | [已实现] |
| NFR-MNT-03 | 数据库迁移使用 `back/migrations/*.sql` 手工脚本，不使用 Alembic | [已实现] |
| NFR-MNT-04 | BU 模块须保持 router 无 SQL、service 层承载查询的分层 | [已实现] |
| NFR-MNT-05 | 性能与基准脚本置于 `cs/`，优先中文文件名，通过调用模块公开 API 实现，不得复制算法 | [已实现] |
| NFR-MNT-06 | API 错误响应 `detail` 格式**当前不统一**，属已知技术债 | [部分实现] |
| NFR-MNT-07 | 无生产部署方案（容器化/反向代理/监控） | [规划中] |

---

## 8. 约束与假设

### 8.1 强制约束

| # | 约束 | 来源 |
| --- | --- | --- |
| C1 | `docs/universal_schema.sql` 是数据库唯一真值 | 项目说明文档 |
| C2 | 读路径使用 raw SQL，不使用 ORM 映射 | 现有实现 |
| C3 | 指纹为元数据 manifest 的 MD5，不是全文件内容哈希；列注释须说明以免混淆 | `AGENTS.md` |
| C4 | 主业务代码禁止写死本机盘符 | `AGENTS.md` |
| C5 | BU 的 19 条锁定决策（D1–D19）未经版本升级不得重开 | `budocs/决策登记表.md` |
| C6 | `git diff front/src/features/prsm` 须为空 | `budocs/P0-Viewer代码改造规划.md` |
| C7 | `.zp` 的 10 条架构边界不可突破 | [ZP转换接入与安全边界.md](ZP转换接入与安全边界.md) |
| C8 | Agent 轮次规则由确定性状态机硬编码，模型不得自行变更 | [Agent状态机与上下文设计.md](Agent状态机与上下文设计.md) |

### 8.2 假设

| # | 假设 | 风险 |
| --- | --- | --- |
| A1 | 元数据指纹足以区分数据集（同名同大小同时间的不同内容视为同一数据集） | 极端情况下可能漏判，实际使用中未出现 |
| A2 | mzML 为索引化非压缩格式 | gzip 输入会被拒绝 |
| A3 | 部署为单机/私有环境，同时活跃用户数少 | 无鉴权在公网暴露会有严重后果 |
| A4 | `viewer-two` 能提供一个稳定的 clean commit | 当前工作目录有未提交 v3 改动，是 Agent 的前置阻塞项 |
| A5 | 模型能在 3 轮内解决多数常见陌生格式 | 未经验证，需建立首个成功率基线 |

---

## 9. 需求到测试的追溯

### 9.1 后端测试映射（52 个 `test_*.py`，另有 `conftest.py` 与 `postgres_support.py`）

| 需求域 | 主要测试文件 |
| --- | --- |
| FR-DS | `test_datasets_api_modes.py`、`test_dataset_delete_cancel_import.py` |
| FR-IMP | `test_import_jobs_layout.py`、`test_import_jobs_raw_conversion.py`、`test_import_jobs_derived_data.py`、`test_import_selection.py` |
| FR-UPL | `test_import_uploads.py`（42 项） |
| FR-ING-01 | `test_dataset_ingest_root.py` |
| FR-ING-02~04 | `test_dataset_metadata_fingerprint.py` |
| FR-ING-05~07 | `test_import_planner.py`、`test_import_planner_raw.py` |
| FR-ING-10 | `test_toppic_native_output.py` |
| FR-ING-11~12 | `test_bu_diaclip_adapter.py`、`test_bu_diaclip_result_reader.py`、`test_bu_diann_parquet_reader.py`、`test_bu_field_mapping.py` |
| FR-ING-13 | `test_mzml_only_adapter.py` |
| FR-ING-14 | `test_raw_mzml_mapping.py` |
| FR-ING-15 | `test_raw_conversion_discovery.py`、`test_raw_conversion_thermo.py`、`test_raw_converter_discovery.py` |
| FR-ING-16 | `test_backfill_dataset_derived_data.py` |
| FR-ING-17 | `test_pfmb_sidecar_prepare.py`、`test_pfmb_v2_reference.py` |
| FR-ING-18 | `test_incoming_path_relocate.py` |
| FR-TD | `test_prsm_files.py`（**路由级覆盖不足，见 §9.3**） |
| FR-MZ | `test_mzml_spectra_api.py`、`test_mzml_scan_index.py`（22 项）、`test_mzml_scan_reader.py`、`test_chromatogram_route_matching.py` |
| FR-BU-01~08 | `test_bu_runtime_api.py`、`test_bu_rt_mz_api.py`、`test_bu_match_detail_display_fields.py`、`test_bu_peptide_mapper.py` |
| FR-BU-09~16 | `test_bu_spectrum_api.py`（29 项）、`test_bu_xic_isotopes.py`、`test_bu_product_xic_indexed.py`、`test_bu_chromatogram_summary.py`、`test_bu_tdf_reader.py` |
| FR-BU-17~19 | `test_bu_ms2_annotation.py` |
| FR-BU-26 | `test_bu_protein_sequence_resolver.py`、`test_bu_protein_sequence_backfill.py`、`test_bu_fasta_index.py` |
| FR-SPM | `test_spectrum_memory.py`（13 项） |
| NFR-SEC-05 | `test_test_environment_safety.py`、`test_postgres_environment_safety.py` |
| EIF-01 | `test_database_engine_factory.py`、`test_postgres_foundation.py`、`test_native_postgres_runner_contract.py`（26 项） |

PostgreSQL 相关测试以 `@pytest.mark.postgres` 标记，默认跳过。

### 9.2 前端测试映射（19 个 Playwright 规格）

| 需求域 | 主要规格文件 |
| --- | --- |
| UI-28~30 | `api-error.spec.ts` |
| UI-31 | `page-transition.spec.ts` |
| UI-33 | `theme.spec.ts` |
| FR-UPL / UI-34 | `import-upload-api.spec.ts`、`import-upload-page.spec.ts`、`import-upload-files.spec.ts` |
| UI-05 / FR-BU-01~02 | `bu-overview-chart-states.spec.ts` |
| UI-18 / FR-BU-08~11 | `bu-match-detail.spec.ts`、`bu-evidence-summary.spec.ts`、`bu-spectrum-label-layout.spec.ts` |
| FR-BU-10 / UI-26 | `bu-rt-linkage.spec.ts` |
| FR-BU-17~19 / UI-25 | `bu-pfmb-*.spec.ts`（4 个） |
| FR-BU-26 | `bu-protein-sequence-coverage.spec.ts` |
| UI-27 | `bu-source-presentation.spec.ts` |
| FR-BU-13 / UI-36 | `product-ion-selection.spec.ts` |
| UI-06 / FR-SO | `spectra-only-peak-annotations.spec.ts`、`spectra-only-scan-relations.spec.ts` |

### 9.3 覆盖缺口

| 缺口 | 影响的需求 | 优先级 |
| --- | --- | --- |
| Top-Down 路由级测试不足（无 `test_td_*_api.py`） | FR-TD-01~14 | P2 |
| 前端无单元测试（无 Vitest/Jest），只有 E2E | UI-* 的细粒度逻辑 | P2 |
| 无性能回归测试进 CI（`cs/` 脚本需人工执行） | NFR-PERF-01~02 | P2 |
| Agent 全部需求无测试（功能未实现） | FR-AGT-* | 随开发同步补 |

### 9.4 Agent 需求的测试要求（[规划中]）

按设计文档，Agent 实现须至少覆盖四类：

**状态机**：第 1、2 次自主失败自动继续；第 3 次必定进入 `NEEDS_USER`；用户回答后只产生一个 guided attempt；guided 失败后立即再次 `NEEDS_USER`；用户回答不重置自主次数；成功必先经 `ACCEPTANCE_CHECK`；`STOPPING` 最终只进入 `STOPPED` 或明确的停止失败态。

**并发与幂等**：两个 Worker 不能同时持有一个 Case；重复幂等键只创建一条消息；陈旧版本提交返回 409；`sequence_no` 无重复且严格递增；服务重启后检查点与业务状态一致。

**上下文**：大文件内容不进入检查点；产物路径不能逃出 Case 根；不跟随符号链接/junction；日志截断规则稳定；用户回答只进入对应 Case 与上下文版本。

**安全**：修改禁止路径在执行前失败；修改验证器进入人工评审；符号链接逃逸失败；任意 shell 参数失败；Agent 无法连接正式库；无法覆盖已有目标；无法读取 `.env` 或仓库外密钥。
