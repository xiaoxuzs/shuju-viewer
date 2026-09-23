# BU 列表与数据集 API 规范

> **文档版本**：v1.2  
> **日期**：2026-05-21  
> **适用范围**：`analysis_mode = BOTTOM_UP` 的 Viewer 数据集（DIA-NN 2.0 + universal schema）  
> **Viewer 项目**：`E:\viewer\`  
> **状态**：规划稿（实现前契约）  
> **关联文档**：[P0-Viewer代码改造规划.md](./P0-Viewer代码改造规划.md)（C1–C7 / C22）、[Viewer接入规划-完整版.md](./Viewer接入规划-完整版.md)、[Bottom-Up数据导入规划.md](./Bottom-Up数据导入规划.md)、[谱图查看说明.md](./谱图查看说明.md)

---

## 目录

1. [文档目的](#1-文档目的)
2. [与 Top-Down API 的差异](#2-与-top-down-api-的差异)
3. [通用约定](#3-通用约定)
4. [端点总览](#4-端点总览)
5. [`GET /datasets/{slug}/overview`](#5-get-datasetsslugoverview)
6. [`GET /datasets/{slug}/overview/rt-mz`](#6-get-datasetsslugoverviewrt-mz)
7. [`GET /datasets/{slug}/proteins`](#7-get-datasetsslugproteins)
8. [`GET /datasets/{slug}/proteins/{protein_id}`](#8-get-datasetsslugproteinsprotein_id)
9. [`GET /datasets/{slug}/peptides`](#9-get-datasetsslugpeptides)
10. [`GET /datasets/{slug}/peptides/{peptide_id}`](#10-get-datasetsslugpeptidespeptide_id)
11. [`GET /datasets/{slug}/matches`](#11-get-datasetsslugmatches)
12. [`GET /datasets/{slug}/matches/{match_id}`](#12-get-datasetsslugmatchesmatch_id)
13. [错误码与校验](#13-错误码与校验)
14. [Pydantic 模型命名建议](#14-pydantic-模型命名建议)
15. [修订记录](#15-修订记录)

---

## 1. 文档目的

本文定义 Bottom-Up 数据集在 Viewer 中的**列表与概览 REST API** 的完整 JSON Schema，覆盖：

| 资源 | 用途 |
|---|---|
| `overview` | 整体页 QC 卡片、规模统计、run 列表 |
| `proteins` | 蛋白列表 / 蛋白详情（含 Sequence coverage） |
| `peptides` | 肽段列表 / 肽段详情 |
| `matches` | 鉴定（precursor）列表 / 鉴定摘要（无大谱图数组） |

**不在本文展开**（见 [谱图查看说明.md](./谱图查看说明.md)）：`chromatogram`、`xic`、`spectrum/ms1|ms2`、`mobility-slice`、`dia-windows`。

**数据真值**：`E:\viewer\docs\universal_schema.sql`；字段入库映射见 [Bottom-Up数据导入规划.md §8](./Bottom-Up数据导入规划.md#8-parquet--universal-schema-字段映射)。

---

## 2. 与 Top-Down API 的差异

| 维度 | Top-Down（已实现） | Bottom-Up（本文） |
|---|---|---|
| URL 前缀 | `/api/v1` | 相同 |
| Cutoff 路径段 | **必须** `/datasets/{slug}/cutoffs/{cutoff}/...` | **无** cutoff；直接 `/datasets/{slug}/proteins` 等 |
| 鉴定实体 | `prsms`（`entity_type=PROTEOFORM`） | `matches`（`entity_type=PEPTIDE`） |
| 列表主键 | PrSM 业务 id `source_prsm_id` | DB 主键 `identification_matches.match_id` |
| `DatasetOut.cutoffs` | 合成 `prsm` / `proteoform` 统计 | **空数组 `[]`**；规模见 `overview.counts` |
| 蛋白列表字段 | `sequence_id`, `prsm_number`… | `accession`, `peptide_count`, `protein_group`… |

前端根据 `GET /datasets/{slug}` 响应中的 `analysis_mode`（见 §3.2 扩展）分支路由，**禁止**对 BU 数据集请求 `/cutoffs/...`。

**URL 与 API 路径对照**（无 `/bu/` 前缀）：

| 场景 | 浏览器 URL | REST API |
|---|---|---|
| Top-Down 列表/详情 | `/datasets/:slug/:cutoff/prsms/...` | `/api/v1/datasets/:slug/cutoffs/:cutoff/...` |
| Bottom-Up 列表/详情 | `/datasets/:slug/proteins` 等（**无** `cutoffs` 段） | `/api/v1/datasets/:slug/proteins` 等 |

---

## 3. 通用约定

### 3.1 请求

- **Base URL**：`/api/v1`
- **Content-Type**：`application/json; charset=utf-8`
- **鉴权**：v1 与现有 Viewer 一致（内网部署，无额外 token）

### 3.2 数据集门禁

所有本文端点（§4.1 数据集内）在执行 SQL 前必须：

1. `require_dataset(slug)` → 得到 `dataset_id`
2. 校验 `datasets.analysis_mode = 'BOTTOM_UP'`，否则 **404** + `detail: "not_bottom_up"`（D16 附记：全项目统一 404，不用 409）

#### 3.2.1 列表端点 `GET /datasets`（共用，M4）

与 Top-Down **共用**现有列表端点（完整 JSON 见 [§4.0](#40-get-datasets数据集列表共用)）。**每项必填** `analysis_mode`：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `analysis_mode` | `"BOTTOM_UP" \| "TOP_DOWN"` | ✅ | 来自 `datasets.analysis_mode`；供 DatasetsPage badge 与路由预判 |

| 数据集类型 | `cutoffs` | 前端行为 |
|---|---|---|
| Top-Down | 非空（prsm / proteoform 统计） | 卡片可显示 cutoff 入口 |
| Bottom-Up | **`[]` 空数组**（D12） | **不**渲染 cutoff；点进后走 BU 路由树 |

列表 API **不**因 BU 新增独立路径；扩展字段向后兼容，TD 旧客户端可忽略 `analysis_mode`（但 v1 前端必须读）。

#### 3.2.2 单数据集 `GET /datasets/{slug}`（扩展）

`GET /datasets/{slug}`（已有端点）对 BU 数据集**扩展**以下字段（向后兼容，TD 数据集为 `null` / 省略）：

```json
{
  "id": 12,
  "slug": "hela_dia_20200110",
  "name": "HeLa DIA 500ng R1",
  "analysis_mode": "BOTTOM_UP",
  "source_software": "DIA-NN_2.0",
  "capabilities": {
    "spectra_source": "mzml_memory",
    "list_routes": ["proteins", "peptides", "matches"]
  },
  "cutoffs": [],
  "status": "READY",
  "extra_metadata": {
    "q_value_cutoff": 0.01,
    "import_stats": { "matches_imported": 110026 }
  },
  "bu_runs": [
    {
      "run_id": 41,
      "file_name": "20200110_Hela_500ng_DIA_25cm_120min_R1.mzML",
      "raw_format": "mzml",
      "diann_run_name": "20200110_Hela_500ng_DIA_25cm_120min_R1"
    }
  ]
}
```

| 扩展字段 | 类型 | 说明 |
|---|---|---|
| `analysis_mode` | `"BOTTOM_UP" \| "TOP_DOWN"` | 来自 `datasets.analysis_mode` |
| `source_software` | `string` | 如 `DIA-NN_2.0`；TD 为 TopPIC 等 |
| `status` | `"IMPORTED" \| "PARSING" \| "READY" \| "ERROR"` | 来自 `datasets.status`（与 `universal_schema.sql` 一致） |
| `capabilities` | `object` | 导入时写入；BU 含 `spectra_source`、`list_routes` 等（见 [导入规划 §14](./Bottom-Up数据导入规划.md#14-capabilities-与-extra_metadata-约定)） |
| `extra_metadata` | `object` | JSONB 透传；**至少**含 `q_value_cutoff`（导入阈值，默认 0.01） |
| `bu_runs` | `BuRunSummary[]` | 嵌套 run 摘要；整体页 run 切换器数据源；TD 为 `null` / 省略 |

**`q_value_cutoff` 真值源**：以本端点 `extra_metadata.q_value_cutoff` 为准；`GET .../overview` 的 `q_value_cutoff` 与之相同，仅作前端 **fallback**（slug 响应缺字段时）。

### 3.3 分页包装 `Page<T>`

与现有 Top-Down 列表一致：

```json
{
  "items": [],
  "total": 110026,
  "page": 1,
  "page_size": 50
}
```

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `items` | `T[]` | 必填 | 当前页行 |
| `total` | `integer` | `≥ 0` | **过滤后**总行数（非仅本页） |
| `page` | `integer` | `≥ 1`，默认 `1` | |
| `page_size` | `integer` | `1…500`，默认 `50` | |

### 3.4 公共查询参数（列表端点）

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `page` | `integer` | `1` | |
| `page_size` | `integer` | `50` | 最大 500 |
| `sort` | `string` | 各端点不同 | 白名单列名，非法值回退默认 |
| `order` | `"asc" \| "desc"` | 各端点不同 | |
| `search` | `string` | — | 大小写不敏感子串（`ILIKE`） |

### 3.5 时间与单位

| 量 | 单位 | 说明 |
|---|---|---|
| `retention_time` / `rt_*` | **分钟** | 与 DIA-NN parquet、`demo_04/05` 一致 |
| `precursor_mz` | Th | |
| `q_value` | 无量纲 | 0–1 |
| `intensity` | 仪器原始单位 | DIA-NN `Precursor.Quantity` 或 `Ms2.Area` |

---

## 4. 端点总览

### 4.0 `GET /datasets`（数据集列表，共用）

与 Top-Down **共用**现有列表端点，响应形状与现网 Viewer **一致**：**`DatasetOut[]` 数组**（非 `Page<T>`；`list_datasets` → `list[DatasetOut]`，`fetchDatasets(): Promise<DatasetOut[]>`）。v1 **不**改造为分页包装。

每项在现有 TD 字段基础上 **扩展**（向后兼容）：

```json
[
  {
    "id": 12,
    "slug": "hela_dia_20200110",
    "name": "HeLa DIA 500ng R1",
    "description": null,
    "source_path": "d:\\dia-shuju",
    "capabilities": {},
    "created_at": "2026-05-20T10:00:00Z",
    "updated_at": null,
    "cutoffs": [],
    "analysis_mode": "BOTTOM_UP",
    "source_software": "DIA-NN_2.0",
    "status": "READY"
  }
]
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| （现有）`id`, `slug`, `name`, `description`, `source_path`, `capabilities`, `created_at`, `cutoffs` | — | ✅ | 与现网 `DatasetOut` 一致 |
| `updated_at` | `datetime \| null` | 🟡 | `datasets` 表**无** `updated_at` 列；API 恒为 `null`；前端展示相对时间时 **fallback `created_at`** |
| `analysis_mode` | `"BOTTOM_UP" \| "TOP_DOWN"` | ✅ | 来自 `datasets.analysis_mode` |
| `source_software` | `string \| null` | ✅ | 如 `DIA-NN_2.0`；卡片小字 |
| `status` | `"IMPORTED" \| "PARSING" \| "READY" \| "ERROR"` | ✅ | 来自 `datasets.status`；前端 pill 文案映射，**禁止**自造 `IMPORTING` / `FAILED` |

### 4.1 数据集内端点

| 方法 | 路径 | 响应模型 | 页面 |
|---|---|---|---|
| `GET` | `/datasets/{slug}/overview` | `BuOverviewOut` | 整体页 |
| `GET` | `/datasets/{slug}/overview/rt-mz` | `BuRtMzHeatmapOut` | 整体页（可选） |
| `GET` | `/datasets/{slug}/proteins` | `Page<BuProteinListItemOut>` | 蛋白列表 |
| `GET` | `/datasets/{slug}/proteins/{protein_id}` | `BuProteinDetailOut` | 蛋白详情 |
| `GET` | `/datasets/{slug}/peptides` | `Page<BuPeptideListItemOut>` | 肽段列表 |
| `GET` | `/datasets/{slug}/peptides/{peptide_id}` | `BuPeptideDetailOut` | 肽段详情 |
| `GET` | `/datasets/{slug}/matches` | `Page<BuMatchListItemOut>` | 鉴定列表 |
| `GET` | `/datasets/{slug}/matches/{match_id}` | `BuMatchDetailOut` | 鉴定详情（摘要） |

---

## 5. `GET /datasets/{slug}/overview`

**用途**：整体页顶部 QC 卡片、数据集规模、run 切换器元数据。  
**禁止**：返回谱图数组（TIC/XIC/峰列表）。

### 5.1 请求

无 query 参数。

### 5.2 响应：`BuOverviewOut`

```json
{
  "dataset_id": 12,
  "slug": "hela_dia_20200110",
  "name": "HeLa DIA 500ng R1",
  "analysis_mode": "BOTTOM_UP",
  "source_software": "DIA-NN_2.0",
  "status": "READY",
  "source_root": "d:\\dia-shuju",
  "q_value_cutoff": 0.01,
  "counts": {
    "matches": 110026,
    "peptides": 92704,
    "proteins": 8247,
    "protein_groups": 8063,
    "runs": 2,
    "decoy_matches": 0
  },
  "qc": {
    "by_run": [
      {
        "run_id": 41,
        "file_name": "20200110_Hela_500ng_DIA_25cm_120min_R1.mzML",
        "diann_run_name": "20200110_Hela_500ng_DIA_25cm_120min_R1",
        "precursors_identified": 110026,
        "proteins_identified": 7191,
        "total_quantity": 5.07853e11,
        "ms1_signal": 1.0292914175731e13,
        "ms2_signal": 2.919961093101e12,
        "fwhm_scans": 3.39,
        "fwhm_rt": 0.262,
        "median_mass_acc_ms1": 0.96528,
        "median_mass_acc_ms1_corrected": 0.433707,
        "median_mass_acc_ms2": 1.37538,
        "median_mass_acc_ms2_corrected": 1.20139,
        "normalisation_instability": 0.0,
        "median_rt_prediction_acc": 1.31329,
        "average_peptide_length": 13.021,
        "average_peptide_charge": 2.263,
        "average_missed_tryptic_cleavages": 0.103
      }
    ],
    "aggregated": {
      "precursors_identified": 110026,
      "proteins_identified": 7191,
      "median_mass_acc_ms1": 0.96528,
      "median_mass_acc_ms2": 1.37538,
      "fwhm_rt": 0.262
    }
  },
  "runs": [
    {
      "run_id": 41,
      "file_name": "20200110_Hela_500ng_DIA_25cm_120min_R1.mzML",
      "raw_format": "mzml",
      "diann_run_name": "20200110_Hela_500ng_DIA_25cm_120min_R1",
      "match_count": 110026,
      "has_im": false
    },
    {
      "run_id": 42,
      "file_name": "DC2817_ELB00124_DIA_H00BP43_P05_A12_13560.d",
      "raw_format": "bruker_d",
      "diann_run_name": "DC2817_ELB00124_DIA_H00BP43_P05_A12_13560",
      "match_count": 0,
      "has_im": true
    }
  ],
  "capabilities": {
    "spectra_source": "mixed",
    "has_ms1": true,
    "has_ms2": true,
    "has_im": true,
    "has_dia_windows": true,
    "analysis_shape": "bottom_up_dia",
    "import_mode": "diann_parquet",
    "entity_types": ["PEPTIDE"],
    "list_routes": ["proteins", "peptides", "matches"]
  },
  "import_stats": {
    "parquet_total_rows": 323232,
    "imported_matches": 110026,
    "unique_peptides": 92704,
    "unique_protein_groups": 8063,
    "parquet_path": "DIANN_2.0/DIANN_2.0/all_report.parquet"
  },
  "created_at": "2026-05-21T08:00:00+08:00"
}
```

### 5.3 字段说明

#### 根对象

| 字段 | 类型 | 必填 | 来源 |
|---|---|---|---|
| `dataset_id` | `integer` | ✅ | `datasets.dataset_id` |
| `slug` | `string` | ✅ | `datasets.slug` |
| `name` | `string` | ✅ | `datasets.dataset_name` |
| `analysis_mode` | `"BOTTOM_UP"` | ✅ | |
| `source_software` | `string` | ✅ | `datasets.source_software` |
| `status` | `string` | ✅ | `IMPORTED\|PARSING\|READY\|ERROR` |
| `source_root` | `string` | ✅ | `datasets.source_root` |
| `q_value_cutoff` | `number` | ✅ | `extra_metadata.q_value_cutoff` |
| `counts` | `BuOverviewCounts` | ✅ | DB 聚合，见下表 |
| `qc` | `BuQcBlock` | ✅ | `extra_metadata.stats` + 按 run 对齐 |
| `runs` | `BuRunSummary[]` | ✅ | `runs` 表 + `COUNT(matches)` |
| `capabilities` | `object` | ✅ | `datasets.capabilities` |
| `import_stats` | `object` | 🟡 | `extra_metadata.import_stats` |
| `created_at` | `string` (ISO8601) | ✅ | `datasets.created_at` |

#### `BuOverviewCounts`

| 字段 | 类型 | SQL 含义 |
|---|---|---|
| `matches` | `integer` | `COUNT(*)` FROM `identification_matches` WHERE `entity_type='PEPTIDE'` |
| `peptides` | `integer` | `COUNT(DISTINCT entity_id)` 同上 |
| `proteins` | `integer` | `COUNT(*)` FROM `proteins` WHERE `is_decoy=false` |
| `protein_groups` | `integer` | `COUNT(DISTINCT extra_metadata->>'protein_group')` 或 import_stats |
| `runs` | `integer` | `COUNT(*)` FROM `runs` |
| `decoy_matches` | `integer` | `is_decoy_match=true` 行数（导入方案 B 通常为 0） |

#### `BuQcRow`（`qc.by_run[]` 元素）

导入时由 `all_report.stats.tsv` 写入；列名映射（TSV → JSON snake_case）：

| JSON 字段 | stats.tsv 列 |
|---|---|
| `precursors_identified` | `Precursors.Identified` |
| `proteins_identified` | `Proteins.Identified` |
| `total_quantity` | `Total.Quantity` |
| `ms1_signal` | `MS1.Signal` |
| `ms2_signal` | `MS2.Signal` |
| `fwhm_scans` | `FWHM.Scans` |
| `fwhm_rt` | `FWHM.RT` |
| `median_mass_acc_ms1` | `Median.Mass.Acc.MS1` |
| `median_mass_acc_ms1_corrected` | `Median.Mass.Acc.MS1.Corrected` |
| `median_mass_acc_ms2` | `Median.Mass.Acc.MS2` |
| `median_mass_acc_ms2_corrected` | `Median.Mass.Acc.MS2.Corrected` |
| `normalisation_instability` | `Normalisation.Instability` |
| `median_rt_prediction_acc` | `Median.RT.Prediction.Acc` |
| `average_peptide_length` | `Average.Peptide.Length` |
| `average_peptide_charge` | `Average.Peptide.Charge` |
| `average_missed_tryptic_cleavages` | `Average.Missed.Tryptic.Cleavages` |

`qc.aggregated`：单 run 时等于该 run；多 run 时 v1 可取**主 run**（match_count 最大）或简单 sum/max——实现须在 OpenAPI `description` 中写死一种。

#### `BuRunSummary`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `run_id` | `integer` | ✅ | `runs.run_id` |
| `file_name` | `string` | ✅ | `runs.file_name` |
| `raw_format` | `"mzml" \| "bruker_d"` | ✅ | `run_metadata.raw_format` |
| `diann_run_name` | `string` | ✅ | `run_metadata.diann_run_name` |
| `match_count` | `integer` | ✅ | 该 run 下鉴定数 |
| `has_im` | `boolean` | ✅ | `raw_format=bruker_d` → true |

---

## 6. `GET /datasets/{slug}/overview/rt-mz`

**用途**：整体页 RT–m/z 简化热图（**仅读 DB**，不读 mzML）。  
**v1**：可选实现；未实现时 **501** 或省略前端请求。

### 6.1 查询参数

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `run_id` | `integer` | 全部 run | 限定单个 run |
| `q_max` | `number` | `q_value_cutoff` | 与列表默认一致 |
| `bins_rt` | `integer` | `80` | RT 分箱数，`10…200` |
| `bins_mz` | `integer` | `80` | m/z 分箱数 |
| `decoy` | `boolean` | `false` | **`false`** = 排除 decoy（`WHERE is_decoy_match = false`）；**`true`** = 含 decoy（不加 `is_decoy_match` 过滤） |

### 6.2 响应：`BuRtMzHeatmapOut`

```json
{
  "unit_rt": "min",
  "unit_mz": "Th",
  "rt_edges": [0.0, 1.5, 3.0],
  "mz_edges": [400.0, 410.0, 420.0],
  "counts": [
    [0, 12, 5],
    [3, 0, 8]
  ],
  "max_count": 12,
  "total_points": 110026,
  "run_id": 41
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `rt_edges` | `number[]` | 长度 `bins_rt + 1`，单调递增 |
| `mz_edges` | `number[]` | 长度 `bins_mz + 1` |
| `counts` | `integer[][]` | 形状 `[bins_rt][bins_mz]`，`counts[i][j]` = RT 第 i 箱、m/z 第 j 箱 |
| `max_count` | `integer` | 热力图 color scale 上限 |
| `total_points` | `integer` | 参与分箱的鉴定行数 |
| `run_id` | `integer \| null` | 请求过滤时回显 |

**产生**：对 `identification_matches` 的 `retention_time`、`precursor_mz` 做等宽分箱 `COUNT(*)`。

---

## 7. `GET /datasets/{slug}/proteins`

### 7.1 查询参数

| 参数 | 默认 | `sort` 白名单 |
|---|---|---|
| 公共分页 | 见 §3.4 | `accession`, `gene_name`, `peptide_count`, `match_count`, `best_q_value`, `pg_max_lfq` |
| `search` | — | 匹配 `accession`, `gene_name`, `description`, `extra_metadata.protein_group` |
| `decoy` | `false` | **`false`** = 仅非 decoy 蛋白（`WHERE proteins.is_decoy = false`）；**`true`** = 含 decoy（不加 `is_decoy` 过滤） |
| `protein_group` | — | 精确过滤 `extra_metadata.protein_group` |

> v1 **不提供** `pg_q_max` 查询参数；蛋白组 Q 筛选由前端在已加载页内二次过滤，或二期再加 API 参数。

### 7.2 列表项：`BuProteinListItemOut`

```json
{
  "id": 1001,
  "accession": "P62805",
  "gene_name": "H4C1",
  "description": "Histone H4",
  "is_decoy": false,
  "protein_group": "P62805;Q71DI3",
  "peptide_count": 42,
  "match_count": 87,
  "best_q_value": 0.00012,
  "pg_max_lfq": 1.25e8,
  "pg_q_value": 0.001,
  "pg_quantity": 3.4e7
}
```

| 字段 | 类型 | 必填 | DB / 计算 |
|---|---|---|---|
| `id` | `integer` | ✅ | `proteins.protein_id` |
| `accession` | `string` | ✅ | `proteins.accession` |
| `gene_name` | `string \| null` | ✅ | `proteins.gene_name` |
| `description` | `string \| null` | ✅ | `proteins.description` |
| `is_decoy` | `boolean` | ✅ | `proteins.is_decoy` |
| `protein_group` | `string \| null` | ✅ | `extra_metadata.protein_group`（原始 `Protein.Group`） |
| `peptide_count` | `integer` | ✅ | 经 `protein_relation_mapping`  DISTINCT `entity_id`（PEPTIDE） |
| `match_count` | `integer` | ✅ | 关联 `identification_matches` 行数 |
| `best_q_value` | `number \| null` | ✅ | `MIN(q_value)` |
| `pg_max_lfq` | `number \| null` | 🟡 | `extra_metadata.pg_max_lfq` |
| `pg_q_value` | `number \| null` | 🟡 | `extra_metadata.pg_q_value` |
| `pg_quantity` | `number \| null` | 🟡 | `extra_metadata.pg_quantity` |

**蛋白组拆分**：`Protein.Group = "A;B"` 入库为 2 条 protein，共享同一 `protein_group` 字符串；列表按 accession 展示。

### 7.3 响应示例

```json
{
  "items": [ { "id": 1001, "accession": "P62805", "gene_name": "H4C1", "description": "Histone H4", "is_decoy": false, "protein_group": "P62805;Q71DI3", "peptide_count": 42, "match_count": 87, "best_q_value": 0.00012, "pg_max_lfq": 125000000.0, "pg_q_value": 0.001, "pg_quantity": 34000000.0 } ],
  "total": 8247,
  "page": 1,
  "page_size": 50
}
```

---

## 8. `GET /datasets/{slug}/proteins/{protein_id}`

### 8.1 路径参数

| 参数 | 说明 |
|---|---|
| `protein_id` | `proteins.protein_id`（库表主键，非 UniProt 字符串） |

### 8.2 响应：`BuProteinDetailOut`

继承 `BuProteinListItemOut`，并增加：

```json
{
  "id": 1001,
  "accession": "P62805",
  "gene_name": "H4C1",
  "description": "Histone H4",
  "is_decoy": false,
  "protein_group": "P62805;Q71DI3",
  "peptide_count": 42,
  "match_count": 87,
  "best_q_value": 0.00012,
  "pg_max_lfq": 125000000.0,
  "pg_q_value": 0.001,
  "pg_quantity": 34000000.0,
  "base_sequence": "MARTKQTARKSTGGKAPRKQLATKAARKSAPATGGVKKPHRYRPGTVALREIRRYQKSTELLIRKLPFQRLVREIAQDFKTDLRFQSSAVMALQEACEAYLVGLFEDTNLCAIHAKRVTIMPKDIQLARRIRGERA",
  "coverage_segments": [
    {
      "peptide_id": 501,
      "sequence": "KSTGGKAPR",
      "start": 10,
      "end": 19,
      "match_count": 3,
      "best_q_value": 0.0003
    }
  ],
  "peptides": [
    {
      "peptide_id": 501,
      "sequence": "KSTGGKAPR",
      "modified_sequence": "K(UniMod:1)STGGKAPR",
      "match_count": 3,
      "best_q_value": 0.0003,
      "best_match_id": 88001
    }
  ],
  "extra_metadata": {
    "protein_names": "Histone H4",
    "protein_ids": "sp|P62805|H4_HUMAN",
    "original_protein_group": "P62805;Q71DI3"
  }
}
```

#### `BuCoverageSegment`

| 字段 | 类型 | 说明 |
|---|---|---|
| `peptide_id` | `integer` | |
| `sequence` | `string` | `peptides.sequence` |
| `start` | `integer \| null` | v1 无位置时为 `null`，前端仅列表不高亮 |
| `end` | `integer \| null` | 半开区间 `[start, end)` |
| `match_count` | `integer` | |
| `best_q_value` | `number \| null` | |

#### `BuProteinPeptideRef`

| 字段 | 类型 | 说明 |
|---|---|---|
| `peptide_id` | `integer` | |
| `sequence` | `string` | |
| `modified_sequence` | `string \| null` | 该蛋白下该肽最佳 match 的 `modified_sequence` |
| `match_count` | `integer` | 此蛋白–肽段组合 |
| `best_q_value` | `number \| null` | |
| `best_match_id` | `integer \| null` | 链到 `/matches/{id}` |

**禁止**：本端点返回 `mz`/`intensity` 数组或请求谱图子资源。

---

## 9. `GET /datasets/{slug}/peptides`

### 9.1 查询参数

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| 公共分页 | | | `page`, `page_size`, `sort`, `order`, `search` |
| `sort` | `string` | `best_q_value` | 白名单：`sequence`, `length`, `match_count`, `protein_count`, `best_q_value`, `best_precursor_mz` |
| `search` | `string` | — | `peptides.sequence` ILIKE |
| `protein_id` | `integer` | — | 仅返回与该蛋白有 mapping 的肽段 |
| `min_length` / `max_length` | `integer` | — | 肽段长度过滤 |
| `q_max` | `number` | `q_value_cutoff` | 仅保留 `best_q_value ≤ q_max` 的肽段（与 matches 列表默认阈值一致） |

### 9.2 列表项：`BuPeptideListItemOut`

```json
{
  "id": 501,
  "sequence": "KSTGGKAPR",
  "length": 9,
  "theoretical_mass": 978.52,
  "missed_cleavages": null,
  "match_count": 5,
  "protein_count": 2,
  "best_q_value": 0.0003,
  "best_precursor_mz": 490.265,
  "best_charge": 2,
  "best_match_id": 88001,
  "protein_groups": "P62805;Q71DI3",
  "genes": "H4C1",
  "example_modified": "K(UniMod:1)STGGKAPR"
}
```

| 字段 | 类型 | DB |
|---|---|---|
| `id` | `integer` | `peptides.peptide_id` |
| `sequence` | `string` | `peptides.sequence` |
| `length` | `integer \| null` | `peptides.length` |
| `theoretical_mass` | `number \| null` | `peptides.theoretical_mass` |
| `missed_cleavages` | `integer \| null` | `peptides.missed_cleavages` |
| `match_count` | `integer` | 聚合 |
| `protein_count` | `integer` | mapping DISTINCT protein |
| `best_q_value` | `number \| null` | MIN(q_value) |
| `best_precursor_mz` | `number \| null` | 对应 best match |
| `best_charge` | `integer \| null` | |
| `best_match_id` | `integer \| null` | `match_id` at min q |
| `protein_groups` | `string \| null` | 关联 match 的 `DISTINCT extra_metadata.protein_group`，`;` 拼接（展示用） |
| `genes` | `string \| null` | 关联 match / protein 的 `genes` 去重拼接 |
| `example_modified` | `string \| null` | 任一条关联 match 的 `modified_sequence`（通常取 best match） |

---

## 10. `GET /datasets/{slug}/peptides/{peptide_id}`

### 10.1 响应：`BuPeptideDetailOut`

```json
{
  "id": 501,
  "sequence": "KSTGGKAPR",
  "length": 9,
  "theoretical_mass": 978.52,
  "missed_cleavages": null,
  "match_count": 5,
  "protein_count": 2,
  "best_q_value": 0.0003,
  "best_precursor_mz": 490.265,
  "best_charge": 2,
  "best_match_id": 88001,
  "proteins": [
    {
      "protein_id": 1001,
      "accession": "P62805",
      "gene_name": "H4C1",
      "protein_group": "P62805;Q71DI3",
      "is_unique": false
    }
  ],
  "matches_summary": {
    "total": 5,
    "items": [
      {
        "id": 88001,
        "run_id": 41,
        "run_name": "20200110_Hela_500ng_DIA_25cm_120min_R1.mzML",
        "precursor_mz": 490.265,
        "precursor_charge": 2,
        "retention_time": 92.46,
        "q_value": 0.0003,
        "intensity": 1250000.0
      }
    ]
  },
  "extra_metadata": {
    "modified_sequence_template": "K(UniMod:1)STGGKAPR"
  }
}
```

| 字段 | 说明 |
|---|---|
| `proteins` | 经 `protein_relation_mapping` |
| `matches_summary` | 详情页侧边预览；完整列表仍用 `GET /matches?peptide_id=` |
| `matches_summary.items` | v1 默认最多 **20** 条，按 `q_value ASC` |

---

## 11. `GET /datasets/{slug}/matches`

**核心列表**：一行 = 一条 precursor 鉴定（`identification_matches`）。

### 11.1 查询参数

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| 公共分页 | | | |
| `sort` | `string` | `q_value` | 白名单见下 |
| `run_id` | `integer` | — | |
| `peptide_id` | `integer` | — | |
| `protein_id` | `integer` | — | EXISTS mapping |
| `q_max` | `number` | `q_value_cutoff` | |
| `decoy` | `boolean` | `false` | **`false`** = 排除 decoy 鉴定（`WHERE identification_matches.is_decoy_match = false`）；**`true`** = 含 decoy（不加过滤） |
| `charge` | `integer` | — | 精确电荷 |
| `rt_min` / `rt_max` | `number` | — | 分钟 |
| `mz_min` / `mz_max` | `number` | — | precursor m/z |
| `search` | `string` | — | `sequence`, `modified_sequence`, `protein_group`, `genes` |

**`sort` 白名单**：`q_value`, `score`, `retention_time`, `precursor_mz`, `precursor_charge`, `intensity`, `match_id`。

### 11.2 列表项：`BuMatchListItemOut`

```json
{
  "id": 88001,
  "run_id": 41,
  "run_name": "20200110_Hela_500ng_DIA_25cm_120min_R1.mzML",
  "peptide_id": 501,
  "sequence": "KSTGGKAPR",
  "modified_sequence": "K(UniMod:1)STGGKAPR",
  "precursor_mz": 490.265,
  "precursor_charge": 2,
  "retention_time": 92.46,
  "experimental_mass": 978.52,
  "q_value": 0.0003,
  "score": 0.0003,
  "intensity": 1250000.0,
  "is_decoy_match": false,
  "scan_number": -1,
  "protein_group": "P62805;Q71DI3",
  "protein_accessions": ["P62805", "Q71DI3"],
  "genes": "H4C1",
  "search_engine": "DIA-NN"
}
```

| 字段 | 类型 | 必填 | DB 列 / 说明 |
|---|---|---|---|
| `id` | `integer` | ✅ | `match_id` |
| `run_id` | `integer` | ✅ | `run_id` |
| `run_name` | `string` | ✅ | `runs.file_name` |
| `peptide_id` | `integer` | ✅ | `entity_id`（`entity_type=PEPTIDE`） |
| `sequence` | `string` | ✅ | JOIN `peptides.sequence` |
| `modified_sequence` | `string \| null` | ✅ | `modified_sequence` |
| `precursor_mz` | `number` | ✅ | `precursor_mz` |
| `precursor_charge` | `integer` | ✅ | `precursor_charge` |
| `retention_time` | `number` | ✅ | `retention_time`（分钟） |
| `experimental_mass` | `number \| null` | ✅ | `experimental_mass` |
| `q_value` | `number` | ✅ | `q_value` |
| `score` | `number \| null` | ✅ | `score`（Global.Q.Value 或 Q.Value） |
| `intensity` | `number \| null` | ✅ | `intensity` |
| `is_decoy_match` | `boolean` | ✅ | `is_decoy_match` |
| `scan_number` | `integer` | ✅ | v1 常为 **-1** |
| `protein_group` | `string \| null` | ✅ | `extra_metadata.protein_group` |
| `protein_accessions` | `string[]` | ✅ | 由 `protein_group` 拆分 `;` |
| `genes` | `string \| null` | ✅ | `extra_metadata.genes` 或 parquet `Genes` |
| `search_engine` | `string` | ✅ | `search_engine` |

### 11.3 响应示例

```json
{
  "items": [ { "id": 88001, "run_id": 41, "run_name": "20200110_Hela_500ng_DIA_25cm_120min_R1.mzML", "peptide_id": 501, "sequence": "KSTGGKAPR", "modified_sequence": "K(UniMod:1)STGGKAPR", "precursor_mz": 490.265, "precursor_charge": 2, "retention_time": 92.46, "experimental_mass": 978.52, "q_value": 0.0003, "score": 0.0003, "intensity": 1250000.0, "is_decoy_match": false, "scan_number": -1, "protein_group": "P62805;Q71DI3", "protein_accessions": ["P62805", "Q71DI3"], "genes": "H4C1", "search_engine": "DIA-NN" } ],
  "total": 110026,
  "page": 1,
  "page_size": 50
}
```

---

## 12. `GET /datasets/{slug}/matches/{match_id}`

**用途**：鉴定详情页**摘要条**（序列、RT、Q、蛋白组、run 信息）。  
**谱图**：由子资源按需加载（见 [谱图查看说明.md](./谱图查看说明.md)）。

### 12.1 响应：`BuMatchDetailOut`

继承 `BuMatchListItemOut`，并增加：

```json
{
  "id": 88001,
  "run_id": 41,
  "run_name": "20200110_Hela_500ng_DIA_25cm_120min_R1.mzML",
  "peptide_id": 501,
  "sequence": "KSTGGKAPR",
  "modified_sequence": "K(UniMod:1)STGGKAPR",
  "precursor_mz": 490.265,
  "precursor_charge": 2,
  "retention_time": 92.46,
  "experimental_mass": 978.52,
  "q_value": 0.0003,
  "score": 0.0003,
  "intensity": 1250000.0,
  "is_decoy_match": false,
  "scan_number": -1,
  "spectrum_native_id": null,
  "protein_group": "P62805;Q71DI3",
  "protein_accessions": ["P62805", "Q71DI3"],
  "genes": "H4C1",
  "search_engine": "DIA-NN",
  "ms_level": 2,
  "entity_type": "PEPTIDE",
  "run": {
    "run_id": 41,
    "file_name": "20200110_Hela_500ng_DIA_25cm_120min_R1.mzML",
    "raw_format": "mzml",
    "file_path": "d:\\dia-shuju\\20200110_Hela_500ng_DIA_25cm_120min_R1.mzML",
    "diann_run_name": "20200110_Hela_500ng_DIA_25cm_120min_R1"
  },
  "rt_window": {
    "rt_start": 91.8,
    "rt_stop": 93.1,
    "rt_apex": 92.46,
    "unit": "min"
  },
  "proteins": [
    { "protein_id": 1001, "accession": "P62805", "gene_name": "H4C1", "description": "Histone H4" },
    { "protein_id": 1002, "accession": "Q71DI3", "gene_name": null, "description": null }
  ],
  "diann": {
    "precursor_id": "12345_67890",
    "lib_qvalue": 0.0001,
    "mass_accuracy": 1.2,
    "ms2_scan": null,
    "resolved_scan": null
  },
  "spectrum_links": {
    "xic": "/api/v1/datasets/hela_dia_20200110/matches/88001/xic",
    "ms2": "/api/v1/datasets/hela_dia_20200110/matches/88001/spectrum/ms2",
    "ms1": "/api/v1/datasets/hela_dia_20200110/matches/88001/spectrum/ms1",
    "mobility_slice": null
  },
  "extra_metadata": {
    "precursor_id": "12345_67890",
    "rt_start": 91.8,
    "rt_stop": 93.1,
    "protein_group": "P62805;Q71DI3",
    "genes": "H4C1"
  }
}
```

#### 新增字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `spectrum_native_id` | `string \| null` | `identification_matches.spectrum_native_id` |
| `ms_level` | `integer` | 固定 `2` |
| `entity_type` | `"PEPTIDE"` | |
| `run` | `BuRunDetail` | 含 `file_path` 供调试；前端展示用 `file_name` |
| `rt_window` | `BuRtWindow` | 来自 `extra_metadata.rt_start/stop` + `retention_time` |
| `proteins` | `BuProteinMini[]` | mapping 展开 |
| `diann` | `object` | 常用 DIA-NN 字段子集 |
| `spectrum_links` | `object` | 相对路径；`mobility_slice` 仅 `bruker_d` 非 null |
| `extra_metadata` | `object` | 完整 JSONB 透传（实现可裁剪 >50KB） |

#### `BuRtWindow`

| 字段 | 来源 |
|---|---|
| `rt_start` | `extra_metadata.rt_start` ← `RT.Start` |
| `rt_stop` | `extra_metadata.rt_stop` ← `RT.Stop` |
| `rt_apex` | `retention_time` ← `RT` |

#### `diann` 子对象（推荐键）

| 键 | Parquet |
|---|---|
| `precursor_id` | `Precursor.Id` |
| `lib_qvalue` | `Lib.Q.Value` |
| `mass_accuracy` | `Mass.Evidence` / `Mass.Acc` |
| `ms2_scan` | `MS2.Scan` |
| `resolved_scan` | 运行时解析后缓存 |

### 12.2 鉴定详情子资源（引用）

| 方法 | 路径 | 响应 |
|---|---|---|
| `GET` | `.../matches/{match_id}/xic` | `BuXicOut` — [谱图查看说明 §G6](./谱图查看说明.md#g6--xicextracted-ion-chromatogram) |
| `GET` | `.../matches/{match_id}/spectrum/ms2` | `SpectrumV1` + `matched_ions` |
| `GET` | `.../matches/{match_id}/spectrum/ms1` | `SpectrumV1` + `markers` |
| `GET` | `.../matches/{match_id}/mobility-slice` | 仅 `bruker_d` |

**约束**：`BuMatchDetailOut` 响应体 **< 32KB**；禁止内嵌 `mz[]`/`intensity[]`。

---

## 13. 错误码与校验

| HTTP | 场景 |
|---|---|
| `404` | `slug` 不存在；`protein_id`/`peptide_id`/`match_id` 不属于该 dataset；非 BU 数据集访问 BU 专用端点 |
| `422` | 查询参数类型错误（FastAPI 默认） |
| `501` | `overview/rt-mz` 未实现（可选） |
| `507` | `spectrum_memory` 容量不足（谱图子资源，非本文） |

---

## 14. Pydantic 模型命名建议

实现时建议新增 `back/app/schemas/bu.py`：

```text
BuOverviewOut, BuOverviewCounts, BuQcBlock, BuQcRow, BuRunSummary
BuRtMzHeatmapOut
BuProteinListItemOut, BuProteinDetailOut, BuCoverageSegment, BuProteinPeptideRef
BuPeptideListItemOut, BuPeptideDetailOut
BuMatchListItemOut, BuMatchDetailOut, BuRtWindow, BuRunDetail
```

路由文件（canonical，与 [P0 C22](./P0-Viewer代码改造规划.md#44-§24-运行时后端r1r7)、[BU运行时 §8.2](./BU运行时后端模块规划.md#82-apiv1bu__init__py-聚合) 一致）：**包内聚合** `back/app/api/v1/bu/`，**非**平铺 `bu_*.py`：

```text
back/app/api/v1/bu/
├── __init__.py          # 聚合 router，api_router.include_router(bu.router)
├── overview.py          # overview、overview/rt-mz
├── chromatogram.py      # TIC/BPC、dia-windows
├── lists.py             # proteins、peptides 列表
├── proteins.py          # protein 详情（或并入 lists.py）
└── matches.py           # matches 列表/详情 + 谱图子资源委托 facade
```

在 `api/v1/__init__.py` 注册 `bu.router`；**不修改**现有 `proteins.py` / `prsms.py`（Top-Down 零修改）。

---

## 15. 修订记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v1.0 | 2026-05-21 | 首版：`overview` / `proteins` / `peptides` / `matches` 完整 schema |
| v1.0.1 | 2026-05-21 | §3.2.1 明确 `GET /datasets` 列表必填 `analysis_mode` |
| v1.1 | 2026-05-21 | §3.2.2 补 `capabilities`/`extra_metadata`/`status`；§4.0 对齐现网数组响应；§9 扩展肽段 `q_max` 与列表字段；非 BU 统一 404 |
| v1.2 | 2026-05-21 | D19：`decoy` 统一为 false 排除、true 包含（§6.1 / §7.1 / §11.1）；§14 路由 canonical 改为 `api/v1/bu/` 包内聚合 |

---

*与 `BU列表与数据集API规范.html` 内容一致。*
