# Sequence Coverage 数据方案

> **文档版本**：v1.0  
> **日期**：2026-05-21  
> **数据样例**：`d:\dia-shuju\`（DIA-NN 2.0 · `all_report.parquet`）  
> **Viewer 项目**：`E:\viewer\`  
> **状态**：已确认（§8 推荐方案），可进入 M7 实施  
> **关联文档**：[Bottom-Up数据导入规划.md](./Bottom-Up数据导入规划.md) · [谱图查看说明.md](./谱图查看说明.md) · [BU前端接入规划.md](./BU前端接入规划.md)

---

## 目录

1. [文档目的](#1-文档目的)
2. [问题定义](#2-问题定义)
3. [数据流总览](#3-数据流总览)
4. [base_sequence 来源](#4-base_sequence-来源)
5. [肽段定位算法](#5-肽段定位算法)
6. [API 与 DB 契约](#6-api-与-db-契约)
7. [v1 降级策略](#7-v1-降级策略)
8. [已确认决策](#8-已确认决策)
9. [实施分期与验收](#9-实施分期与验收)

---

## 1. 文档目的

蛋白详情页的 **Sequence coverage**（组件名固定为 `SequenceCoverage`，标题固定为「Sequence coverage」）需要在一条蛋白序列上高亮被鉴定肽段的覆盖区间。

本文只回答三件事：

| 主题 | 本文回答 |
|---|---|
| **base_sequence 从哪来** | 写入 `proteins.base_sequence` 的来源、优先级、缓存 |
| **肽段如何定位** | 肽段序列 → 在蛋白序列上的 `[start, end)` 区间算法 |
| **v1 降级策略** | 缺序列 / 定位失败 / 多重匹配时前端与 API 如何表现 |

不包含：MS1/MS2 谱图、XIC、列表页筛选——见 [谱图查看说明.md](./谱图查看说明.md)。

---

## 2. 问题定义

### 2.1 输入（已有）

| 来源 | 字段 | 说明 |
|---|---|---|
| DIA-NN parquet | `Stripped.Sequence` | 无修饰肽段序列，已入库 `peptides.sequence` |
| DIA-NN parquet | `Protein.Group` | 蛋白组；导入时拆成多条 `proteins.accession` |
| DIA-NN parquet | `Modified.Sequence` | 展示用，**不参与**定位 |
| DB | `protein_relation_mapping` | 蛋白 ↔ 肽段归属（v1 导入时 `start_position` / `end_position` 为 NULL） |

### 2.2 输出（目标）

蛋白详情 API 需返回：

```json
{
  "accession": "P62805",
  "base_sequence": "MARTKQTARKSTGGKAPRKQLATKAARKSAPATGGVKKPHRYRPGTVALRE...",
  "coverage_mode": "full",
  "coverage_percent": 0.42,
  "coverage_segments": [
    { "start": 12, "end": 22, "peptide_id": 1001, "sequence": "STGGKAPRKQL", "is_ambiguous": false }
  ],
  "peptides": [ "..." ]
}
```

### 2.3 当前数据缺口（实测 `d:\dia-shuju`）

| 检查项 | 结果 | 影响 |
|---|---|---|
| parquet 69 列中是否有肽段起始/终止位置 | ❌ 无 `Start`/`End`/`Position` 类列 | 必须靠序列比对 |
| `Protein.Sites` 列 | 列存在，**323,232 行均为空字符串** | 不能用于肽段定位 |
| `all_report.protein_description.tsv` 的 `Sequence` 列 | 20,397 行，**非空 0 行** | 不能作为 v1 主来源 |
| `proteins.base_sequence`（Top-Down 现状） | 导入时写 **NULL** | BU 需新建填充逻辑 |

**结论**：Sequence coverage 的核心依赖是 **外部蛋白全长序列**（推荐 UniProt），而不是 DIA-NN 报告本身。

---

## 3. 数据流总览

```text
导入期                          打开蛋白详情页（运行时）
────────                        ────────────────────────
parquet                         GET .../proteins/{id}
  Protein.Group ──► proteins          │
  Stripped.Sequence ──► peptides    ├─► 读 proteins.base_sequence
  mapping ──► protein_relation_mapping│       │
                                      │       ├─ 有值 → 直接用
UniProt / FASTA / description.tsv     │       └─ NULL → 按 §4 解析并回写 DB
  ──► proteins.base_sequence          │
                                      ├─► 查该蛋白下属肽段（peptides + mapping）
                                      ├─► §5 定位算法 → coverage_segments[]
                                      └─► 返回 JSON → SequenceCoverage.tsx 渲染
```

**原则**（与 [Bottom-Up数据导入规划.md](./Bottom-Up数据导入规划.md) 一致）：

- 蛋白详情页 **不读 mzML / .d**  
- 定位在 **后端** 完成；前端只消费 `coverage_segments`  
- 导入期 **不** 对 110k match 全量预定位（与 scan 策略相同：详情按需）

---

## 4. base_sequence 来源

### 4.1 写入目标

| DB 列 | 含义 | 格式约定 |
|---|---|---|
| `proteins.base_sequence` | 理论未修饰氨基酸序列 | 大写单字母码 `A-Z`；不含空格/换行 |
| `proteins.extra_metadata.sequence_source` | 序列来源标记 | 见下表 |
| `proteins.extra_metadata.sequence_length` | 冗余长度 | `len(base_sequence)` |

### 4.2 来源优先级（已确认）

按顺序尝试，**首个成功即停止**：

| 优先级 | 来源 | 触发时机 | `sequence_source` | 备注 |
|---|---|---|---|---|
| P1 | 用户随数据提供的 FASTA | 导入 | `user_fasta` | 见 §4.3 |
| P2 | `all_report.protein_description.tsv` → `Sequence` | 导入 | `diann_description` | 列存在但当前样例全空 |
| P3 | **UniProt REST** `GET /uniprot/uniprotkb/{accession}.fasta` | 详情页懒加载 + DB 回写 | `uniprot` | **v1 主路径** |
| P4 | 无 | — | `missing` | 触发 §7 降级 |

**异构体 / 截断**：v1 只取 UniProt **canonical**（FASTA 第一条）。isoform 选择放二期。

**Decoy**：若 `proteins.is_decoy = true`，**不请求 UniProt**；`base_sequence` 保持 NULL，`coverage_mode = "decoy"`。

### 4.3 可选：ingest 根 FASTA 布局

```text
<ingest_root>/
├── DIANN_2.0/...
├── *.mzML
└── reference/                    # 可选
    └── uniprot_human.fasta       # 或 dataset.fasta
```

解析规则（v1）：

1. 若 ingest 根下存在**唯一** `**/*.fasta` 或 `**/*.fa` → 读入内存索引 `accession → sequence`  
2. FASTA header 取第一个 `|` 分隔段或空格前 token 与 `proteins.accession` 匹配（大小写不敏感）  
3. 命中则写入 `base_sequence`，`sequence_source = user_fasta`

### 4.4 UniProt 获取策略（已确认：懒加载）

数据集约 **8k 唯一 accession**（蛋白组拆分后略多）。**v1 不在导入期批量拉取**；首次打开蛋白详情时按需请求：

```text
GET .../proteins/{id}
    → 读 proteins.base_sequence
    → 若 NULL 且非 decoy：
         本地 LRU 缓存（进程内，键 accession）
         → 未命中则 UniProt REST（限速 3 req/s，失败重试 2 次）
         → 成功：UPDATE proteins SET base_sequence = ...
         → 失败：extra_metadata.sequence_fetch_error = "404" | "timeout" | ...
    → 后续同蛋白打开：直接读 DB（< 50 ms）
```

| 指标 | v1 采用 |
|---|---|
| 导入期批量 UniProt | **否** |
| 首次打开某蛋白详情 | ~200–500 ms（含 UniProt 请求） |
| 二次打开 | < 50 ms（DB 缓存） |

**离线兜底**：若 UniProt 不可达，用户提供 ingest 根 FASTA（§4.3 P1）仍可启用 coverage。

### 4.5 蛋白组 accession 与序列

`Protein.Group = P62805;Q71DI3` 导入为 **2 条** `proteins`，各自独立：

- `P62805.base_sequence` ← UniProt P62805  
- `Q71DI3.base_sequence` ← UniProt Q71DI3  

同一肽段若归属蛋白组，会在两条蛋白详情页各定位一次（序列不同则区间不同）。

---

## 5. 肽段定位算法

### 5.1 术语

| 名称 | 含义 |
|---|---|
| **肽段定位** | 在 `base_sequence` 中找到 `peptides.sequence` 的区间 |
| **区间约定** | **`[start, end)`**，0-based，`end` 不包含；与 Python 切片一致 |
| **unique 肽段** | 在蛋白序列上**恰好 1 处**匹配 |
| **ambiguous 肽段** | ≥2 处匹配（重复序列蛋白常见） |

### 5.2 预处理

```python
def normalize_aa(s: str) -> str:
    return re.sub(r"[^A-Za-z]", "", s).upper()
```

- 输入肽段：优先 `peptides.sequence`（= parquet `Stripped.Sequence`）  
- **v1 不做** I/L 等价、修饰 stripped 再比对  
- 长度 `< 1` → `mapping_status = "invalid_peptide"`

### 5.3 核心算法（v1）

与 `pyteomics.parser.coverage` 相同思路：在蛋白序列上对肽段做**非 overlapping 的滑动起点扫描**（lookahead regex）。

```python
def find_peptide_occurrences(protein: str, peptide: str) -> list[tuple[int, int]]:
    protein = normalize_aa(protein)
    peptide = normalize_aa(peptide)
    if not peptide or not protein:
        return []
    pattern = re.compile("(?=" + re.escape(peptide) + ")")
    return [(m.start(), m.start() + len(peptide)) for m in pattern.finditer(protein)]
```

**复杂度**：O(n·m) per peptide，n = 蛋白长度（通常 &lt; 2k），m = 肽段数（单蛋白通常 &lt; 500）；详情页可接受 (&lt; 50 ms)。

### 5.4 匹配结果处理

| 匹配数 | `mapping_status` | 写入 `coverage_segments` | 写入 `protein_relation_mapping` |
|---|---|---|---|
| 0 | `unmapped` | 不生成 segment | `start/end` 保持 NULL |
| 1 | `unique` | 1 条 segment，`is_ambiguous=false` | v1 **不回写** `start/end` |
| ≥2 | `ambiguous` | **每条匹配 1 个 segment**，`is_ambiguous=true` | v1 **不回写** mapping 位置 |

### 5.5 去重与聚合

同一蛋白下多条 precursor 可能对应**同一肽段序列**：

- `coverage_segments` 按 **`peptide_id` 去重**（每个肽段最多一组区间列表）  
- 计算 **`coverage_percent`**：合并所有 segment 的并集后 `covered_len / len(base_sequence)`（参考 pyteomics `coverage()` 的 mask 并集）

### 5.6 与修饰肽段的关系

| 字段 | 是否参与定位 |
|---|---|
| `Stripped.Sequence` / `peptides.sequence` | ✅ |
| `Modified.Sequence` | ❌（仅 UI 展示） |
| `Protein.Sites` / PTM 位点 | ❌ v1 忽略 |

---

## 6. API 与 DB 契约

### 6.1 蛋白详情 API（BU）

```http
GET /api/v1/datasets/{slug}/proteins/{protein_id}
```

**扩展字段**（相对 Top-Down 的 cutoff 路由，BU 无 cutoff 维度）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `base_sequence` | `string \| null` | 全长序列；null 时前端降级 |
| `coverage_mode` | enum | 见 §7 |
| `coverage_percent` | `number \| null` | 0–1；无序列时为 null |
| `coverage_segments` | `array` | 高亮区间 |
| `peptides` | `array` | 下属肽段表数据源 |

**`coverage_segments[]` 元素**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `start` | int | 0-based  inclusive |
| `end` | int | 0-based exclusive |
| `peptide_id` | int | |
| `sequence` | string | 冗余，便于 tooltip |
| `is_ambiguous` | bool | 该肽段是否有多个匹配 |
| `occurrence_index` | int | 同一肽段第几个匹配（0-based） |

### 6.2 导入期 DB（与现有规划对齐）

[Bottom-Up数据导入规划.md §8.6](./Bottom-Up数据导入规划.md) 约定：

| 列 | v1 值 | v2 可选 |
|---|---|---|
| `protein_relation_mapping.start_position` | **NULL** | v2 可选回写（仅 unique） |
| `protein_relation_mapping.end_position` | **NULL** | v2 同上 |
| `protein_relation_mapping.is_unique` | **false** | v2 unique 肽段改 true |

**理由**：导入时多数蛋白尚无 `base_sequence`；定位放在详情 API 或异步 job 更稳妥。

### 6.3 前端 `SequenceCoverage.tsx`

| 条件 | UI |
|---|---|
| `coverage_mode = full` | 序列行 + 彩色 segment 高亮 + 滚动 |
| `coverage_mode = partial` | 有序列但部分肽段 `unmapped` → 高亮可用的 + 表内标记「未定位」 |
| `coverage_mode = list_only` | 仅肽段表，序列区显示说明文案 |
| `coverage_mode = decoy` | 横幅「Decoy 蛋白不提供 coverage」；**仍展示**肽段表 |

标题 **始终** 为「Sequence coverage」（见 [BU前端接入规划.md](./BU前端接入规划.md)）。

---

## 7. v1 降级策略

按 **`coverage_mode`** 四级降级（优先级从高到低判断）：

```text
is_decoy?
  yes → decoy
  no → base_sequence 为空?
          yes → list_only
          no → 至少 1 个肽段有 segment?
                  yes → 有 unmapped 肽段? → partial : full
                  no → list_only（有序列但零匹配）
```

### 7.1 各级行为

| mode | 触发条件 | 序列行 | 高亮 | 肽段表 | 用户提示 |
|---|---|---|---|---|---|
| `full` | 有序列；所有肽段 unique 或 ambiguous 均已生成 segment | ✅ | ✅ 全部 | ✅ | 可选显示 coverage % |
| `partial` | 有序列；部分肽段 `unmapped` | ✅ | ✅ 已定位部分 | ✅；未定位行 badge | 「N 条肽段未能映射到序列」 |
| `list_only` | 无序列 **或** 有序列但 0 匹配 | ❌ | ❌ | ✅ | 「蛋白序列不可用，仅展示肽段列表」 |
| `decoy` | `is_decoy=true` | ❌ | ❌ | ✅ 展示 | 「Decoy 蛋白不提供 coverage」 |

### 7.2 子场景

| 场景 | 处理 |
|---|---|
| UniProt 404 / 网络失败 | `list_only`；`extra_metadata.sequence_fetch_error` 记入日志 |
| accession 为片段 ID（如 `A0A...`） | 仍请求 UniProt；失败则降级 |
| 蛋白组中某 accession 无序列 | 仅该蛋白详情降级；不影响同组另一 accession |
| ambiguous 肽段 | **高亮所有匹配位点** + `is_ambiguous=true` |
| 肽段长度 &lt; 7 | 仍尝试定位；过短则 ambiguous 概率高，接受 |

### 7.3 与导入规划的一致性

| 导入规划 v1 | Sequence coverage v1 |
|---|---|
| `scan_number = -1` 按需解析 | `start_position = NULL` 按需定位 |
| 不在导入期扫 mzML | 不在导入期批量 UniProt（**已确认**） |
| 详情页 &lt;1s | 定位 + UniProt 单次 &lt; 500 ms（命中 DB 缓存后 &lt; 50 ms） |

---

## 8. 已确认决策

> 2026-05-21 确认：采用 §4–§7 推荐方案。

| # | 决策项 | v1 约定 |
|---|---|---|
| Q1 | **base_sequence 主来源** | UniProt 懒加载 + DB 回写 |
| Q2 | 导入期批量预拉 UniProt | **否** |
| Q3 | **ambiguous 肽段** | 高亮**所有**匹配位点 + `is_ambiguous=true` |
| Q4 | ingest 根可选 FASTA | **纳入 v1**（P1 优先级，离线兜底） |
| Q5 | unique 定位后回写 `protein_relation_mapping` | v1 **不回写**（仅 API 返回 segments） |
| Q6 | Decoy 蛋白肽段表 | **展示**肽段表，不显示 coverage 序列行 |
| Q7 | I/L 等价、M 氧化等模糊匹配 | v1 **不做** |
| Q8 | 网络环境 | 默认部署可访问 UniProt；不可达时用 FASTA 兜底 |

---

## 9. 实施分期与验收

### 9.1 模块（`E:\viewer\back\app\bu\`）

```text
back/app/
├── api/v1/bu/
│   └── proteins.py                    # GET .../proteins/{protein_id}（薄 handler）
└── bu/services/
    ├── protein_sequence_resolver.py   # §4：UniProt / FASTA / description.tsv
    └── peptide_mapper.py              # §5：find_peptide_occurrences + coverage_percent
```

### 9.2 分期

| 阶段 | 内容 | 依赖 |
|---|---|---|
| **M7a** | `peptide_mapper` + API 返回 `coverage_segments`（假定 base_sequence 已在 DB） | 手动 seed 一条序列测通 |
| **M7b** | `protein_sequence_resolver` UniProt 懒加载 + FASTA | §8 已确认 |
| **M7c** | 前端 `SequenceCoverage.tsx` 四级降级 UI | [BU前端接入规划.md](./BU前端接入规划.md) P6 |

### 9.3 验收清单

| # | 检查 | 期望 |
|---|---|---|
| 1 | 打开 `P62805` 蛋白详情 | 有 `base_sequence`；≥1 条 segment |
| 2 | 已知肽段 `LLLPGELAK`（H2B） | segment 与 UniProt 序列手动核对一致 |
| 3 | 断网 + 无缓存 | `coverage_mode = list_only`，页面不报错 |
| 4 | Decoy 蛋白 | `coverage_mode = decoy` |
| 5 | 重复序列肽段（若存在） | 高亮所有匹配位点 |
| 6 | 蛋白详情 | **无** MS2 / XIC 请求 |

---

## 附录 A：示例（P62805 · Histone H4）

假设 UniProt 返回序列（节选）：

```text
MARTKQTARKSTGGKAPRKQLATKAARKSAPATGGVKKPHRYRPGTVALRE...
```

肽段 `STGGKAPRKQL` 若 unique 匹配：

```json
{ "start": 12, "end": 23, "sequence": "STGGKAPRKQL", "is_ambiguous": false, "occurrence_index": 0 }
```

前端渲染（概念）：

```text
MARTKQTARKSTGGKAPRKQLATKAARKSAPATGGVKKPHRYRPGTVALRE...
           ███████████
```

---

## 附录 B：与 Top-Down Sequence coverage 对比

| 项 | Top-Down（PrSM 详情） | Bottom-Up（蛋白详情） |
|---|---|---|
| 序列来源 | PrSM / proteoform JSON | UniProt / FASTA → `proteins.base_sequence` |
| 定位依据 | 搜索引擎已给位点 | 运行时字符串匹配 |
| 组件 | `SequenceView` | `SequenceCoverage`（新） |
| 无序列时 | 不展示卡片 | `list_only` 降级 |

---

*文档 v1.0 · Sequence Coverage 专项规划 · 已确认，可进入 M7 实施。*
