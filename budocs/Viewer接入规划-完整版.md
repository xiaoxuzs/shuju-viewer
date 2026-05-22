# Viewer 谱图查看器 — Bottom-Up DIA 接入规划（完整版）

> **文档版本**：v1.4  
> **日期**：2026-05-21  
> **数据目录**：`d:\dia-shuju\`  
> **Viewer 项目**：`E:\viewer\`  
> **状态**：规划稿（确认后实施）

---

## 目录

1. [文档目的与结论摘要](#1-文档目的与结论摘要)
2. [正式网站要展示多少图？（先读本章）](#2-正式网站要展示多少图先读本章)
3. [两页模型：整体页 vs 详情页](#3-两页模型整体页-vs-详情页)
4. [Bottom-Up 与 Top-Down 是什么](#4-bottom-up-与-top-down-是什么)
5. [你的数据里有什么](#5-你的数据里有什么)
6. [谱图在哪里？鉴定结果是什么](#6-谱图在哪里鉴定结果是什么)
7. [Demo 与正式站的关系](#7-demo-与正式站的关系)
8. [数据库设计（复用 universal schema）](#8-数据库设计复用-universal-schema)
9. [数据导入策略](#9-数据导入策略)
10. [URL 与前端路由](#10-url-与前端路由)
11. [后端 API 设计](#11-后端-api-设计)
12. [页面与图表清单（按整体/详情拆分）](#12-页面与图表清单按整体详情拆分)
13. [组件复用与新写总账](#13-组件复用与新写总账)
14. [硬约束与改动边界](#14-硬约束与改动边界)
15. [实施里程碑](#15-实施里程碑)
16. [已确认决策清单](#16-已确认决策清单)
17. [v1 明确不支持项](#17-v1-明确不支持项)
18. [附录](#18-附录)

---

## 1. 文档目的与结论摘要

将 `d:\dia-shuju\` 下的 **Bottom-Up DIA（DIA-NN 2.0）** 接入 `E:\viewer\`，在**同一套「数据集」入口**（`/datasets`）中支持 Top-Down 与 Bottom-Up，并按 `analysis_mode` 展示不同页面。

| 问题 | 答案 |
|---|---|
| 正式站要展示 demo 里全部 17 张图吗？ | **不要**。demo 用于验证能力；正式站按 **整体页 + 详情页** 精简 |
| 谱图文件在哪？ | `*.mzML`、`* .d/` 是原始谱图；parquet 是鉴定索引 |
| URL 怎么设计？ | 先 `/datasets/:slug`；BU 详情在 `/matches/:id` 等 |
| 数据库 | 复用 universal schema，`analysis_mode=BOTTOM_UP` |
| Top-Down | **零修改**；BU 新增模块，谱图组件**抄版**独立目录 |

---

## 2. 正式网站要展示多少图？（先读本章）

### 2.1 结论一句话

**正式网站不需要展示 demo 文件夹里的全部图。**  
demo（`plots/demo01~05`）是开发阶段用来证明「数据能读、能联动」的；上线产品只保留 **两类页面** 上真正用到的图表。

### 2.2 三类内容对照

| 类别 | 是什么 | 是否上正式站 | 说明 |
|---|---|---|---|
| **A. 整体页图表** | 数据集级 QC / 概览 | ✅ 少量（3～4 个区块） | 用户**刚打开数据集**时看 |
| **B. 详情页图表** | 单条鉴定 / 单蛋白 | ✅ 核心（4～6 个区块） | 用户**点开某条结果**后看 |
| **C. demo 探索图** | 电荷分布、m/z 分布、全量 hexbin 等 | ❌ 或二期 | 分析用，非日常浏览必需 |

### 2.3 用户浏览路径（Bottom-Up）

```text
/datasets                          选数据集
    │
    ▼
/datasets/:slug                    【整体页】QC + 概览图 + 进入列表
    │
    ├── /proteins                  表格（不是「图集页」）
    ├── /peptides                  表格
    └── /matches                   表格
            │
            ▼ 用户点击某一行的 precursor
/datasets/:slug/matches/:matchId   【详情页】XIC + MS1 + MS2 标注 (+ 可选 4D)

/datasets/:slug/proteins/:id       【蛋白详情】Sequence coverage（序列图，不是质谱图）
```

---

## 3. 两页模型：整体页 vs 详情页

### 3.1 整体页（Dataset Overview）

**URL（Bottom-Up）**：`/datasets/:slug`  
**页面定位**：这一批实验「跑得怎么样？」「鉴定规模多大？」「从哪进蛋白/肽段/鉴定列表？」

#### 用户在什么情况下会打开整体页？

| 场景 | 用户意图 | 页面上应看到什么 |
|---|---|---|
| 导入后第一次打开 | 确认导入成功、规模是否合理 | QC 数字卡片、鉴定条数、run 列表 |
| 日常分析入口 | 决定先查蛋白还是肽段 | 三个入口：Proteins / Peptides / Matches |
| 怀疑采集异常 | 看色谱是否断裂、信号是否过弱 | **一张** TIC 或 BPC（按当前选中的 run） |
| 了解鉴定分布 | 大致 RT、m/z 覆盖 | **一张** 简化的 RT–m/z 密度图（可二期） |
| 对比 DIA 窗口（Bruker） | 方法学核对 | DIA 窗口条带图（仅当 run 为 `.d` 时显示） |

#### 整体页应包含的图表（正式站 · 建议 v1）

| 区块 | 图表/组件 | 必需？ | 数据来源 |
|---|---|---|---|
| 统计卡片 | 鉴定数、蛋白组数、肽段数、Mass accuracy | ✅ 必需 | DB 聚合 + `stats.tsv` |
| Run 切换 | mzML run / .d run 下拉 | ✅ 若有多个 run | `runs` 表 |
| 色谱概览 | **TIC** 或 **BPC**（二选一或 Tab） | ✅ 推荐 | mzML / tdfpy |
| 鉴定分布 | RT–m/z 小图（hexbin 简化版） | 🟡 可选 v1 | DB |
| DIA 窗口 | 隔离窗口示意图 | 🟡 仅 .d run | tdfpy |
| 入口 | 三个导航卡片/按钮 | ✅ 必需 | — |

#### 整体页明确不放的内容

- ❌ 单条肽段的 MS2 碎片标注  
- ❌ 单条肽段的 XIC 放大  
- ❌ 完整 4D 散点大图（占满屏）  
- ❌ Q.Value 直方图（可放在 Matches 列表侧栏筛选，不必占首页）  
- ❌ 电荷分布、m/z 分布等「统计报告图」

---

### 3.2 详情页（Spectrum / Match Detail）

**URL（Bottom-Up）**：`/datasets/:slug/matches/:matchId`  
**页面定位**：「这条 precursor 鉴定靠不靠谱？」「谱图证据是什么？」

#### 用户在什么情况下会打开详情页？

| 场景 | 用户意图 | 页面上应看到什么 |
|---|---|---|
| 从 Matches 表点进 | 核对某条 Q.Value、序列、定量 | 摘要条 + 谱图区 |
| 质疑某个蛋白推断 | 看该肽段 MS2 是否有足够 b/y | **MS2 + b/y 标注** |
| 看洗脱峰形 | 定量是否由真实峰支持 | **XIC** + DIA-NN RT 窗口阴影 |
| 确认前体 | MS1 上 precursor m/z 位置 | **MS1** + precursor 标记 |
| Bruker 4D 数据 | 该肽段在 IM 维是否一致 | 可选 **m/z × 1/K₀** 小窗（当前 RT 附近） |

#### 详情页应包含的图表（正式站 · 建议 v1）

| 区块 | 图表/组件 | 必需？ | 数据来源 |
|---|---|---|---|
| 摘要 | 序列、电荷、m/z、RT、Q.Value、蛋白组、scan | ✅ 必需 | `identification_matches` |
| XIC | 提取离子色谱 + RT 窗口 + apex 线 | ✅ 必需 | mzML MS1 按 m/z±ppm 提取 |
| MS2 | 棍状图 + **b/y 匹配高亮** | ✅ 必需 | mzML scan + 理论碎片 |
| MS1 | 棍状图 + precursor marker | ✅ 推荐 | 同 run 邻近 MS1 |
| 4D 小窗 | m/z vs 1/K₀（当前鉴定 RT） | 🟡 仅 .d | tdfpy |
| 碎片表 | matched b/y 列表（ppm、强度） | 🟡 推荐 | 后端计算 |

#### 详情页明确不放的内容

- ❌ 全 run 的 TIC/BPC（属于整体页）  
- ❌ 全数据集的 RT–m/z hexbin  
- ❌ 12 个 DIA 窗口总览（除非做折叠「方法信息」）

---

### 3.3 蛋白详情页（第三类 · 无质谱棍图）

**URL**：`/datasets/:slug/proteins/:proteinId`  
**不是「选谱图后的详情」**，而是「蛋白维度」。

| 区块 | 内容 |
|---|---|
| 蛋白注释 | accession、gene、description |
| **Sequence coverage** | 序列行上高亮被鉴定肽段（固定命名） |
| 下属肽段表 | 链接到 `/matches/:id` |

此处 **不放** MS1/MS2/XIC（避免与 match 详情重复）；用户从肽段表再进 match 详情看谱图。

---

### 3.4 两页模型一览表

|  | 整体页 `/datasets/:slug` | 详情页 `/matches/:matchId` | 蛋白页 `/proteins/:id` |
|---|---|---|---|
| **何时看** | 打开数据集、QC、选入口 | 选中一条鉴定 | 看蛋白覆盖 |
| **图的数量** | 少（1～3 张图 + 卡片） | 多（谱图为主 3～4 块） | 1 张 sequence 图 |
| **TIC/BPC** | ✅ | ❌ | ❌ |
| **XIC** | ❌ | ✅ | ❌ |
| **MS2 标注** | ❌ | ✅ | ❌ |
| **Sequence coverage** | ❌ | ❌ | ✅ |

---

## 4. Bottom-Up 与 Top-Down 是什么

（与 v1.0 相同，略述。）

| 维度 | Top-Down | Bottom-Up |
|---|---|---|
| 鉴定单元 | Proteoform / PrSM | Peptide / Precursor |
| 软件 | TopPIC + TopFD | DIA-NN 2.0 |
| Viewer | 已支持 | 本次接入 |

工作流：样本 → 酶切 → LC-MS [+TIMS] → **mzML / .d（谱图）** → DIA-NN → **parquet（鉴定）**。

---

## 5. 你的数据里有什么

| 类型 | 文件 | 正式站用途 |
|---|---|---|
| 谱图 | `*.mzML`、`* .d/` | 整体页 TIC；详情页 MS1/MS2/XIC/4D |
| 鉴定 | `all_report.parquet` | 入库；列表与详情索引 |
| QC | `all_report.stats.tsv` | **整体页**数字卡片 |
| 忽略 | `*.pkl`、zip | 不使用 |

实测：全量 323,232 行；Q.Value&lt;0.01 后 **110,026** 条鉴定，**8,063** 蛋白组。

---

## 6. 谱图在哪里？鉴定结果是什么

- **谱图** = mzML / .d 文件本体（不入库峰数组，只登记 `runs.file_path`）。  
- **鉴定** = parquet 一行一条 precursor（入库到 `identification_matches`）。  
- 点击鉴定后，运行时从路径读谱图并计算 b/y、XIC。

---

## 7. Demo 与正式站的关系

`d:\dia-shuju\demo\` 与 `plots\` 中的图 **不等于** 正式站页面草图。

| Demo 图 | 验证了什么 | 正式站放在哪 |
|---|---|---|
| demo01 TIC/BPC/MS1/MS2 | mzML 可读 | 整体页 TIC；详情页 MS1/MS2 |
| demo02 4D、DIA 窗口 | .d 可读 | 整体页窗口（可选）；详情页 4D 小窗（可选） |
| demo03 Q/RT/电荷/m/z 分布 | 报告统计 | 整体页仅保留简化 RT–m/z；其余**不上线** |
| demo04 MS2 标注 | 鉴定↔谱图联动 | **仅详情页** |
| demo05 XIC | 定量峰形 | **仅详情页** |

---

## 8. 数据库设计（复用 universal schema）

- 真值：`E:\viewer\docs\universal_schema.sql`  
- `datasets.analysis_mode = 'BOTTOM_UP'`  
- `peptides` + `identification_matches`（`entity_type=PEPTIDE`）  
- 不新建 `dia_*` 表  

---

## 9. 数据导入策略

- **路径导入**，不复制 mzML/.d  
- **方案 B**：Q.Value &lt; 0.01 入库，约 30–60 秒  
- 指纹去重：`source_dataset_fingerprint`  

---

## 10. URL 与前端路由

- 统一 `/datasets`，**无** `/bu/` 前缀  
- Top-Down：`/datasets/:slug/:cutoff/prsms/...`（不变）  
- Bottom-Up：  
  - 整体：`/datasets/:slug`  
  - 列表：`/proteins`、`/peptides`、`/matches`  
  - 详情：`/matches/:matchId`  
  - 蛋白：`/proteins/:proteinId`（Sequence coverage）  

---

## 11. 后端 API 设计

前缀 `/api/v1`。完整 JSON Schema 与查询参数见专项文档：

- **列表 / 概览 / 分页**：[BU列表与数据集API规范.md](./BU列表与数据集API规范.md)
- **谱图 / 色谱 / XIC / MS2**：[谱图查看说明.md](./谱图查看说明.md)（G1–G10、SpectrumV1）

| 用途 | 示例 |
|---|---|
| 整体页 QC | `GET /datasets/{slug}` + `GET .../overview`（stats 聚合） |
| 整体页 TIC | `GET /datasets/{slug}/runs/{run_id}/chromatogram?type=tic` |
| 列表 | `GET .../proteins`、`/peptides`、`/matches` |
| 详情 | `GET .../matches/{id}`、`.../xic`、`.../spectrum/ms2` |
| 蛋白 | `GET .../proteins/{id}`（含 sequence coverage） |

---

## 12. 页面与图表清单（按整体/详情拆分）

### 12.1 页面矩阵

| 页面类型 | URL | 图表？ |
|---|---|---|
| 数据集列表 | `/datasets` | 无（表格/卡片） |
| **整体页** | `/datasets/:slug` | ✅ 少量 |
| 蛋白/肽段/鉴定列表 | `.../proteins` 等 | 无（表格+筛选） |
| **鉴定详情页** | `.../matches/:id` | ✅ 核心谱图 |
| **蛋白详情页** | `.../proteins/:id` | Sequence coverage only |

### 12.2 正式站 v1 图表总表（仅 8 项）

| # | 图表 | 页面 | 组件名 |
|---|---|---|---|
| 1 | QC 统计卡片 | 整体 | `BuQcStats` |
| 2 | TIC 或 BPC | 整体 | `TicChart` / `BpcChart` |
| 3 | RT–m/z 简图（可选） | 整体 | `RtMzMiniHeatmap` |
| 4 | DIA 窗口条带（可选） | 整体 | `DiaWindowMap` |
| 5 | XIC | 详情 | `XICChart` |
| 6 | MS2 + b/y | 详情 | `BuSpectrumChart` |
| 7 | MS1 + precursor | 详情 | `BuSpectrumChart` |
| 8 | Sequence coverage | 蛋白详情 | `SequenceCoverage` |

**不上线 v1**：Q.Value 直方图、电荷分布、m/z 分布、全屏 4D 散点、scan 组成柱状图（除非二期「高级 QC」Tab）。

---

## 13. 组件复用与新写总账

| 层级 | 复用 | 新建/抄版 |
|---|---|---|
| 后端 mzML | spectrum_memory | — |
| 后端 .d | — | tdf_reader |
| 前端谱图 | — | 抄 SpectrumChart → bu-spectra |
| Top-Down | prsm 全部 | **零修改** |

---

## 14. 硬约束与改动边界

1. 不修改 Top-Down 源码  
2. 不建 `dia_*` 表  
3. 不复制原始谱图  
4. URL 不以 `/bu/` 为根  
5. 先规划后编码  

### 14.1 低耦合架构（实施时遵守）

| 边界 | 做法 |
|---|---|
| TD / BU 分叉 | 唯一门禁：`datasets.analysis_mode`（API + `DatasetModeGate`） |
| 后端 | `ingest/bu/` · `app/bu/` · `schemas/bu.py` · `api/v1/bu/` 独立；`import_jobs` 仅编排 |
| 前端 | `features/bu/**` 独立；谱图组件抄版；`features/prsm/**` 零 diff |
| 谱图 | `spectrum_facade` 统一 run 格式分支；router 不写格式 if/else |
| 契约 | [决策登记表](./决策登记表.md) 锁定；矛盾时以登记表为准 |

---

## 15. 实施里程碑

### 15.1 全链路对照（导入 · 运行时 · 前端）

| 域 | ID | 交付 | 验收 | 关联文档 |
|---|---|---|---|---|
| **导入** | M1 | DIA-NN ingest adapter + finalize | `analysis_mode=BOTTOM_UP`，`status=READY` | [Bottom-Up数据导入规划.md](./Bottom-Up数据导入规划.md) |
| **运行时** | R1 | `bu/deps` + `schemas/bu.py` | mode guard | [BU运行时后端模块规划.md](./BU运行时后端模块规划.md) |
| **运行时** | R2–R3 | scan_resolver + match 谱图 API | LLLPGELAK MS2 | 谱图查看说明 |
| **运行时** | R4–R5 | lists + overview + TIC | 列表 total ≈ 110k | BU API 规范 |
| **运行时** | R6–R7 | tdf_reader + proteins/coverage | .d 窗口；P62805 coverage | Sequence-Coverage 方案 |
| **前端** | M3 | `DatasetModeGate` + BU 路由壳 | TD/BU 分叉 | [BU前端接入规划.md](./BU前端接入规划.md) |
| **前端** | M4 | 整体页 QC + TIC + 入口 | `/datasets/:slug` | Viewer 本文 §12 |
| **前端** | M5–M6 | 详情 XIC + MS2 | matches 详情 | 谱图查看说明 |
| **前端** | M7 | Sequence coverage | 蛋白详情 | Sequence-Coverage 方案 |
| **前端** | M8 | .d 可选图 | dia-windows / 4D | 谱图查看说明 G5/G9 |

### 15.2 图表里程碑（原表）

| 阶段 | 交付 | 验收 |
|---|---|---|
| M4 | **整体页** QC + TIC + 入口 | 打开 `/datasets/:slug` 可见 |
| M5–M6 | **详情页** XIC + MS2 标注 | 从 matches 点进可见 |
| M7 | 蛋白页 Sequence coverage | 命名正确 |
| M8 | .d 可选图（整体窗口 + 详情 4D） | .d run 可用 |

---

## 16. 已确认决策清单

**19 项实施级决策**（D1–D19，含 API/ingest/运行时定稿）见 **[决策登记表.md](./决策登记表.md)**。

| # | 决策（产品级） |
|---|---|
| 1 | 完整接入 DIA-NN + mzML + .d |
| 2 | 复用 universal schema |
| 3 | 路径导入，不复制谱图文件 |
| 4 | 入库 Q.Value &lt; 0.01（见 D2） |
| 5 | URL：先 datasets，按 analysis_mode 分叉 |
| 6 | Top-Down 零修改 |
| 7 | 谱图组件抄版独立 |
| 8 | Sequence coverage 固定命名 |
| 9 | **正式站 = 整体页 + 详情页，非 demo 全图** |

---

## 17. v1 明确不支持项

以下能力 **不在 v1 范围**；文档与代码须显式声明，避免误接或半实现。与 [决策登记表 D10](./决策登记表.md) 一致。

| # | 不支持项 | 说明 | 二期 / 替代 |
|---|---|---|---|
| 1 | **`.d` run 的 match 级 MS2 / XIC** | Bruker timsTOF 目录可 **登记** 为 run、整体页可看 DIA 窗口；打开 `/matches/:id` 时 **不** 请求 MS2/XIC（或 API 返回 404 + 明确文案） | M8：`tdf_reader` + spectrum_facade |
| 2 | **PTM 专用碎片通道** | v1 MS2 标注仅 **b/y**（Stripped 序列）；不含 ox/M 等修饰离子独立通道 | 修饰序列理论碎裂扩展 |
| 3 | **`pg_matrix.tsv` / `pr_matrix.tsv` 入库** | 矩阵 TSV 仅 DIA-NN 侧车文件；v1 **不读、不入库** | 蛋白/ precursor 矩阵 API |
| 4 | **ZIP 作为 ingest 根** | `*.d.zip` 仅传输备份；v1 ingest 根须为 **已解压** 目录 + parquet + 谱图同盘（D5） | 可选「上传后服务端解压」 |
| 5 | **`*.pkl` / `*_lib.parquet`** | 谱图库与缓存 pickle；viewer 不使用 | — |
| 6 | **parquet 与谱图分盘** | ingest 根必须同时含报告与 mzML/.d（D5） | — |

### 17.1 前端守卫（低耦合）

| 场景 | 行为 |
|---|---|
| match 所属 run 为 `raw_format=bruker_d` | P5 **不 mount** `XICChart` / MS2 区；展示「v1 仅支持 mzML run 谱图」+ 摘要条仍可用 |
| 整体页选中 `.d` run | 允许 TIC 占位 / DIA 窗口（M8）；**不**预拉 match 谱图 API |
| 用户上传 `.zip` 路径 | `POST /imports` 由后端拒绝；前端 **不** 做 zip 解压 |

### 17.2 后端守卫

- `spectrum_facade`：run 格式分支在 **facade 内**；router 不复制 if/else
- ingest：`import_planner` 检测 zip-only 根 → **fail fast**，错误信息指向「请先解压 .d」

---

## 18. 附录

### 18.1 文档索引（7+7）

| # | Markdown | HTML | 主题 |
|---|---|---|---|
| 0 | **[P0-Viewer代码改造规划.md](./P0-Viewer代码改造规划.md)** | — | **C1–C31 任务清单、低耦合边界、PR 切片** |
| 1 | [Viewer接入规划-完整版.md](./Viewer接入规划-完整版.md) | `.html` | 总览、两页模型、里程碑 |
| 2 | [决策登记表.md](./决策登记表.md) | — | D1–D19 定稿 |
| 3 | [Bottom-Up数据导入规划.md](./Bottom-Up数据导入规划.md) | `.html` | ingest、字段映射 |
| 4 | [BU运行时后端模块规划.md](./BU运行时后端模块规划.md) | `.html` | 运行时服务、router |
| 5 | [BU列表与数据集API规范.md](./BU列表与数据集API规范.md) | `.html` | 列表/概览 REST |
| 6 | [谱图查看说明.md](./谱图查看说明.md) | `.html` | G1–G10、SpectrumV1 |
| 7 | [BU前端接入规划.md](./BU前端接入规划.md) | `.html` | 路由、列表、线框 |
| 8 | [Sequence-Coverage数据方案.md](./Sequence-Coverage数据方案.md) | `.html` | 蛋白序列 coverage |
| 9 | [验收测试矩阵.md](./验收测试矩阵.md) | — | E2E 验收用例 |

### 18.2 推荐阅读顺序

1. **[P0 代码改造规划](./P0-Viewer代码改造规划.md)**（实施入口）→ 2. **[决策登记表](./决策登记表.md)** → 3. **Viewer 完整版** §2–§3 → 4. **[导入规划](./Bottom-Up数据导入规划.md)** → 5. **[API 规范](./BU列表与数据集API规范.md)** + **[谱图说明](./谱图查看说明.md)**（可并行）→ 6. **[运行时规划](./BU运行时后端模块规划.md)** → 7. **[前端规划](./BU前端接入规划.md)** → 8. **[Sequence coverage](./Sequence-Coverage数据方案.md)**（M7 前）→ 9. **[验收测试矩阵](./验收测试矩阵.md)**（实施收尾）

```text
d:\dia-shuju\docs\
├── P0-Viewer代码改造规划.md          ← 实施入口（C1–C31）
├── 决策登记表.md
├── Viewer接入规划-完整版.md / .html
├── Bottom-Up数据导入规划.md / .html
├── BU运行时后端模块规划.md / .html
├── BU列表与数据集API规范.md / .html
├── 谱图查看说明.md / .html
├── BU前端接入规划.md / .html
├── Sequence-Coverage数据方案.md / .html
└── 验收测试矩阵.md
```

---

*文档 v1.4 · 决策登记表同步至 D1–D19；附录含验收测试矩阵与阅读顺序。*
