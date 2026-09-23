# P0 — Viewer 代码改造规划（最小集 · 低耦合）

> **文档版本**：v1.0  
> **日期**：2026-05-21  
> **Viewer 项目**：`E:\viewer\`  
> **数据样例**：`d:\dia-shuju\`  
> **状态**：规划稿（**只补文档，不在本仓库改代码**）  
> **定位**：将 C1–C31 任务清单收敛为**可执行、可验收、低耦合**的实施蓝图；细节仍下沉到各专项文档。

---

## 目录

1. [文档目的与范围](#1-文档目的与范围)
2. [低耦合总原则](#2-低耦合总原则)
3. [模块边界与依赖图](#3-模块边界与依赖图)
4. [任务清单 C1–C31](#4-任务清单-c1c31)
5. [实施顺序与 PR 切片](#5-实施顺序与-pr-切片)
6. [验收与硬约束](#6-验收与硬约束)
7. [专项文档索引](#7-专项文档索引)

---

## 1. 文档目的与范围

### 1.1 本文回答什么

| 问题 | 答案 |
|---|---|
| P0 要改哪些文件？ | §4 逐条映射 C1–C31 → 路径 + 改动 + 验收 |
| 怎样保证 Top-Down 不被牵连？ | §2 边界规则 + §6 硬约束（含 `features/prsm/**` diff=0） |
| 先做哪块、后做哪块？ | §5 四阶段 + PR 切片建议 |
| 字段 / API / 算法细节在哪？ | §7 链到 9 份专项文档，**本文不重复展开** |

### 1.2 P0 范围（与里程碑对齐）

```text
P0 最小可交付 = M1（导入）+ M3/M4（数据集 API + 列表/整体页骨架）+ 运行时骨架（R1–R7 模块就位）
                + 前端路由分叉与 bu 目录 scaffold（M4 前可 partial stub）

不在 P0 强交付：M5–M6 谱图细节 polish、M7 coverage、M8 .d 谱图（见决策 D10）
```

| 里程碑 | 对应 C 项 | 说明 |
|---|---|---|
| M1 导入 | C8–C16 | `d:\dia-shuju` 可路径导入，DB 行数达标 |
| M3 数据集 API | C1–C7 | `analysis_mode` / `cutoffs:[]` / `bu_runs` |
| R1–R7 运行时 | C17–C24 | `bu/` 包 + router 挂载 + wiring mixed |
| M4 前端骨架 | C25–C31 | `DatasetModeGate` + `features/bu/**` scaffold |

---

## 2. 低耦合总原则

### 2.1 分叉轴：唯一真值 `analysis_mode`

```text
                    datasets.analysis_mode
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
        TOP_DOWN                         BOTTOM_UP
    features/prsm/**                  features/bu/**
    api/v1/prsms, spectra…            api/v1/bu/*
    ingest/universal_toppic*          ingest/bu/*
```

**禁止**：用 URL 段、文件扩展名、`cutoffs.length`、slug 命名猜测模式（见 [决策登记表 D12](./决策登记表.md)）。

### 2.2 包级隔离（后端）

| 层 | Top-Down（不动） | Bottom-Up（新增） | 共用（只扩展字段） |
|---|---|---|---|
| Schema | `schemas/dataset.py` 扩展 | `schemas/bu.py` 新建 | — |
| Ingest | `ingest/universal_toppic_*` | `ingest/bu/*` | `import_jobs` 仅 +1 分支 |
| 运行时 | `spectrum_memory` 只读调用 | `bu/services/*`, `bu/tdf_reader/*` | `spectrum_memory_wiring` 扩展 mixed |
| API | `datasets.py` 扩展输出 | `api/v1/bu/*` 新建 | `GET /datasets` 共用 |

### 2.3 包级隔离（前端）

| 层 | 规则 |
|---|---|
| 路由 | `DatasetModeGate` **唯一**分叉点；TD 子树保持原挂载 |
| 组件 | BU 谱图 **抄版** 到 `features/bu/components/spectrum/**`，**不** import 改 `features/prsm` |
| API Client | `features/bu/api/buClient.ts`（或等价）；**不**改现有 TD fetch |
| 共用页 | `DatasetsPage` 只读 `analysis_mode` 做 badge，不写 BU 业务 |

### 2.4 薄层规则

| 文件类型 | 允许 | 禁止 |
|---|---|---|
| `api/v1/bu/*.py` | 参数校验、`Depends(require_bu_*)`、调 service、返回 DTO | SQL、scan 算法、parquet 解析 |
| `import_jobs.py` | `elif plan.shape == DIANN_DIA` → 调 adapter | 字段映射、batch insert 逻辑 |
| `DatasetModeGate.tsx` | 读 slug → `analysis_mode` → 选 layout | 列表列定义、谱图渲染 |
| `ingest/bu/*` | 写 DB、登记 runs | 运行时 scan 解析 |

### 2.5 共享点清单（允许「最小侵入」）

以下文件**允许扩展**，但改动须可一行说明「为 BU 分叉」且 TD 行为不变：

| 文件 | 允许改动 | 禁止 |
|---|---|---|
| `schemas/dataset.py` | `DatasetOut` 加可选字段 | 改 TD 必填语义 |
| `api/v1/datasets.py` | `_cutoffs_payload` 分支；list/detail 加字段 | 改 TD cutoff SQL |
| `api/v1/universal_compat.py` | SELECT 增列 | 改 TD 查询逻辑 |
| `dataset_ingest_root/resolver.py` | + BU 检测；互斥 | 改 TopPIC 判定 |
| `services/import_planner/*` | + `DIANN_DIA` | 改现有 shape 枚举语义 |
| `services/spectrum_memory_wiring.py` | `mixed` / `tdf_memory` | 改 topfd_js 路径 |
| `App.tsx` | 包一层 `DatasetModeGate` | 改 prsm 路由定义 |
| `api/types.ts` | 扩展 `DatasetOut` | 改 prsm 类型 |

---

## 3. 模块边界与依赖图

### 3.1 后端依赖（实施时禁止反向依赖）

```text
api/v1/bu/*  ──→  bu/deps.py  ──→  bu/services/*
                      │                    │
                      │                    ├──→ spectrum_memory（只读，mzML）
                      │                    └──→ bu/tdf_reader/*（.d）
                      │
ingest/bu/*  ──→  run_discovery（可被 tdf_reader.root_resolver import）
                      │
import_planner  ──→  resolver（只读检测）
import_jobs     ──→  ingest/bu/universal_diann_adapter（编排 only）

schemas/bu.py  ←──  api/v1/bu/* , bu/services（DTO 单向：schema 不 import service）
```

**规则**：`bu/services` **不得** import `api/v1/*`；`ingest/bu` **不得** import `bu/services`（导入期不写 scan 缓存逻辑，可选 `resolved_scan` 留运行时）。

### 3.2 前端依赖

```text
App.tsx
  └── DatasetModeGate ──→ useDataset(slug)  [共用 api/client 或 hooks]
         ├── TOP_DOWN → 现有 prsm 出口（Navigate）
         └── BOTTOM_UP → BuDatasetLayout
                ├── bu/pages/*
                ├── bu/components/*
                └── bu/api/buClient.ts  ──→  /api/v1/datasets/:slug/...
```

### 3.3 数据流（导入 vs 运行时）

```text
[一次性] POST /imports → ingest/bu → PostgreSQL（7 表）
[按需]   GET .../matches/:id/spectrum/ms2 → bu/services → mzML/.d 文件
```

两阶段 **不共享** 业务类；仅共享 `run_discovery.resolve_bruker_tdf_root()` 路径规则。

---

## 4. 任务清单 C1–C31

> **图例**：依赖列指向必须先完成的 C 项；验收列链到 [验收测试矩阵](./验收测试矩阵.md) 章节。

### 4.1 §2.1 数据库 / Schema 层

| ID | 文件 | 改动 | 依赖 | 低耦合要点 | 验收 |
|---|---|---|---|---|---|
| **C1** | `back/app/schemas/dataset.py` | `DatasetOut` 增加：`analysis_mode`, `source_software`, `extra_metadata`（至少含 `q_value_cutoff` 可读）, `bu_runs: list[BuRunSummary] \| None = None` | C2 中 `BuRunSummary` 定义 | BU 字段 **Optional**；TD 响应 omit 或 null，不破坏旧客户端 | 5.2 #1–2 |
| **C2** | `back/app/schemas/bu.py` | **新建**：API 规范全部 DTO（Overview、List、Match、Coverage 等），命名见 [BU列表与数据集API规范 §14](./BU列表与数据集API规范.md#14-pydantic-模型命名建议) | — | DTO **仅**放 `schemas/`；`bu/services` 只 import，不重复定义（D15） | 5.2 #4–5 |
| **C3** | `back/app/api/v1/universal_compat.py` | `require_dataset` SQL 增加 `analysis_mode`, `extra_metadata`, `status` | DB 列已存在 | 只扩 SELECT；不改 TD 侧 require 语义 | 5.2 #2 |
| **C4** | `docs/universal_schema.sql` + migration | **D18 必建**：R4 前 migration 创建 `idx_im_dataset_q`、`idx_im_dataset_run`（见 [导入规划 §18](./Bottom-Up数据导入规划.md#18-数据库索引必建)）；未通过 §5.2 #6 不得合 PR | M1 完成 | 索引在 migration 层；**禁止** runtime `CREATE INDEX` | 5.2 #6 |

**C1/C2 字段最小集（P0）**：

```python
# dataset.py — 示意，实施时对齐现有 BaseModel 风格
class DatasetOut(BaseModel):
    # ... 现有 TD 字段 ...
    analysis_mode: Literal["TOP_DOWN", "BOTTOM_UP"] | None = None
    source_software: str | None = None
    extra_metadata: dict[str, Any] | None = None
    bu_runs: list[BuRunSummary] | None = None  # BU 时填充；TD 为 None
```

### 4.2 §2.2 数据集 API 分叉

| ID | 文件 | 改动 | 依赖 | 低耦合要点 | 验收 |
|---|---|---|---|---|---|
| **C5** | `back/app/api/v1/datasets.py` | `_cutoffs_payload`：若 `analysis_mode == BOTTOM_UP` → 返回 **`[]`**（D12，非占位 0 计数） | C3 | 分支在 **单一函数**；TD 路径零 diff 行为 | 5.2 #2–3 |
| **C6** | `back/app/api/v1/datasets.py` | `list_datasets` / `get_dataset_detail`：输出 `analysis_mode`；BU 时附 `bu_runs`（来自 `runs` + `run_metadata`） | C1, C3, M1 | 列表 SQL **一次** JOIN runs；不在 router 拼 BU 专有逻辑 | 5.2 #1–2 |
| **C7** | `back/app/api/v1/datasets.py` | BU 数据集 `GET /datasets/{slug}` 仍可调 `ensure_mzml_dataset_resident`；wiring 支持 **`mixed`**（C20） | C16, C20 | resident 逻辑留 wiring 模块；datasets router 只触发 | 5.1 #4, 5.3 #7 |

**`bu_runs` 组装规则**（P0 契约）：

| 字段 | 来源 |
|---|---|
| `run_id` | `runs.run_id` |
| `file_name` | `runs.file_name` |
| `raw_format` | `run_metadata.raw_format`（canonical：`mzml` \| `bruker_d`） |
| `diann_run_name` | `run_metadata.diann_run_name` |

### 4.3 §2.3 导入链路（M1）

| ID | 文件 | 改动 | 依赖 | 低耦合要点 | 验收 |
|---|---|---|---|---|---|
| **C8** | `back/app/dataset_ingest_root/resolver.py` | `has_bu_diann_layout()`；`find_ingest_root` 支持 TopPIC **或** BU；**互斥检测**（同根不可双模） | — | 与 TopPIC 检测 **并列**，不嵌套改 TopPIC 函数 | 5.1 #1, #6 |
| **C9** | `back/app/services/import_planner/types.py` | `DatasetShape.DIANN_DIA` | C8 | 枚举 **追加**；不改现有 shape 值 | 5.1 #1 |
| **C10** | `back/app/services/import_planner/detectors.py` | `detect_bu_spectra_source()` → `mzml_memory` / `tdf_memory` / `mixed` | C8 | 纯检测，不写 DB | 5.1 #4 |
| **C11** | `back/app/services/import_planner/planner.py` | BU 分支 → `ImportPlan(DIANN_DIA, ...)` | C9, C10 | planner **只产出 plan** | 5.1 #1 |
| **C12** | `back/app/services/import_jobs.py` | `elif plan.shape == DIANN_DIA` → `ingest_universal_diann()` | C13 | **一行分支** + progress 回调 | 5.1 #1, #7 |
| **C13** | `back/app/ingest/bu/*` | 新建包：`universal_diann_adapter`, `diann_parquet_reader`, `field_mapping`, `run_discovery`, `stats_reader`, `protein_description_reader` | — | 算法 **全部**在此包；见 [导入规划 §13](./Bottom-Up数据导入规划.md#13-后端模块划分新增文件) | 5.1 #2–4 |
| **C14** | ingest adapter | `runs` INSERT：`analysis_mode='BOTTOM_UP'`, `software='DIA-NN_2.0'`, `status`：`IMPORTED`→`READY` | C13 | 状态机与 TD adapter 对齐 | 5.1 #2 |
| **C15** | ingest adapter | `extra_metadata` 键 **snake_case**（D14）：`q_value_cutoff`, `pg_max_lfq`, `import_stats`, … | C13 | 映射集中在 `field_mapping.py` | 5.2 #5 |
| **C16** | ingest adapter | `capabilities` 按 [导入规划 §14](./Bottom-Up数据导入规划.md#14-capabilities-与-extra_metadata-约定)；`mixed` 时 `has_im: true` | C10 | capabilities **导入时一次写入** | 5.1 #4 |

**ingest/bu 包内职责切分**：

| 模块 | 职责 | 不得 |
|---|---|---|
| `universal_diann_adapter.py` | 阶段编排、事务、progress | parquet 列解析细节 |
| `diann_parquet_reader.py` | 流式读 + Q 过滤 | SQL |
| `field_mapping.py` | 列→DB 列/extra_metadata | 文件扫描 |
| `run_discovery.py` | mzML/.d 扫描 + Bruker 下钻 | parquet |
| `stats_reader.py` | stats.tsv → extra_metadata | 鉴定行 |
| `protein_description_reader.py` | description.tsv | 肽段 |

### 4.4 §2.4 运行时后端（R1–R7）

| ID | 文件 | 改动 | 依赖 | 低耦合要点 | 验收 |
|---|---|---|---|---|---|
| **C17** | `back/app/bu/deps.py` | `require_bu_dataset`, `require_bu_match` | C3 | mode guard **集中**；router 不重复 if | 5.2 #4 |
| **C18** | `back/app/bu/services/*` | 新建：`scan_resolver`, `theoretical_fragments`, `xic_service`, `spectrum_facade`, `chromatogram_service`, `overview_service`, `lists_service`, `peptide_mapper`, `protein_sequence_resolver` | C17 | 见 [BU运行时后端模块规划 §5](./BU运行时后端模块规划.md#5-buservices-模块) | 5.3 #1–2 |
| **C19** | `back/app/bu/tdf_reader/*` | 新建：`session_cache`, `root_resolver`, `chromatogram`, `dia_windows`, `mobility_slice` | C13 `run_discovery` | P0 可先 **stub** MS2；G2/G3/G5 优先 | 5.3 #5 |
| **C20** | `back/app/services/spectrum_memory_wiring.py` | `_is_mzml_memory_dataset`：支持 `spectra_source in ('mzml_memory', 'mixed')` | C16 | mixed 时 **按 run** 决定是否走 memory | 5.3 #7 |
| **C21** | `back/app/services/import_jobs.py` | mzML 校验：`mixed` 时仍 validate **mzML** mapping | C12, C20 | 校验逻辑复用现有 mzML validator | 5.1 #4 |
| **C22** | `back/app/api/v1/bu/*` | 新建 routers：`overview`, `chromatogram`, `lists`, `matches`, `proteins` | C2, C17, C18 | URL **无** `/bu/` 前缀（D8） | 5.2 #4–5 |
| **C23** | `back/app/api/v1/__init__.py` | `include_router(bu.router)` | C22 | 聚合 router 在 `bu/__init__.py` | 5.2 #4 |
| **C24** | `back/pyproject.toml` | 增加 `tdfpy` 依赖（M8 前可先 **optional** / extra） | C19 | optional 避免 TD 部署强绑 Bruker | — |

**P0 运行时交付梯度**（与 D10 一致）：

| 模块 | P0 必须 | 可 stub 到 M5–M8 |
|---|---|---|
| `lists_service` + lists router | ✅ | — |
| `overview_service` + overview router | ✅ | `rt-mz` 可 501 |
| `chromatogram_service`（mzML TIC） | ✅ | `.d` TIC |
| `scan_resolver` + `spectrum_facade`（mzML MS2） | 🟡 骨架 + 单测 | `.d` MS2 |
| `xic_service` | 🟡 M5 | — |
| `tdf_reader` | 🟡 G5 dia-windows | mobility MS2 |

### 4.5 §2.5 前端（M3–M7）

| ID | 文件 | 改动 | 依赖 | 低耦合要点 | 验收 |
|---|---|---|---|---|---|
| **C25** | `front/src/App.tsx` | `/datasets/:slug` → `DatasetModeGate`；BU 子路由 proteins/peptides/matches/… | C6 | **不**改 prsm 子树定义 | 5.5 #1–2 |
| **C26** | `front/src/features/bu/**` | 按 [BU前端接入规划 §6](./BU前端接入规划.md#6-组件目录) 建目录 | — | 与 prsm **零 cross-import** | 5.5 #6 |
| **C27** | `front/src/pages/DatasetsPage.tsx` | 卡片按 `analysis_mode` 分叉；`status` 用 DB 枚举映射；BU badge + §9.5 DIA-NN 空态文案 | C6 | 只读 API 字段；列表响应为 **数组**（与现网一致） | 5.5 #4–5, 5.1 #7 |
| **C28** | `front/src/pages/DatasetPage.tsx` | **保留** TD cutoff 概览页（D16）；由 `DatasetModeGate` 在 `TOP_DOWN` 时挂载，**不**自动 Navigate 到 prsms | C25 | 避免 TD/BU 同文件混写 | 5.5 #1 |
| **C29** | `front/src/api/types.ts` | 扩展 `DatasetOut`；新增 `features/bu/types.ts` 或 `api/bu/types.ts` | C1 | TD 类型 **向后兼容** | 5.2 #1 |
| **C30** | `front/src/api/client.ts` 或 `features/bu/api/*` | BU API client；**不**修改现有 TD fetch | C22 | 所有 BU 请求走独立模块（D13 `search`） | 5.5 #3 |
| **C31** | `front/src/features/prsm/**` | 实施期 **diff 为零**（硬约束） | — | CI / PR 检查 `git diff -- front/src/features/prsm` | 5.5 #6 |

**`features/bu/` 建议目录（P0 scaffold）**：

```text
front/src/features/bu/
├── routes/
│   ├── DatasetModeGate.tsx
│   ├── BuDatasetLayout.tsx
│   └── buRoutes.tsx              # 可选：集中子路由表
├── pages/
│   ├── BuOverviewPage.tsx        # P0 可先占位 + QC 卡片
│   ├── BuProteinsListPage.tsx
│   ├── BuPeptidesListPage.tsx
│   ├── BuMatchesListPage.tsx
│   ├── BuMatchDetailPage.tsx     # M5 前可 stub
│   └── BuProteinDetailPage.tsx   # M7
├── components/
│   ├── BuDatasetHeader.tsx
│   ├── BuDataTable.tsx
│   ├── BuListFilters.tsx
│   └── spectrum/                 # 抄版，不 import prsm
├── api/
│   └── buClient.ts
├── constants/
│   └── importStages.ts
└── types.ts
```

---

## 5. 实施顺序与 PR 切片

### 5.1 四阶段依赖

```text
阶段 A — 契约层（可并行）
  C1, C2, C3, C29          Schema + compat SQL + 前端类型

阶段 B — 导入 M1（阻塞 BU 一切联调）
  C8 → C9 → C10 → C11 → C13(C14–C16) → C12 → C21
  verify: POST /imports d:\dia-shuju → 5.1 全绿

阶段 C — 数据集 API + 运行时骨架
  C4(文档/migration), C5, C6, C7, C20
  C17 → C18(lists/overview 优先) → C22 → C23
  verify: 5.2 全绿

阶段 D — 前端分叉 M4
  C25, C26(scaffold), C27, C28, C30
  verify: 5.5 #1–5；C31 prsm diff=0
```

### 5.2 建议 PR 切片（便于 review · 低冲突）

| PR | 包含 C 项 | 标题建议 | 合并门槛 |
|---|---|---|---|
| PR-1 | C8–C12, C13–C16, C21 | feat(ingest): DIA-NN BU path import | 5.1 |
| PR-2 | C1–C3, C4, C5–C7 | feat(api): dataset analysis_mode fork | 5.2 #1–3 |
| PR-3 | C17–C19, C20, C22–C24 | feat(bu): runtime services + routers | 5.2 #4–6 |
| PR-4 | C25–C31 | feat(front): DatasetModeGate + bu scaffold | 5.5 + prsm diff=0 |
| PR-5 | （M5+） | feat(bu): match spectrum + XIC | 5.3 |

**原则**：每个 PR **单一域**（ingest / api / bu-runtime / front）；禁止「一个 PR 改 ingest + 改 prsm」。

### 5.3 阶段内并行度

| 可并行 | 须串行 |
|---|---|
| C1 ∥ C2；C29 随 C1 | C6 依赖 M1 有 BU 数据集 |
| C18 各 service 文件 ∥ | C22 依赖 C18 lists/overview |
| C26 目录 scaffold ∥ PR-3 | C25 依赖 C6 字段稳定 |
| C4 migration ∥ PR-2 | C7 依赖 C20 |

---

## 6. 验收与硬约束

### 6.1 P0 完成定义（Definition of Done）

| # | 条件 |
|---|---|
| 1 | `d:\dia-shuju` 路径导入成功，`identification_matches` ≈ 110,026 |
| 2 | `GET /datasets/:slug` 对 BU 返回 `analysis_mode`, `cutoffs:[]`, `bu_runs` |
| 3 | TD histone（或任意 TD 样例）导入 / 打开 **回归通过** |
| 4 | 浏览器打开 BU slug → Overview 壳层 + 三列表 Tab（可空数据 stub） |
| 5 | `git diff -- front/src/features/prsm` **为空** |
| 6 | [验收测试矩阵](./验收测试矩阵.md) §5.1 + §5.2 + §5.5（#1–#5,#7）勾选 |

### 6.2 硬约束检查表（PR 自检）

| 约束 | 检查方式 |
|---|---|
| TD 零修改（产品级） | TD 数据集 E2E + prsm diff=0 |
| URL 无 `/bu/` | grep 路由注册 |
| DTO 在 `schemas/bu.py` | grep `class Bu` 不在 `bu/services` |
| 索引不在 runtime 创建 | grep `CREATE INDEX` 不在 `bu/services` |
| mixed wiring | capabilities `spectra_source=mixed` 数据集 mzML run 可 resident |
| v1 .d match MS2 | P5 不请求或 404（D10） |

### 6.3 明确不在 P0 解决

| 项 | 文档 |
|---|---|
| `.d` run match 级 MS2/XIC | [Viewer §17](./Viewer接入规划-完整版.md#17-v1-明确不支持项) |
| pg/pr matrix 入库 | 导入规划 §3 |
| PTM 碎片通道 | 谱图查看说明 |
| ZIP ingest 根 | D5 |

---

## 7. 专项文档索引

| C 域 | 深度细节文档 |
|---|---|
| C1–C7, C22 | [BU列表与数据集API规范.md](./BU列表与数据集API规范.md) |
| C8–C16 | [Bottom-Up数据导入规划.md](./Bottom-Up数据导入规划.md) |
| C17–C24 | [BU运行时后端模块规划.md](./BU运行时后端模块规划.md) |
| C25–C31 | [BU前端接入规划.md](./BU前端接入规划.md) |
| 谱图 G1–G10 | [谱图查看说明.md](./谱图查看说明.md) |
| Coverage M7 | [Sequence-Coverage数据方案.md](./Sequence-Coverage数据方案.md) |
| 决策 D1–D19 | [决策登记表.md](./决策登记表.md) |
| E2E | [验收测试矩阵.md](./验收测试矩阵.md) |
| 总览 | [Viewer接入规划-完整版.md](./Viewer接入规划-完整版.md) |

### 7.1 推荐阅读顺序（实施者）

1. **本文（P0 清单）** → 2. **[决策登记表](./决策登记表.md)** → 3. **[导入规划](./Bottom-Up数据导入规划.md)**（PR-1）→ 4. **[API 规范](./BU列表与数据集API规范.md)**（PR-2）→ 5. **[运行时规划](./BU运行时后端模块规划.md)**（PR-3）→ 6. **[前端规划](./BU前端接入规划.md)**（PR-4）→ 7. **[验收矩阵](./验收测试矩阵.md)**（每 PR 收尾）

---

## 修订记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v1.0 | 2026-05-21 | 首版：C1–C31 任务映射、低耦合原则、PR 切片、P0 DoD |

---

*实施在 `E:\viewer\` 仓库进行；本仓库（`d:\dia-shuju\`）仅维护规划与样例数据。*
