# BU 前端接入规划

> **文档版本**：v1.1  
> **日期**：2026-05-21  
> **Viewer 项目**：`E:\viewer\`  
> **数据样例**：`d:\dia-shuju\`  
> **状态**：规划稿（确认后实施）  
> **关联文档**：[P0-Viewer代码改造规划.md](./P0-Viewer代码改造规划.md)（C25–C31 前端任务）、[Viewer接入规划-完整版.md](./Viewer接入规划-完整版.md)（两页模型 / 图表）、[Bottom-Up数据导入规划.md](./Bottom-Up数据导入规划.md)（入库字段）、[谱图查看说明.md](./谱图查看说明.md)（谱图 API / 组件绑定）

---

## 目录

1. [文档目的](#1-文档目的)
2. [路由分叉](#2-路由分叉)
3. [页面清单](#3-页面清单)
4. [列表页：列定义与筛选](#4-列表页列定义与筛选)
5. [页面线框](#5-页面线框)
6. [组件目录](#6-组件目录)
7. [复用边界与请求守卫](#7-复用边界与请求守卫)
8. [实施顺序与验收](#8-实施顺序与验收)
9. [DatasetsPage 改造规范](#9-datasetspage-改造规范)
10. [导入 UI 与进度条](#10-导入-ui-与进度条)

---

## 1. 文档目的

本文只回答 **Bottom-Up DIA 在 Viewer 前端怎么接**：路由如何按 `analysis_mode` 分叉、有哪些页面、三张列表表怎么列/怎么筛、线框长什么样、`front/src` 下新建哪些文件。

**不包含**：parquet 入库、scan 解析算法、后端 API 实现细节——分别见导入规划与谱图查看说明。

### 1.1 硬约束（与全项目一致）

| # | 约束 |
|---|---|
| 1 | URL **无** `/bu/` 根前缀；与 Top-Down 共用 `/datasets` |
| 2 | Top-Down `features/prsm/**` **零修改** |
| 3 | BU 前端代码全部落在 `features/bu/**`；谱图组件 **抄版** 不 import 改 prsm |
| 4 | 路由分叉靠 `datasets.analysis_mode`，不靠 URL 猜测 |
| 5 | 列表数据来自 DB API，**禁止**前端读 parquet |

---

## 2. 路由分叉

### 2.1 分叉点

用户进入任意数据集相关 URL 时，前端必须先拿到数据集元数据（至少含 `analysis_mode`、`capabilities`、`extra_metadata`），再决定挂载哪套 layout 与 outlet。

```text
GET /api/v1/datasets/:slug
        │
        ├── analysis_mode === 'TOP_DOWN'  → 现有 PrSM 路由树（不改）
        │
        └── analysis_mode === 'BOTTOM_UP' → BU 路由树（本文）
```

**`capabilities.list_routes`**（导入时写入）决定数据集内 Tab 可见性，v1 固定为 `["proteins", "peptides", "matches"]`。

### 2.2 路由树（React Router v6 建议）

```text
/                                    → 重定向 /datasets
/datasets                            → DatasetListPage（TD+BU 混合列表，共用）

/datasets/:slug                      → BuDatasetLayout（BU 壳层）
  index                              → BuOverviewPage          【整体页】
  proteins                           → BuProteinsListPage
  proteins/:proteinId                → BuProteinDetailPage
  peptides                           → BuPeptidesListPage
  matches                            → BuMatchesListPage
  matches/:matchId                   → BuMatchDetailPage       【鉴定详情】

```

> **v1 导入**：沿用现有 **DatasetsPage 内嵌导入**（路径提交 + 进度），**不**新增独立 `/import`、`/imports/:jobId` 路由。P7 标记为「已有能力，非 BU 新路由」。

Top-Down 现有树（**保持不变**）：

```text
/datasets/:slug/:cutoff/prsms/...
/datasets/:slug/:cutoff/proteins/...
```

### 2.3 路由注册方式（最小侵入）

在 `front/src/App.tsx`（项目实际路由入口）中，**不修改** prsm 子树，仅新增 BU 分支：

```tsx
// 伪代码 — 实施时按项目实际 router 文件调整
{
  path: "datasets/:slug",
  element: <DatasetModeGate />,           // 拉 slug → 读 analysis_mode
  children: [
    { index: true, element: <ModeAwareOverview /> },
    // ModeAwareOverview 内部：
    //   TOP_DOWN → 现有 Overview
    //   BOTTOM_UP → <BuOverviewPage />

    {
      path: "proteins",
      element: <BuModeOnly><BuProteinsListPage /></BuModeOnly>,
    },
    { path: "proteins/:proteinId", element: <BuModeOnly><BuProteinDetailPage /></BuModeOnly> },
    { path: "peptides", element: <BuModeOnly><BuPeptidesListPage /></BuModeOnly> },
    { path: "matches", element: <BuModeOnly><BuMatchesListPage /></BuModeOnly> },
    { path: "matches/:matchId", element: <BuModeOnly><BuMatchDetailPage /></BuModeOnly> },
  ],
}
```

**`DatasetModeGate`**（D16）：Suspense + `useDataset(slug)`。`TOP_DOWN` 时 **渲染现有 `DatasetPage`**（cutoff 卡片），不自动跳转 prsms。`BOTTOM_UP` 时挂载 `BuDatasetLayout` 子路由。

**路径软着陆**（D17）：URL 与分析模式不一致时 **重定向**到合法入口（可选 toast），**不**用 404 惩罚用户；详见 [§9.4](#94-datasetmodegate-行为)。

**`BuModeOnly`**：`analysis_mode !== 'BOTTOM_UP'` 时 `<Navigate to=".." replace />`。

### 2.4 导航 Tab 分叉

| 位置 | Top-Down | Bottom-Up |
|---|---|---|
| 数据集壳层 Tab | Cutoffs / PrSMs / Proteins … | **Overview / Proteins / Peptides / Matches** |
| 面包屑 | `数据集 > cutoff > prsm` | `数据集 > Matches > LLLPGELAK` |
| 列表行点击 | → PrSM 详情 | → `/matches/:matchId` |

Tab 数据源：`capabilities.list_routes` + 当前 pathname 高亮。

### 2.5 URL 查询参数约定（列表页共用）

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `search` | string | — | 全文搜索（序列 / accession / gene） |
| `q_max` | number | `extra_metadata.q_value_cutoff`（0.01） | Q.Value 上限 |
| `run_id` | integer | 全部 run | 按 run 过滤 matches |
| `charge` | int | — | 电荷态 |
| `rt_min` / `rt_max` | number | — | RT 范围（分钟） |
| `mz_min` / `mz_max` | number | — | precursor m/z |
| `decoy` | boolean | `false` | 默认隐藏 decoy |
| `sort` | string | 见 §4 | 列排序键 |
| `order` | `asc\|desc` | `desc` | 排序方向 |
| `page` | int | `1` | 页码 |
| `page_size` | int | `50` | 每页条数 |

列表页 **同步 URL ↔ 筛选状态**（可分享链接）；改筛选重置 `page=1`。

---

## 3. 页面清单

### 3.1 总表

| # | 页面 | URL | 布局 | 主要 API | 图表？ | 里程碑 |
|---|---|---|---|---|---|---|
| P0 | 数据集列表 | `/datasets` | 全局 | `GET /datasets` | 否 | 已有 |
| P1 | **整体页** | `/datasets/:slug` | BuDatasetLayout | `GET /datasets/:slug`, `.../overview`, `.../runs/:id/chromatogram` | ✅ 少量 | M4 |
| P2 | 蛋白列表 | `.../proteins` | 同上 + 列表工具栏 | `GET .../proteins` | 否 | M4 |
| P3 | 肽段列表 | `.../peptides` | 同上 | `GET .../peptides` | 否 | M4 |
| P4 | 鉴定列表 | `.../matches` | 同上 | `GET .../matches` | 否 | M4 |
| P5 | **鉴定详情** | `.../matches/:matchId` | 同上 | `GET .../matches/:id`, `.../xic`, `.../spectrum/ms2` | ✅ 核心 | M5–M6 |
| P6 | **蛋白详情** | `.../proteins/:proteinId` | 同上 | `GET .../proteins/:id` | Sequence only | M7 |
| P7 | 导入进度 | DatasetsPage 内嵌 | 全局 | `GET /imports/:jobId` | 否 | **已有，非新路由** |

### 3.2 各页职责摘要

**P1 整体页**：QC 卡片 + Run 切换 + TIC/BPC + 三个列表入口；**不**加载单条 match 谱图。

**P2–P4 列表页**：Server-side 分页表格 + 统一筛选栏；行点击跳转详情（P4 → P5，P2 → P6）。

**P5 鉴定详情**：摘要条 + XIC + MS2(b/y) + MS1；`.d` run 可选 4D 小窗。

**P6 蛋白详情**：注释 + Sequence coverage + 下属肽段表（链到 P5）。

### 3.3 页面 ↔ 组件挂载矩阵

| 页面 | 必挂组件 | 条件挂载 |
|---|---|---|
| P1 | `BuDatasetHeader`, `BuQcStats`, `BuListEntryCards`, `TicChart` | `BpcChart` Tab；`RtMzMiniHeatmap`；`DiaWindowMap`（`.d`） |
| P2 | `BuDataTable`, `BuListFilters` | — |
| P3 | 同上 | — |
| P4 | 同上 | 侧栏可折叠 `QValueSlider` |
| P5 | `BuMatchSummary`, `XICChart`, `BuSpectrumChart`×2 | `MzMobilityScatter`（`.d`）；`BuFragmentTable` |
| P6 | `BuProteinHeader`, `SequenceCoverage`, `BuPeptideLinksTable` | — |

---

## 4. 列表页：列定义与筛选

三张表共用 **`BuListFilters`** + **`BuDataTable`**（TanStack Table 或项目现有表格封装）。列定义通过 config 注入，避免三份重复逻辑。

### 4.1 蛋白列表 `/proteins`

**默认排序**：`pg_max_lfq` desc（无定量时 fallback `accession` asc）

| 列 key | 表头 | 数据来源 | 格式 | 默认可见 | 可排序 |
|---|---|---|---|---|---|
| `accession` | Accession | `proteins.accession` | 文本，链到 P6 | ✅ | ✅ |
| `gene_name` | Gene | `proteins.gene_name` | 文本 | ✅ | ✅ |
| `description` | Description | `proteins.description` | 省略号 + tooltip | ✅ | ❌ |
| `protein_group` | Protein group | `extra_metadata.protein_group` | 等宽小字 | ✅ | ❌ |
| `pg_max_lfq` | PG.MaxLFQ | `extra_metadata.pg_max_lfq` | 科学计数 / KMG | ✅ | ✅ |
| `pg_q_value` | PG Q | `extra_metadata.pg_q_value` | `1.2e-4` | ✅ | ✅ |
| `peptide_count` | Peptides | API 聚合 | 整数 | ✅ | ✅ |
| `match_count` | Matches | API 聚合 | 整数 | 🟡 | ✅ |
| `is_decoy` | Decoy | `proteins.is_decoy` | badge | ❌ | ✅ |

**筛选栏**

| 控件 | 绑定参数 | 说明 |
|---|---|---|
| 搜索框 | `search` | 匹配 accession / gene / description |
| 隐藏 decoy | `decoy=false` | 默认勾选（隐藏 decoy） |
| 仅含肽段 ≥N | `min_peptides` | 可选，二期 |

**行交互**：点击 accession → P6；右键/操作列「View matches」→ P4 并带 `search=<accession>` 预填。

### 4.2 肽段列表 `/peptides`

**默认排序**：`best_q_value` asc

| 列 key | 表头 | 数据来源 | 格式 | 默认可见 | 可排序 |
|---|---|---|---|---|---|
| `sequence` | Sequence | `peptides.sequence` | 等宽 mono | ✅ | ✅ |
| `length` | Len | `peptides.length` | 数字 | ✅ | ✅ |
| `match_count` | Precursors | 聚合 | 整数 | ✅ | ✅ |
| `best_q_value` | Best Q | min(q) | 科学计数 | ✅ | ✅ |
| `protein_groups` | Protein groups | 关联聚合 | 截断 + tooltip | ✅ | ❌ |
| `genes` | Genes | 关联 | 截断 | 🟡 | ❌ |
| `example_modified` | Modified | 任一条 `modified_sequence` | 小字 | 🟡 | ❌ |

**筛选栏**

| 控件 | 绑定参数 | 说明 |
|---|---|---|
| 搜索框 | `search` | 序列子串（大小写不敏感） |
| 长度 | `min_length`, `max_length` | 肽段长度 |
| Q 阈值 | `q_max` | 针对该肽段关联 match 的 best Q |
| 蛋白 | `protein_id` | 下拉或从 P6 带入 |

**行交互**：点击行 → P4 并带 `search=<sequence>`；操作列「Best match」→ 该肽段 Q 最小的 `/matches/:id`。

### 4.3 鉴定列表 `/matches`（主入口）

**默认排序**：`q_value` asc（或 `intensity` desc，用户可切换）

| 列 key | 表头 | 数据来源 | 格式 | 默认可见 | 可排序 |
|---|---|---|---|---|---|
| `modified_sequence` | Modified sequence | `identification_matches.modified_sequence` | mono | ✅ | ✅ |
| `sequence` | Stripped | `peptides.sequence`（join） | mono 灰色 | ✅ | ✅ |
| `precursor_mz` | Precursor m/z | `precursor_mz` | 4 位小数 | ✅ | ✅ |
| `precursor_charge` | z | `precursor_charge` | `2+` | ✅ | ✅ |
| `rt` | RT (min) | `retention_time` | 2 位小数 | ✅ | ✅ |
| `q_value` | Q.Value | `q_value` | 科学计数，&lt;0.01 绿 | ✅ | ✅ |
| `intensity` | Quantity | `intensity` | K/M/G | ✅ | ✅ |
| `protein_group` | Protein group | `extra_metadata.protein_group` | 截断 | ✅ | ❌ |
| `genes` | Genes | join proteins | 截断 | 🟡 | ❌ |
| `run_name` | Run | `runs.file_name` | 文本 | 🟡 | ✅ |
| `scan_number` | Scan | `scan_number` | 数字或 `—`（-1） | ❌ | ✅ |
| `rt_window` | RT window | `extra_metadata.rt_start/stop` | `92.15–93.08` | 🟡 | ❌ |
| `is_decoy_match` | Decoy | `is_decoy_match` | badge | ❌ | ✅ |

**筛选栏（Matches 最全）**

| 控件 | 绑定参数 | 默认 | 说明 |
|---|---|---|---|
| 搜索框 | `search` | — | modified / stripped / protein group |
| Q.Value 滑块 | `q_max` | **0.01**（读 `extra_metadata.q_value_cutoff`） | 主过滤 |
| Run | `run_id` | 全部 | 多 run 时显示 |
| Charge | `charge` | 全部 | 2+ / 3+ … |
| RT 范围 | `rt_min`, `rt_max` | — | 双端输入 |
| m/z 范围 | `mz_min`, `mz_max` | — | precursor |
| 显示 decoy | `decoy=true` | 关 | 高级 |
| 重置 | — | — | 恢复导入默认阈值 |

**行交互**：整行点击 → P5；键盘 ↑↓ + Enter 可选（二期）。

### 4.4 列表 API 形状（前端 TypeScript 期望）

```typescript
// GET /api/v1/datasets/:slug/matches?page=1&page_size=50&q_max=0.01&sort=q_value&order=asc
// 与 TD 一致：分页包装为 Page<T>，无 filters_applied / defaults
type Page<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};
// q_value_cutoff：主源 GET /datasets/:slug → extra_metadata.q_value_cutoff；
// 仅当缺字段时 fallback GET .../overview 的 q_value_cutoff
```

前端 **不**假设 `items.length === total`；空态组件 `BuEmptyState` 区分「无数据」与「筛选过严」。

---

## 5. 页面线框

### 5.1 壳层 `BuDatasetLayout`

```text
┌─────────────────────────────────────────────────────────────┐
│ Viewer logo    Datasets > HeLa DIA R1          [导入] [?]  │
├─────────────────────────────────────────────────────────────┤
│ HeLa DIA 500ng R1 · DIA-NN 2.0 · BOTTOM_UP · 110,026 matches│
│ [ Overview ] [ Proteins ] [ Peptides ] [ Matches ]          │
├─────────────────────────────────────────────────────────────┤
│                        <Outlet />                           │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 整体页 P1

```text
┌─ QC 卡片 ─────────────────────────────────────────────────┐
│ 110,026 matches │ 8,063 protein groups │ 92,704 peptides   │
│ Mass accuracy 0.8 ppm │ Median FWHM 0.35 min               │
├─ Run ─────────────────────────────────────────────────────┤
│ Run: [ 20200110_Hela_...R1.mzML ▼ ]   Format: mzML        │
├─ 色谱 ────────────────────────────────────────────────────┤
│ [ TIC | BPC ]  ～～～～～～～～～～～～～～～～～～～～～～  │
├─ 可选 ────────────────────────────────────────────────────┤
│ RT×m/z 简图（小） │ DIA 窗口条带（仅 .d）                   │
├─ 入口 ────────────────────────────────────────────────────┤
│  [ → Proteins 8063 ]  [ → Peptides 92704 ]  [ → Matches ] │
└─────────────────────────────────────────────────────────────┘
```

### 5.3 列表页 P2 / P3 / P4（以 Matches 为例）

```text
┌─ 筛选栏 ──────────────────────────────────────────────────┐
│ 🔍 Search    Q ≤ [====●====] 0.01   Run [All▼]  z [All▼]  │
│ RT [___]–[___] min   m/z [___]–[___]   [ ] Show decoy     │
├─ 表格 ────────────────────────────────────────────────────┤
│ Modified sequence │ m/z    │ z │ RT   │ Q.Value │ Quantity│
│ LLLPGELAK         │ 477.31 │2+ │ 92.46│ 1.0e-3  │ 4.2e7   │ ← 点击
│ ...               │        │   │      │         │         │
├─ 分页 ────────────────────────────────────────────────────┤
│ ◀ 1 2 3 … 2201 ▶     50 / page     共 110,026 条          │
└─────────────────────────────────────────────────────────────┘
```

Proteins / Peptides 复用同一壳，仅列 config 与默认排序不同。

### 5.4 鉴定详情 P5

```text
┌─ 摘要条 ──────────────────────────────────────────────────┐
│ LLLPGELAK · 2+ · 477.3051 · RT 92.46 · Q 0.001            │
│ PG O60814;P62805 · Run Hela_R1 · Scan 67726 (resolved)    │
├─ XIC ─────────────────────────────────────────────────────┤
│      ░░░ RT window ░░░  │ apex                             │
│ ～～～～～/\～～～～～～～～～～～～～～～～～～～～～～～～  │
├─ MS2 + MS1 ───────────────────────────────────────────────┤
│  MS2 + b/y 标注（大）          │  MS1 + precursor ▼（中）  │
├─ 可选 / 碎片表 ───────────────────────────────────────────┤
│  m/z×1/K0 小窗（.d）           │  matched b/y 表          │
└─────────────────────────────────────────────────────────────┘
```

### 5.5 蛋白详情 P6

```text
┌─ 蛋白注释 ────────────────────────────────────────────────┐
│ P62805 · Histone H4 · description...                      │
├─ Sequence coverage ───────────────────────────────────────┤
│ MARTKQTARKSTGGKAPRKQLATKAARKSAPATGGVKKPHRYRPGTVALRE...     │
│      ████████              ████                           │
├─ 肽段表 ──────────────────────────────────────────────────┤
│ Sequence   │ Matches │ Best Q │ → 点击跳转 match 详情      │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. 组件目录

所有 BU 前端代码落在 **`E:\viewer\front\src\features\bu\`**，**不**修改 `features/prsm/**`。

```text
front/src/features/bu/
├── index.ts                          # 对外 re-export（供 router 懒加载）
├── routes/
│   ├── DatasetModeGate.tsx           # analysis_mode 分叉
│   ├── BuModeOnly.tsx                # 非 BU 重定向
│   └── buRoutes.tsx                  # 路由片段（可选）
├── layout/
│   ├── BuDatasetLayout.tsx           # Tab 壳 + Outlet
│   ├── BuDatasetHeader.tsx           # 标题 / 元信息 / badge
│   └── BuTabNav.tsx                  # Overview | Proteins | Peptides | Matches
├── pages/
│   ├── BuOverviewPage.tsx            # P1
│   ├── BuProteinsListPage.tsx        # P2
│   ├── BuProteinDetailPage.tsx       # P6
│   ├── BuPeptidesListPage.tsx        # P3
│   ├── BuMatchesListPage.tsx         # P4
│   └── BuMatchDetailPage.tsx         # P5
├── lists/
│   ├── BuDataTable.tsx               # 通用表格
│   ├── BuListFilters.tsx             # 通用筛选栏
│   ├── BuListToolbar.tsx             # 列显示 / 导出（二期）
│   ├── buColumnDefs/
│   │   ├── proteinsColumns.ts
│   │   ├── peptidesColumns.ts
│   │   └── matchesColumns.ts
│   ├── useBuListQuery.ts             # URL ↔ API 参数
│   └── BuEmptyState.tsx
├── overview/
│   ├── BuQcStats.tsx                 # QC 卡片
│   ├── BuListEntryCards.tsx          # 三入口卡片
│   ├── RunSelector.tsx               # run 下拉
│   └── BuOverviewCharts.tsx          # TIC/BPC/可选图组合
├── match-detail/
│   ├── BuMatchSummary.tsx
│   ├── BuMatchDetailCharts.tsx       # 编排 XIC + MS1/MS2
│   └── BuFragmentTable.tsx
├── protein-detail/
│   ├── BuProteinHeader.tsx
│   └── BuPeptideLinksTable.tsx
├── spectra/                          # 抄版自 prsm，独立维护
│   ├── BuSpectrumChart.tsx           # MS1/MS2 棍图 + 标注
│   ├── XICChart.tsx
│   ├── TicChart.tsx
│   ├── BpcChart.tsx
│   ├── RtMzMiniHeatmap.tsx           # 可选 v1
│   ├── DiaWindowMap.tsx              # 仅 .d
│   ├── MzMobilityScatter.tsx         # 仅 .d
│   └── spectrumTypes.ts              # SpectrumV1 类型
├── sequence/
│   └── SequenceCoverage.tsx          # 固定命名
├── hooks/
│   ├── useDataset.ts                 # slug → dataset + capabilities
│   ├── useBuOverview.ts
│   ├── useMatchDetail.ts
│   └── useRunCapabilities.ts       # has_im / spectra_source
├── api/
│   ├── buClient.ts                   # fetch 封装
│   ├── datasets.ts
│   ├── lists.ts
│   └── spectra.ts
└── utils/
    ├── formatters.ts                 # q_value, lfq, rt, mz
    ├── listParams.ts                 # URL 序列化
    └── guards.ts                     # analysis_mode / run format
```

### 6.1 与现有 frontend 的依赖关系

| 依赖 | 方式 |
|---|---|
| 全局 Layout / 主题 / Button / Table 基元 | `shared/` 或 `components/ui` **import** |
| `features/prsm/SpectrumChart` | ❌ 不 import；已抄到 `bu/spectra/BuSpectrumChart` |
| 数据集列表 `/datasets` | 共用现有页；卡片上显示 `analysis_mode` badge |
| 导入流程 | 共用 DatasetsPage 内嵌导入；成功后 `navigate(/datasets/${slug})` |

### 6.2 懒加载建议

```tsx
const BuOverviewPage = lazy(() => import("@/features/bu/pages/BuOverviewPage"));
// router 层对 bu/pages/* 做 lazy，避免 TD 用户加载 BU 图表库
```

---

## 7. 复用边界与请求守卫

### 7.1 页面级守卫

```text
analysis_mode !== 'BOTTOM_UP'  → 不 mount features/bu 下任何页面组件（BuModeOnly 回退）
URL 与分析模式不一致          → D17 软重定向，不用 404
pathname 含 /matches/:id     → 禁止请求 TD prsm API
page === overview              → 禁止请求 /matches/:id/spectrum/*
run.raw_format !== 'bruker_d'  → 不 mount DiaWindowMap / MzMobilityScatter
```

### 7.2 列表页守卫

- 禁止在前端读取 `source_root` 下 parquet / mzML 路径做「本地解析」。
- `q_max` 初始值：主源 `GET /datasets/:slug` → `extra_metadata.q_value_cutoff`；缺字段时 fallback `GET .../overview` 的 `q_value_cutoff`。禁止写死常量（允许用户改筛选）。

### 7.3 性能预算

| 场景 | 预算 |
|---|---|
| 列表首屏 | &lt; 500ms API + 渲染 50 行 |
| 整体页 TIC | 单 run Downsample 后 &lt; 2s |
| 进入 match 详情 | 摘要 &lt; 300ms；MS2 按需 &lt; 2s（含 scan 解析） |

---

## 8. 实施顺序与验收

### 8.1 实施顺序

| 步骤 | 交付 | 依赖 |
|---|---|---|
| 1 | `routes/` + `layout/` + `DatasetModeGate` | 后端 `GET /datasets/:slug` 含 mode |
| 2 | `lists/` + P2/P3/P4 列与筛选 | 列表 API |
| 3 | P1 整体页 QC + TIC + 入口 | overview API |
| 4 | P5 详情摘要 + XIC + MS2 | 谱图 API |
| 5 | P6 Sequence coverage | 蛋白详情 API |
| 6 | `.d` 条件组件 | tdf 后端 |

### 8.2 验收清单

| # | 检查项 | 期望 |
|---|---|---|
| 1 | 打开 TD 数据集 | 仍走 prsm 路由，无 BU Tab |
| 2 | 打开 BU 数据集 | Tab 为 Overview / Proteins / Peptides / Matches |
| 3 | Matches 默认 Q | 筛选默认 0.01，与导入一致 |
| 4 | 列表 URL 分享 | 复制 URL 后筛选状态保持 |
| 5 | 点击 match 行 | 进入 P5，不整页刷新 TD 组件 |
| 6 | 蛋白详情 | 无 MS2 请求；Sequence coverage 标题正确 |
| 7 | `features/prsm` diff | 实施期 **零修改** |

---

## 9. DatasetsPage 改造规范

共用页 **`DatasetsPage`**（`/datasets`）与 **`DatasetModeGate`**（`/datasets/:slug`）是 TD/BU 分叉的**唯一入口**；改造须保持低耦合：只读 API 字段，不在前端推断模式。

### 9.1 低耦合原则

| 层 | 规则 |
|---|---|
| 数据 | 列表与详情 **只** 通过 `GET /datasets`、`GET /datasets/:slug` 读 `analysis_mode`；禁止根据 slug / 路径猜测 TD/BU |
| 组件 | TD 逻辑留 `features/prsm/**`；BU 逻辑进 `features/bu/**`；共用页只做 **badge + 路由分发**，不混写业务 |
| API | `buClient.ts` 与 prsm client **分离**；BU 页禁止 import prsm API 模块 |
| 导入 | 共用 `POST /imports`；进度轮询共用 `GET /imports/:jobId`；stage 文案见 §10 |

### 9.2 列表卡片字段（`GET /datasets`）

每项 **必须** 含 `analysis_mode`（见 [BU列表与数据集API规范 §4.0](./BU列表与数据集API规范.md#40-get-datasets数据集列表共用)）。

| 字段 | 展示 | 说明 |
|---|---|---|
| `name` | 标题 | 主文案 |
| `slug` | 副标题 / tooltip | 可复制 |
| `status` | 状态 pill | DB 枚举：`IMPORTED` / `PARSING` / `READY` / `ERROR`（UI 映射为「就绪」「解析中」等，**禁止** `IMPORTING`/`FAILED`） |
| `analysis_mode` | **Badge** | `BOTTOM_UP` → 蓝「Bottom-Up」；`TOP_DOWN` → 灰「Top-Down」 |
| `source_software` | 小字（可选） | BU：`DIA-NN 2.0`；TD：TopPIC 等 |
| `updated_at` | 相对时间 | API 常为 `null`；展示时 **fallback `created_at`**（与现网 `DatasetOut` 一致） |

**不展示**：`cutoffs` 数量（BU 无 cutoff 概念）；列表项 **不** 渲染 TD 的 prsm/proteoform 计数。

### 9.3 `cutoffs` 为空时的展示

| 上下文 | TD 数据集 | BU 数据集 |
|---|---|---|
| `GET /datasets/:slug` 的 `cutoffs` | `[{type:"prsm",...},{type:"proteoform",...}]` | **`[]` 空数组**（D12） |
| 列表卡片 | 可显示 cutoff 入口 hint | **不显示** cutoff 相关 UI |
| 进入详情 | 停留 `/datasets/:slug`（`DatasetPage`，cutoff 卡片） | 停留 `/datasets/:slug`（BU Overview） |
| 壳层 Tab | Cutoffs / PrSMs / … | Overview / Proteins / Peptides / Matches |

前端 **禁止** 把 `cutoffs.length === 0` 当作错误；BU 用 `analysis_mode === 'BOTTOM_UP'` 分支，而非「无 cutoff 则当 BU」。

### 9.4 `DatasetModeGate` 行为

**D16 — TD 保留 cutoff 概览页**（与现网 `DatasetPage` 一致）：

```text
GET /datasets/:slug
    │
    ├── analysis_mode === 'TOP_DOWN'
    │       → <DatasetPage />   # cutoff 卡片，用户自选 cutoff 再进 prsms
    │
    └── analysis_mode === 'BOTTOM_UP'
            → <BuDatasetLayout />（Tab 见 §2.4；index = Overview）
```

**D17 — 路径软着陆**（普适：按 API 返回的 `analysis_mode` 纠正 URL，不写死拒绝）：

| 误配 URL（示例） | 行为 |
|---|---|
| TD 数据集 + `/matches`、`/peptides`、`/proteins`（无 cutoff 的 BU 路径） | `replace` 重定向 → `/datasets/:slug`（`DatasetPage`） |
| BU 数据集 + `/:cutoff/prsms` 等 TD 路径 | `replace` 重定向 → `/datasets/:slug`（BU Overview） |
| 子路由内 `analysis_mode` 与页面不符 | `BuModeOnly` 已有：`<Navigate to=".." replace />` |

可选：重定向时 toast「已跳转到该数据集的分析模式首页」。**404 仅**用于 slug / 实体 id 不存在（与 REST 一致），不用于「模式不匹配」。

### 9.5 DIA-NN 空态与导入文案（C27）

列表无 BU 数据集时，空态 **追加**（不替换 TD 通用说明）：

| 元素 | 文案（草案） |
|---|---|
| 标题 | 尚无 Bottom-Up 数据集 |
| 说明 | 选择包含 **DIA-NN `all_report.parquet`** 与 **mzML**（或 Bruker **`.d`** 目录）的文件夹作为 ingest 根 |
| 约束提示 | 谱图与 parquet 须在同一目录（[导入规划 D5](./Bottom-Up数据导入规划.md#17-已定稿决策d1d5)） |

导入表单控件 **不变**（仍 `POST /imports`）；仅空态与帮助文本区分 DIA-NN。

### 9.6 改造清单（文件级）

| 文件 | 改动 |
|---|---|
| `pages/DatasetsPage.tsx`（或等价） | 卡片 badge + status 映射 + §9.5 空态文案；导入表单不变 |
| `pages/DatasetPage.tsx` | **保留** TD cutoff 概览（D16）；由 Gate 在 TD 时挂载 |
| `features/bu/routes/DatasetModeGate.tsx` | 新建；D16/D17 分发与软重定向 |
| `features/prsm/**` | **零修改** |

---

## 10. 导入 UI 与进度条

v1 **不** 新增 `/import` 路由；沿用 **DatasetsPage 内嵌** 路径导入 + 进度面板（P7）。

### 10.1 交互流程

```text
用户填写 source_path + slug + name
    → POST /api/v1/imports
    → 轮询 GET /api/v1/imports/{job_id}（1–2 s 间隔）
    → status === 'success' → toast + navigate(/datasets/{slug})
    → status === 'failed'  → 展示 error_message，保留表单
```

### 10.2 stage 码与中文 label（与后端对齐）

与 [Bottom-Up数据导入规划 §12](./Bottom-Up数据导入规划.md#12-导入阶段与进度条) **共用** `import_jobs.stage` 枚举；前端 **只映射展示**，不改 stage 值。

建议在 `features/bu/constants/importStages.ts`（或 `shared/importStages.ts` 若 TD 共用）维护：

```typescript
export const IMPORT_STAGE_LABELS: Record<string, string> = {
  queued: "排队中",
  fingerprint: "计算指纹",
  init: "初始化数据集",
  runs: "登记谱图文件",
  proteins: "导入蛋白",
  peptides: "导入肽段",
  matches: "导入鉴定",
  finalize: "收尾",
  // TD 专用 stage 保留原映射，BU  job 不会进入未知 stage
};
```

| API 字段 | UI 绑定 |
|---|---|
| `stage` | 查表 → 主 label |
| `stage_detail` | 副标题（如 `导入鉴定 45000/110026`） |
| `progress` | 进度条 0–100 |
| `status` | `running` / `success` / `failed` |

### 10.3 进度条 UI

```text
┌─ 导入 HeLa DIA ─────────────────────────────────────────┐
│ 导入鉴定 45000/110026                                    │
│ ████████████████████░░░░░░░░░░  72%                     │
│ stage: matches · 预计剩余 ~20s（可选，二期）              │
└─────────────────────────────────────────────────────────┘
```

- **进行中**：禁用重复提交；允许「后台继续」关闭面板（job 仍跑）
- **失败**：展示 `error_message` + 「复制日志」；不自动清表单
- **成功**：2 s 内跳转数据集 Overview

### 10.4 低耦合

| 禁止 | 允许 |
|---|---|
| 在 DatasetsPage 内写 parquet 解析或路径探测 | `POST /imports` 交给后端 planner |
| 按文件扩展名猜测 BU/TD 并改 UI | 仅根据 job 返回的 `plan.shape` / 完成后 `analysis_mode` 展示 |
| BU 专用 stage 文案写死在 JSX 多处 | 单一 `IMPORT_STAGE_LABELS` 常量 |

---

## 附录 A：页面 URL vs API 路径对照

避免 **浏览器 URL 的 `:cutoff` 段** 与 **REST API** 混淆；二者 **无** `/bu/` 前缀。

### A.1 数据集级

| 场景 | 浏览器 URL | REST API |
|---|---|---|
| 数据集列表 | `/datasets` | `GET /api/v1/datasets` |
| TD 整体 / 默认入口 | `/datasets/:slug/:cutoff/prsms` | `GET /api/v1/datasets/:slug` + `.../cutoffs/:cutoff/...` |
| BU 整体页 | `/datasets/:slug` | `GET /api/v1/datasets/:slug` + `GET .../overview` |
| 导入 job | （DatasetsPage 内嵌，无独立 URL） | `POST /api/v1/imports` · `GET /api/v1/imports/:jobId` |

### A.2 列表与详情

| 场景 | 浏览器 URL | REST API |
|---|---|---|
| BU 蛋白列表 | `/datasets/:slug/proteins` | `GET /api/v1/datasets/:slug/proteins` |
| BU 鉴定详情 | `/datasets/:slug/matches/:matchId` | `GET .../matches/:id` · `.../xic` · `.../spectrum/ms2` |
| TD PrSM 详情 | `/datasets/:slug/:cutoff/prsms/:id` | `GET .../cutoffs/:cutoff/prsms/:id` |
| BU 蛋白详情 | `/datasets/:slug/proteins/:proteinId` | `GET .../proteins/:id` |

### A.3 常见误用（实施时禁止）

| ❌ 错误 | ✅ 正确 |
|---|---|
| `GET /api/v1/datasets/:slug/cutoffs/0.01/matches` | `GET /api/v1/datasets/:slug/matches?q_max=0.01` |
| 浏览器打开 `/datasets/:slug/0.01/matches`（BU） | `/datasets/:slug/matches?q_max=0.01` |
| BU 数据集请求 `.../cutoffs/...` 任意路径 | 404；Q 阈值仅 query `q_max` |

---

## 附录 B：文档关系

```text
Bottom-Up数据导入规划.md     → 入库字段（列表 API 的数据源）
Viewer接入规划-完整版.md       → 两页模型、图表范围、里程碑
谱图查看说明.md               → 谱图 API、SpectrumV1、G1–G10
BU前端接入规划.md（本文）      → 路由、列表、线框、组件目录
```

---

*文档 v1.1 · BU 前端专项规划 · §9–§10 补全 DatasetsPage / 导入 UI；确认后可进入 M4 实施。*
