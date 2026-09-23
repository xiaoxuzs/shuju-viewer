# Bottom-Up DIA 数据导入规划

> **文档版本**：v1.1  
> **日期**：2026-05-21  
> **数据样例**：`d:\dia-shuju\`  
> **Viewer 项目**：`E:\viewer\`  
> **状态**：规划稿（确认后实施）  
> **关联文档**：[P0-Viewer代码改造规划.md](./P0-Viewer代码改造规划.md)（C1–C31 实施清单）、[Viewer接入规划-完整版.md](./Viewer接入规划-完整版.md)（页面 / API / 图表）、[BU运行时后端模块规划.md](./BU运行时后端模块规划.md)（§13 运行时服务 / router）

---

## 目录

1. [文档目的](#1-文档目的)
2. [导入原则（与 Top-Down 对齐）](#2-导入原则与-top-down-对齐)
3. [你的数据目录长什么样](#3-你的数据目录长什么样)
4. [推荐的 ingest 根目录布局](#4-推荐的-ingest-根目录布局)
5. [导入总流程（路径导入）](#5-导入总流程路径导入)
6. [ingest 根解析（扩展 resolve_ingest_root）](#6-ingest-根解析扩展-resolve_ingest_root)
7. [Import Planner 扩展](#7-import-planner-扩展)
8. [Parquet → universal schema 字段映射](#8-parquet--universal-schema-字段映射)
9. [Run 发现与谱图绑定](#9-run-发现与谱图绑定)
10. [Scan 号策略（入库 vs 按需解析）](#10-scan-号策略入库-vs-按需解析)
11. [过滤与入库规模（方案 B）](#11-过滤与入库规模方案-b)
12. [导入阶段与进度条](#12-导入阶段与进度条)
13. [后端模块划分（新增文件）](#13-后端模块划分新增文件)
14. [capabilities 与 extra_metadata 约定](#14-capabilities-与-extra_metadata-约定)
15. [导入命令与 API](#15-导入命令与-api)
16. [验收清单](#16-验收清单)
17. [已定稿决策（D1–D5）](#17-已定稿决策d1d5)
18. [数据库索引（必建）](#18-数据库索引必建)

---

## 1. 文档目的

本文只回答一件事：**Bottom-Up DIA 数据如何从磁盘进入 `E:\viewer` 的 PostgreSQL（universal 7 表）**。

不包含前端页面线框、谱图 API 细节——那些见 [Viewer接入规划-完整版.md](./Viewer接入规划-完整版.md)。

---

## 2. 导入原则（与 Top-Down 对齐）

| 原则 | Bottom-Up 做法 | 理由 |
|---|---|---|
| **路径导入，不复制大文件** | `datasets.source_root` 指向用户选的目录；mzML / `.d` 保持原位 | 与 Top-Down 一致；1.3 GB mzML 不能进 DB |
| **谱图峰不入库** | 只写 `runs.file_path`；详情页用 `spectrum_memory` 按需读 | 现有 Top-Down fast 模式已验证 |
| **鉴定摘要入库，详情按需** | parquet 行 → `identification_matches`；b/y 标注在打开详情时算 | demo_04 已证明可行 |
| **复用 universal schema** | `analysis_mode=BOTTOM_UP`，不建 `dia_*` 表 | schema 已预留 |
| **指纹去重** | 复用 `back/app/fingerprint/` | AGENTS.md 硬约束 |
| **薄编排** | `import_jobs` 只编排；算法在 `back/app/ingest/bu/` | AGENTS.md 硬约束 |
| **Top-Down 零修改** | 新 adapter + planner 分支；不改 `universal_toppic_adapter` | 已确认决策 |

---

## 3. 你的数据目录长什么样

当前 `d:\dia-shuju\` 实测结构（**扁平混放**，可直接作为 ingest 根）：

```text
d:\dia-shuju\
├── 20200110_Hela_500ng_DIA_25cm_120min_R1.mzML     # 1.34 GB · Thermo DIA（单文件）
├── DC2817_ELB00124_DIA_H00BP43_P05_A12_13560.d/    # Bruker timsTOF · 本身就是文件夹（见 §3.1）
├── DC2817_ELB00124_DIA_H00BP43_P05_A12_13560.d.zip # 同上目录的 zip 备份（传输用，可删）
├── DIANN_2.0\
│   └── DIANN_2.0\
│       ├── all_report.parquet                        # 36 MB · 主报告（323,232 行）
│       ├── target_report.parquet                     # 12 MB · 迭代精炼版
│       ├── all_report.stats.tsv                      # QC 统计 → 整体页卡片
│       ├── all_report.protein_description.tsv        # 蛋白注释
│       ├── all_report.pg_matrix.tsv                  # 蛋白定量矩阵（v1 不入库）
│       ├── all_report.pr_matrix.tsv                  # precursor 定量矩阵（v1 不入库）
│       ├── *.pkl                                     # ❌ 忽略
│       └── all_lib.parquet / target_lib.parquet      # ❌ v1 忽略（谱图库，viewer 不用）
```

**角色划分**

| 文件 | 导入阶段 | 运行时 |
|---|---|---|
| `all_report.parquet` | ✅ 读入 → 写 DB | 列表 / 筛选 / 详情索引 |
| `all_report.stats.tsv` | ✅ 读入 → `datasets.extra_metadata` | 整体页 QC 卡片 |
| `all_report.protein_description.tsv` | ✅ 读入 → `proteins.description` | 蛋白列表 / 详情 |
| `*.mzML` / `*.d` | ✅ 登记 → `runs` | TIC / MS1 / MS2 / XIC / 4D |
| `*.pkl` | ❌ | — |
| `*_matrix.tsv` | ❌ v1 | 二期多样本矩阵视图 |

### 3.1 Bruker `.d` 是什么？要不要「解压」？

**结论**：`.d` **本来就是文件夹**，不是像 `.mzML` 那样的单文件；仪器导出时目录名就以 `.d` 结尾。  
**不需要**对 `.d` 文件夹本身再做任何「解压」操作。

| 形态 | 说明 | 你的目录里 |
|---|---|---|
| `xxx.d/` | Bruker 原始数据**目录**（含 `analysis.tdf` 等） | ✅ 已有 |
| `xxx.d.zip` | 把上述目录打成 zip，便于拷贝/传输 | ✅ 也有（约 1.53 GB，可保留作备份） |

「解压」仅指：若你**只拿到** `xxx.d.zip`，需要先解压 zip 才能得到 `xxx.d/` 文件夹。  
你这边 **zip 已解压过**，文件夹可直接用。

**与 mzML 对比**

| | Thermo mzML | Bruker `.d` |
|---|---|---|
| 形态 | 单个文件 | **文件夹** |
| 能否直接读 | 是 | 是（读文件夹内 `analysis.tdf` + `analysis.tdf_bin`） |
| 何时需要 unzip | 不需要 | 仅当收到的是 `.d.zip` 时，解压 zip |

#### 3.1.1 实测：你的 `.d` 多嵌套了一层（重要）

zip 解压后常见「外层壳 + 内层真实数据」结构。你当前磁盘实测：

```text
DC2817_ELB00124_DIA_H00BP43_P05_A12_13560.d/          ← 外层（zip 解压产物）
├── analysis.tdf                                      ← 0 字节，空文件，忽略
└── DC2817_ELB00124_DIA_H00BP43_P05_A12_13560.d/      ← 内层，真实数据在这里
    ├── analysis.tdf               (33 MB)
    ├── analysis.tdf_bin           (1.57 GB)           ← 谱图主体
    ├── chromatography-data.sqlite
    ├── SampleInfo.xml
    └── 13560.m/
```

**导入 / 读谱时必须用内层路径**（或让 `run_discovery` 自动下钻，见 §9）：

```text
d:\dia-shuju\DC2817_ELB00124_DIA_H00BP43_P05_A12_13560.d\DC2817_ELB00124_DIA_H00BP43_P05_A12_13560.d\
```

`run_discovery.py` 规则（v1）：

1. 发现 `*.d/` 目录后，若**当前层** `analysis.tdf` 非空且同目录有 `analysis.tdf_bin` → 即有效 run 根  
2. 否则若存在**唯一**同名子目录 `xxx.d/xxx.d/` 且内层含有效 `analysis.tdf` → 自动改用内层  
3. 外层 0 字节 `analysis.tdf` 不参与校验

---

## 4. 推荐的 ingest 根目录布局

### 4.1 现状：直接导入 `d:\dia-shuju\`

**v1 支持**：resolver 在根目录下同时找到「DIA-NN 报告」+「至少一个谱图文件」即视为合法 BU ingest 根。

判定规则（见 §6）：

- 存在 `**/all_report.parquet` 或 `**/target_report.parquet`
- 且存在 `*.mzML` / `*.mzml` 或 `*.d/` 目录

### 4.2 可选：规范化子目录（二期友好）

若以后多样本混放，可整理为：

```text
<ingest_root>/
├── diann/
│   ├── all_report.parquet
│   ├── all_report.stats.tsv
│   └── all_report.protein_description.tsv
└── spectra/
    ├── sample_A.mzML
    └── sample_B.d/
```

resolver **两种布局都识别**；指纹对整个 ingest 根做 manifest MD5。

---

## 5. 导入总流程（路径导入）

与现有 Top-Down 路径导入共用 `POST /api/v1/imports` → `run_path_import_job`，仅在 **planner 分叉** 后走 BU adapter。

```text
用户提交 source_path（如 d:\dia-shuju）
        │
        ▼
resolve_ingest_root()          ← 扩展：识别 TopPIC **或** DIA-NN 布局
        │
        ▼
compute_dataset_metadata_fingerprint()   ← 复用，≤0.5s
        │
        ▼
find_dataset_with_fingerprint()            ← 重复则拒绝
        │
        ▼
plan_ingest()                  ← 扩展：DatasetShape.DIANN_DIA
        │
        ├── TOPPIC_HTML  → ingest_universal_toppic()      （现有）
        ├── PRSM_BUNDLE  → ingest_universal_prsm_js()     （现有）
        └── DIANN_DIA    → ingest_universal_diann()       （新增）
        │
        ▼
finalize：写 source_root、source_dataset_fingerprint、capabilities
        │
        ▼
datasets.status = READY
```

**与 ZIP 导入的关系**：v1 **只做路径导入**；ZIP 解压后可指向解压目录，但不专门为 BU 写解压逻辑。

---

## 6. ingest 根解析（扩展 resolve_ingest_root）

**现状**（`E:\viewer\back\app\dataset_ingest_root\resolver.py`）只认 TopPIC 标志目录。

**扩展方案**：新增 `has_bu_diann_layout(path)`，与 TopPIC 并列：

```python
def has_bu_diann_layout(path: Path) -> bool:
    if not path.is_dir():
        return False
    has_parquet = any(path.rglob("all_report.parquet")) or any(path.rglob("target_report.parquet"))
    has_spectra = (
        any(path.rglob("*.mzML")) or any(path.rglob("*.mzml"))
        or any(p for p in path.rglob("*.d") if p.is_dir())
    )
    return has_parquet and has_spectra
```

`find_ingest_root()` 优先级：

1. 当前目录同时满足 TopPIC **或** BU → 返回当前目录  
2. 子目录中**恰好一个**匹配 → 返回该子目录  
3. 多个匹配 → `ValueError`（与 TopPIC 行为一致）  
4. TopPIC 与 BU **不可同时**出现在同一 ingest 根（避免歧义）

---

## 7. Import Planner 扩展

**文件**：`E:\viewer\back\app\services\import_planner\planner.py`

新增 `DatasetShape.DIANN_DIA` 与分支：

```python
def plan_ingest(ingest_root: Path) -> ImportPlan:  # 由 plan_zip_ingest 重命名或包装
    if is_toppic_html_tree(root):
        ...  # 现有
    if has_bu_diann_layout(root):
        return ImportPlan(
            shape=DatasetShape.DIANN_DIA,
            spectra_source=detect_bu_spectra_source(root),  # mzml_memory | tdf_memory | mixed
            need_toppic_multirun_pass=False,
        )
    ...
```

`detect_bu_spectra_source`：

| 磁盘内容 | `capabilities.spectra_source` |
|---|---|
| 仅有 mzML | `mzml_memory` |
| 仅有 `.d` | `tdf_memory`（新值，与 Top-Down 的 topfd_js 区分） |
| 两者都有 | `mixed`（runs 表分 run 标记各自来源） |

---

## 8. Parquet → universal schema 字段映射

**主报告选择（v1 默认）**：`all_report.parquet`  
（`target_report.parquet` 作为 `extra_metadata.refined_report_path` 登记，v1 不二次入库）

### 8.1 `datasets`

| DB 列 | 值 |
|---|---|
| `analysis_mode` | `BOTTOM_UP` |
| `source_software` | `DIA-NN_2.0` |
| `source_root` | ingest 根绝对路径 |
| `status` | 导入完成后 `READY` |
| `capabilities` | 见 §14 |
| `extra_metadata` | stats.tsv 摘要、parquet 路径、过滤阈值、行数统计 |

### 8.2 `runs`（每个谱图文件一行）

| DB 列 | `*.mzML` | `*.d/` |
|---|---|---|
| `file_path` | 绝对路径 | 绝对路径（`resolve_bruker_tdf_root()` 内层根） |
| `file_name` | 文件名 | 目录名 |
| `analysis_mode` | `BOTTOM_UP` | `BOTTOM_UP` |
| `software` | `DIA-NN_2.0` | `DIA-NN_2.0` |
| `status` | `IMPORTED` → finalize 后 `READY` | `IMPORTED` → finalize 后 `READY` |
| `run_metadata` | `{ "raw_format": "mzml", "diann_run_name": "<Run列值>" }` | `{ "raw_format": "bruker_d", "tdf_path": "<内层根绝对路径>" }` |

导入时 **直接写 canonical `run_metadata`**（与 API `bu_runs.raw_format` 一致），不做 `format` → `raw_format` 二次映射。

**Finalize（数据集级，与 §8.1 同步）**：全部 runs 登记完成后，`datasets.analysis_mode=BOTTOM_UP`，`source_software=DIA-NN_2.0`，`status=READY`。

**Run 名对齐**：parquet 的 `Run` 列（如 `20200110_Hela_...R1`）与 mzML 文件名做**规范化匹配**（去扩展名、大小写不敏感、可选去路径前缀）。匹配失败 → **警告 + 单 run fallback**；**多 run 且无匹配 → 导入失败**（[决策登记表 D11](./决策登记表.md)）。

### 8.3 `proteins`

从 parquet 的 `Protein.Group` 拆分为多个 accession（`;` 分隔）：

| DB 列 | Parquet / 外部 |
|---|---|
| `accession` | 单个 UniProt ID；蛋白组拆成多行，组内共享 `extra_metadata.protein_group` |
| `gene_name` | `Genes`（若有） |
| `description` | `all_report.protein_description.tsv` |
| `is_decoy` | **按 accession 逐条判定**：target accession → `false`；纯 decoy accession → `true`。蛋白组 `A;B` 拆多行时各行独立，**不**采用「组内任一 decoy 则全组 false」。优先读 parquet 行级 **`Decoy`** 列（`Decoy==1` 且无配对 target）；无该列时 fallback accession 前缀/命名（如 `rev_`） |
| `extra_metadata` | `pg_max_lfq`, `pg_q_value`, `pg_quantity`, `protein_group`（原始 `Protein.Group` 字符串） |

**蛋白组 vs 单 accession**：一个 `Protein.Group` 含 `P62805;Q71DI3` 时入库 **2 条 protein**，通过 `protein_relation_mapping` 指向同一肽段。

### 8.4 `peptides`

| DB 列 | Parquet |
|---|---|
| `sequence` | `Stripped.Sequence` |
| `theoretical_mass` | 由序列计算或 `Precursor.Mz * charge - proton` 反推 |
| `length` | `len(sequence)` |
| `extra_metadata` | `Modified.Sequence` 模板（可选） |

去重键：`(dataset_id, sequence)`。

### 8.5 `identification_matches`（核心，一行 = 一条 precursor 鉴定）

| DB 列 | Parquet 列 | 说明 |
|---|---|---|
| `run_id` | `Run` | 映射到 §8.2 |
| `scan_number` | — | **v1 填 `-1`**，见 §10 |
| `spectrum_native_id` | — | NULL；详情页按需解析 |
| `retention_time` | `RT` | 单位：分钟（与 demo 一致） |
| `ms_level` | 固定 `2` | DIA 鉴定对应 MS2 |
| `entity_type` | 固定 `PEPTIDE` | |
| `entity_id` | → `peptides.peptide_id` | |
| `modified_sequence` | `Modified.Sequence` | 前端展示 |
| `experimental_mass` | 由 `Precursor.Mz` + `Precursor.Charge` 算 | |
| `precursor_mz` | `Precursor.Mz` | |
| `precursor_charge` | `Precursor.Charge` | |
| `intensity` | `Precursor.Quantity` 或 `Ms2.Area` | |
| `score` | `Global.Q.Value` 或 `Q.Value` | |
| `q_value` | `Q.Value` | 过滤主键 |
| `is_decoy_match` | `Decoy == 1` | |
| `search_engine` | `DIA-NN` | |
| `detail_path` | NULL | BU 无 per-row 详情文件 |
| `extra_metadata` | 见下表 | |

**`extra_metadata` 建议保留的 DIA-NN 列**（其余 69 列中未映射的放这里，避免丢信息）：

| 键 | Parquet 列 |
|---|---|
| `precursor_id` | `Precursor.Id` |
| `rt_start` / `rt_stop` | `RT.Start` / `RT.Stop` |
| `ms2_scan` | `MS2.Scan`（若有；Thermo 常为空） |
| `lib_qvalue` | `Lib.Q.Value` |
| `mass_accuracy` | `Mass.Evidence` / `Mass.Acc` 等 |
| `protein_group` | `Protein.Group` |
| `genes` | `Genes` |

### 8.6 `protein_relation_mapping`

每条 `identification_match` 对其 `Protein.Group` 中每个 accession 写一行：

| 列 | 值 |
|---|---|
| `protein_id` | 对应 accession 的 protein_id |
| `entity_type` | `PEPTIDE` |
| `entity_id` | peptide_id |
| `start_position` / `end_position` | v1 **NULL**（二期用 UniProt 序列算 coverage） |
| `is_unique` | v1 false |

---

## 9. Run 发现与谱图绑定

```text
ingest_root 递归扫描（不跟随符号链接，与指纹模块一致）
        │
        ├── *.mzML / *.mzml  → runs (+ register in spectrum_memory wiring)
        └── *.d/ 目录        → resolve_bruker_tdf_root()（§3.1.1 处理嵌套）
                → runs.file_path 写「有效 run 根」绝对路径
                → 导入期只验证 analysis.tdf + analysis.tdf_bin 存在
```

**`.d` 有效 run 根判定**（`run_discovery.resolve_bruker_tdf_root(d_path)`）：

```python
def is_valid_bruker_root(p: Path) -> bool:
    tdf = p / "analysis.tdf"
    return tdf.is_file() and tdf.stat().st_size > 0 and (p / "analysis.tdf_bin").is_file()

def resolve_bruker_tdf_root(outer: Path) -> Path:
    if is_valid_bruker_root(outer):
        return outer
    inner = outer / outer.name  # 常见 zip 解压嵌套：xxx.d/xxx.d/
    if inner.is_dir() and is_valid_bruker_root(inner):
        return inner
    raise ValueError(f"no valid Bruker TDF root under {outer}")
```

**校验（导入期，不读全谱）**：

- mzML：用 pyteomics 读 `index` / 首个 spectrum，确认可打开  
- `.d`：对 `resolve_bruker_tdf_root()` 返回的路径确认 `analysis.tdf`（非空）+ `analysis.tdf_bin` 存在  

**不做的**：全文件 TIC 预计算、MS2 全索引（留给首次打开详情页 / spectrum_memory 懒加载）。

---

## 10. Scan 号策略（入库 vs 按需解析）

DIA-NN parquet **通常不含可靠 MS2 scan 号**（demo_04 是在运行时扫 mzML 定位）。

| 策略 | v1 采用 | 说明 |
|---|---|---|
| A. 导入期全量预匹配 scan | ❌ | 110k 行 × 扫 mzML ≈ 数小时 |
| B. 入库 RT+m/z+charge，详情页按需匹配 | ✅ | demo_04 算法，<1s/条 |
| C. 仅导入期对 Top N 强峰预匹配 | 🟡 二期 | 可选加速 |

**v1 约定**：

- `identification_matches.scan_number = -1`（与 Top-Down fast 模式占位一致）  
- 详情 API `GET .../matches/{id}/spectrum/ms2` 内部调用 `bu/services/scan_resolver.py`：  
  - 输入：run_id, RT, precursor_mz, charge  
  - 算法：demo_04（RT ±0.5 min + isolation window 包含 precursor）  
  - 输出：scan_number + peaks → 再算 b/y  

可选：首次解析后写 `extra_metadata.resolved_scan` 缓存，避免重复扫 mzML。

---

## 11. 过滤与入库规模（方案 B）

| 方案 | 条件 | 行数 | 导入时间（估） |
|---|---|---|---|
| A 全量 | 无 | 323,232 | ~2–3 min |
| **B 推荐** | `Decoy==0` 且 `Q.Value < 0.01` | **110,026** | **30–60 s** |
| C 更严 | Q.Value < 0.001 | ~85k | ~40 s |

**v1 默认方案 B**；阈值写入 `datasets.extra_metadata.q_value_cutoff = 0.01`，前端 Matches 列表可复用该默认值。

导入时 **不读** `*.pkl`、`**_matrix.tsv`、`**_lib.parquet`。

---

## 12. 导入阶段与进度条

与 Top-Down 共用 `import_jobs` 阶段码，BU 专用 label：

| stage | stage_label | progress 区间 | 动作 |
|---|---|---|---|
| `queued` | 排队中 | 0 | — |
| `fingerprint` | 计算指纹 | 0–8 | 复用 fingerprint 模块 |
| `init` | 初始化数据集 | 8–12 | 写 datasets、读 stats.tsv |
| `runs` | 登记谱图文件 | 12–18 | 扫描 mzML/.d → runs |
| `proteins` | 导入蛋白 | 18–35 | protein_description + Protein.Group 去重 |
| `peptides` | 导入肽段 | 35–50 | Stripped.Sequence 去重 |
| `matches` | 导入鉴定 | 50–92 | 流式读 parquet → batch insert |
| `finalize` | 收尾 | 92–100 | capabilities、commit、READY |

`stage_detail` 示例：`导入鉴定 45000/110026`（batch 每 5000 行更新一次）。

### 12.1 前端进度 UI（DatasetsPage）

与 [BU前端接入规划 §10](./BU前端接入规划.md#10-导入-ui-与进度条) 对齐：

| 职责 | 归属 |
|---|---|
| stage 枚举与 progress 计算 | 后端 `import_jobs` + `ingest/bu/*` |
| 中文 label 映射 | 前端单一常量 `IMPORT_STAGE_LABELS` |
| 轮询与跳转 | 共用 DatasetsPage；**不**在 BU 路由树重复实现 |

API 响应字段（与 TD 共用 job 模型）：

```json
{
  "job_id": "uuid",
  "status": "running",
  "stage": "matches",
  "stage_label": "导入鉴定",
  "stage_detail": "导入鉴定 45000/110026",
  "progress": 72
}
```

`stage_label` 可由后端填充（与上表一致）；前端优先用本地映射表，后端 label 作 fallback。

---

## 13. 后端模块划分（新增文件）

遵循 `E:\viewer\AGENTS.md`，**不**把逻辑堆进 `import_jobs.py`：

```text
E:\viewer\back\app\
├── dataset_ingest_root\
│   └── resolver.py              # 改：+ has_bu_diann_layout
├── services\import_planner\
│   ├── planner.py               # 改：+ DIANN_DIA 分支
│   └── detectors.py             # 改：+ detect_bu_spectra_source
├── ingest\
│   └── bu\                      # 新建包
│       ├── __init__.py
│       ├── universal_diann_adapter.py   # 主入口 ingest_universal_diann()
│       ├── diann_parquet_reader.py      # 流式读 parquet + 过滤
│       ├── diann_field_mapping.py       # 列名 → DB 字段
│       ├── run_discovery.py             # 扫描 mzML/.d + resolve_bruker_tdf_root()
│       ├── protein_description_reader.py
│       └── stats_reader.py
├── services\
│   └── import_jobs.py           # 改：+ elif plan.shape == DIANN_DIA
└── bu\                          # 运行时服务（非 ingest，见 BU运行时后端模块规划.md）
    ├── services\
    │   ├── scan_resolver.py
    │   ├── theoretical_fragments.py
    │   └── xic_service.py
    ├── tdf_reader\              # Bruker .d 读取
    └── （api/v1/bu/ router 挂载）
```

**批量写入**：`identification_matches` 用 `executemany` 或 `COPY`，每批 5000 行；`proteins` / `peptides` 先内存去重再 insert。

---

## 14. capabilities 与 extra_metadata 约定

### `datasets.capabilities`（BU 示例）

```json
{
  "spectra_source": "mzml_memory",
  "has_ms1": true,
  "has_ms2": true,
  "has_im": false,
  "has_dia_windows": true,
  "analysis_shape": "bottom_up_dia",
  "import_mode": "diann_parquet",
  "entity_types": ["PEPTIDE"],
  "list_routes": ["proteins", "peptides", "matches"]
}
```

若含 `.d` run：`has_im: true`, `spectra_source: "mixed"`。

### `datasets.extra_metadata`（BU 示例）

```json
{
  "q_value_cutoff": 0.01,
  "parquet_path": "DIANN_2.0/DIANN_2.0/all_report.parquet",
  "stats": { "File.Name": "...", "Precursors.ID": 110026, "...": "..." },
  "import_stats": {
    "parquet_total_rows": 323232,
    "imported_matches": 110026,
    "unique_peptides": 92704,
    "unique_protein_groups": 8063
  }
}
```

---

## 15. 导入命令与 API

### 15.1 HTTP API（与 Top-Down 相同入口）

```http
POST /api/v1/imports
Content-Type: application/json

{
  "source_path": "d:\\dia-shuju",
  "slug": "hela_dia_20200110",
  "name": "HeLa DIA 500ng R1",
  "description": "DIA-NN 2.0 all_report, Q<0.01"
}
```

轮询 `GET /api/v1/imports/{job_id}` → 成功后打开 `/datasets/hela_dia_20200110`。

### 15.2 CLI（开发 / 调试，与 toppic adapter 对称）

```powershell
cd E:\viewer\back

uv run python -m app.ingest.bu.universal_diann_adapter `
  --root "d:\dia-shuju" `
  --slug hela_dia_20200110 `
  --name "HeLa DIA 500ng R1" `
  --parquet "DIANN_2.0\DIANN_2.0\all_report.parquet" `
  --q-value-max 0.01 `
  --replace
```

---

## 16. 验收清单

导入完成后，在 psql 或 API 中验证：

| # | 检查项 | 期望 |
|---|---|---|
| 1 | `datasets.analysis_mode` | `BOTTOM_UP` |
| 2 | `datasets.source_dataset_fingerprint` | 32 位 hex，重复导入被拒绝 |
| 3 | `runs` 行数 | = mzML 文件数 + `.d` 目录数 |
| 4 | `identification_matches` 行数 | ≈ 110,026（Q&lt;0.01） |
| 5 | `peptides` 去重 | ≈ 92,704 |
| 6 | `proteins` | ≥ 8,000（蛋白组拆分后可能略多） |
| 7 | 任意 match 详情 API | MS2 能返回峰列表 + b/y（scan 按需解析） |
| 8 | Top-Down 回归 | 原 histone 数据集导入 / 打开不受影响 |

---

## 17. 已定稿决策（D1–D5）

> 完整 19 项见 [决策登记表.md](./决策登记表.md)。

| # | 问题 | 定稿 | 状态 |
|---|---|---|---|
| D1 | 用 `all_report` 还是 `target_report` 入库？ | v1 **all_report**（`target_report` 仅登记路径） | ✅ |
| D2 | Q.Value 阈值固定 0.01 还是 UI 可选？ | 导入固定 0.01；列表可再筛 | ✅ |
| D3 | 蛋白组 `A;B;C` 拆成 3 条 protein 还是 1 条？ | **拆成多条** + mapping | ✅ |
| D4 | 同时有 mzML 和 `.d` 两个 run 时默认展示哪个？ | 整体页 run 下拉，默认 mzML | ✅ |
| D5 | ingest 根是否允许只有 parquet、谱图在外层别的盘？ | v1 **不允许**（必须同 ingest 根下） | ✅ |

---

## 18. 数据库索引（必建）

> **决策 D18**：列表性能为硬性要求；约 11 万行 `identification_matches` 无复合索引时，Matches/肽段列表会全表扫描。**M1 ingest 完成后、R4 列表 API 上线前** 必须通过 migration 建好下表索引（P0 C4）。

### 18.0 与 schema 基线的关系

| 层级 | 内容 |
|---|---|
| **基线已有** | `ix_identification_matches_entity` → `(dataset_id, entity_type, entity_id)`；`ix_identification_matches_dataset_run_scan` → `(dataset_id, run_id, scan_number)`；`ix_identification_matches_q_value` → **仅**单列 `q_value`（对「先限定 dataset 再按 Q 筛」帮助有限） |
| **BU migration 必增** | **`(dataset_id, q_value)`**、**`(dataset_id, run_id)`**（见 §18.1） |
| **禁止** | 在 ingest adapter 或 list service 运行时 `CREATE INDEX` |

### 18.1 必建索引

| 表 | 索引 | 优先级 | 用途 |
|---|---|---|---|
| `identification_matches` | **`(dataset_id, q_value)`** | **P0 必建** | Matches 列表默认 `q_max` 过滤 + 按 Q 排序（最高频） |
| `identification_matches` | **`(dataset_id, run_id)`** | **P0 必建** | 整体页按 run 筛 matches；比三列 `(dataset_id, run_id, scan_number)` 更贴合列表 SQL |
| `identification_matches` | `(dataset_id, entity_type, entity_id)` | 基线已有 | 肽段 / 蛋白 → matches 聚合；migration **无需重复创建** |
| `identification_matches` | `match_id` PK | 基线已有 | 详情 `GET .../matches/{id}` |

### 18.2 SQL 示例（PostgreSQL）

```sql
-- BU migration：仅创建基线尚未覆盖的复合索引（D18）
CREATE INDEX IF NOT EXISTS idx_im_dataset_q
  ON identification_matches (dataset_id, q_value);

CREATE INDEX IF NOT EXISTS idx_im_dataset_run
  ON identification_matches (dataset_id, run_id);
```

### 18.3 验收与低耦合

- 索引 **只** 在 migration 中定义；`bu/services/list_queries.py` 只写查询 SQL
- **必须通过**：[验收测试矩阵 §5.2 #6](./验收测试矩阵.md#52-数据集-apim3m4) — `EXPLAIN ANALYZE` 对 `GET .../matches?q_max=0.01` 显示 **Index Scan**（或 Bitmap Index Scan），禁止 Seq Scan 扫全表
- 目标：列表首屏 API **&lt; 500ms**（与 [BU前端接入规划 §7.3](./BU前端接入规划.md#73-性能预算) 一致）；未建索引不得上线 R4

---

## 附录：与 Top-Down 导入对照

| 步骤 | Top-Down | Bottom-Up |
|---|---|---|
| 根解析 | `toppic_prsm_cutoff/` | `all_report.parquet` + mzML/.d |
| 主文件 | `proteins.js` | `all_report.parquet` |
| 实体 | proteoform + PrSM | peptide + precursor match |
| 详情文件 | `prsm*.js` → detail_path | 无；parquet 行 + 按需读谱 |
| scan | PrSM header / 按需 | RT+m/z 按需匹配 |
| 谱图源 | topfd_js / mzml_memory | mzml_memory / tdf_memory |

---

*文档 v1.2 · Bottom-Up 数据导入专项规划 · §12.1 前端进度 UI、§18 索引必建（D18）。*
