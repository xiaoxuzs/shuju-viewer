# BU 运行时后端模块规划

> **文档版本**：v1.0  
> **日期**：2026-05-21  
> **Viewer 项目**：`E:\viewer\`  
> **数据样例**：`d:\dia-shuju\`  
> **状态**：规划稿（确认后实施）  
> **关联文档**：[P0-Viewer代码改造规划.md](./P0-Viewer代码改造规划.md)（C17–C24 运行时任务）、[Bottom-Up数据导入规划.md](./Bottom-Up数据导入规划.md)（ingest / §13 引用本文）、[谱图查看说明.md](./谱图查看说明.md)（G1–G10 / SpectrumV1）、[Viewer接入规划-完整版.md](./Viewer接入规划-完整版.md)（页面 / API 总览）、[BU前端接入规划.md](./BU前端接入规划.md)（前端路由与请求顺序）

---

## 目录

1. [文档目的](#1-文档目的)
2. [运行时 vs 导入：边界](#2-运行时-vs-导入边界)
3. [总体架构](#3-总体架构)
4. [目录结构（新增文件）](#4-目录结构新增文件)
5. [`bu/services` 模块](#5-buservices-模块)
6. [`tdf_reader` 模块](#6-tdf_reader-模块)
7. [`spectrum_memory` 复用边界](#7-spectrum_memory-复用边界)
8. [Router 挂载与 API 分层](#8-router-挂载与-api-分层)
9. [端点清单（v1）](#9-端点清单v1)
10. [依赖注入与 mode guard](#10-依赖注入与-mode-guard)
11. [错误码与响应约定](#11-错误码与响应约定)
12. [缓存策略](#12-缓存策略)
13. [实施顺序与里程碑](#13-实施顺序与里程碑)
14. [验收清单](#14-验收清单)
15. [已定稿决策（D6–D10）](#15-已定稿决策d6d10)

---

## 1. 文档目的

本文只回答一件事：**Bottom-Up DIA 数据集在 `datasets.status = READY` 之后，Viewer 后端如何按需读谱、算图、暴露 API**。

| 本文包含 | 本文不包含 |
|---|---|
| `back/app/bu/services/*` 运行时算法 | parquet 入库（见导入规划 `ingest/bu/`） |
| `back/app/bu/tdf_reader/*` Bruker `.d` 读取 | 前端组件与 React 路由 |
| `back/app/api/v1/bu/*` 路由挂载 | Top-Down `spectra.py` / PrSM 改动 |
| 与 `spectrum_memory` 的调用边界 | 修改 `spectrum_memory` 源码 |

导入规划 §13 中「运行时服务（非 ingest，**另文档**）」即指本文。

---

## 2. 运行时 vs 导入：边界

```text
POST /api/v1/imports  →  import_jobs（薄编排）
                              │
                              ├── TOPPIC  → ingest/universal_toppic_adapter
                              └── DIANN   → ingest/bu/universal_diann_adapter
                                        （写 DB，登记 runs.file_path，不读全谱）

用户打开 /datasets/:slug 或 /matches/:id
                              │
                              └── bu/* 运行时模块（本文）
                                    ├── 读 runs.file_path 指向的 mzML / .d
                                    ├── scan_resolver / xic / b-y 计算
                                    └── 返回 JSON → 前端 BuSpectrumChart 等
```

| 阶段 | 包路径 | 何时运行 | 写 DB？ |
|---|---|---|---|
| 导入 | `back/app/ingest/bu/` | 一次性 job | ✅ 大表批量 insert |
| 运行时 | `back/app/bu/` | 每次 API 请求 | ❌ 仅可选回写 `extra_metadata.resolved_scan` |

**硬约束**（与 `E:\viewer\AGENTS.md` 一致）：

- 算法不进 `import_jobs.py`、不进 `api/v1/*.py` 路由函数体；路由只做校验、调 service、序列化。
- **不修改** Top-Down 已有模块；BU 新增独立包与 router。
- URL **无** `/bu/` 前缀；与 TD 共用 `/api/v1/datasets/{slug}/...`，靠 `analysis_mode` 分叉。

---

## 3. 总体架构

```text
┌─────────────────────────────────────────────────────────────────┐
│ FastAPI  app.main  →  api/v1/__init__.py                        │
│   ├── datasets / imports / proteins / prsms / spectra  （TD 现有）│
│   ├── mzml_spectra                                    （TD+mzML）│
│   └── bu.router  ← 新增挂载（本文 §8）                            │
└────────────────────────────┬────────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
   bu/api handlers    bu/services          bu/tdf_reader
   （薄）              scan_resolver         TIC/BPC/窗口/4D
                       xic_service
                       theoretical_fragments
                       spectrum_facade ──→ spectrum_memory（mzML，只读）
```

**请求典型路径（鉴定详情 MS2）**：

```text
GET .../matches/{id}/spectrum/ms2
  → require_bu_dataset(slug)
  → load match row（run_id, RT, precursor_mz, charge, sequence）
  → spectrum_facade.resolve_ms2(run, match)
       ├── raw_format=mzml  → scan_resolver → get_mzml_spectrum()
       └── raw_format=bruker_d → tdf_reader.get_ms2_frame()（二期同 scan 规则）
  → theoretical_fragments.match_b_y(sequence, peaks, ppm)
  → SpectrumV1 JSON
```

---

## 4. 目录结构（新增文件）

遵循导入规划 §13 的命名，运行时与 ingest 同级分树：

```text
E:\viewer\back\app\
├── bu/                                    # 新建包（运行时专用）
│   ├── __init__.py
│   ├── deps.py                            # require_bu_dataset, require_bu_match
│   # DTO 定义在 app/schemas/bu.py（见 [决策登记表 D15](./决策登记表.md)）；bu/ 内不重复定义
│   ├── services/
│   │   ├── __init__.py
│   │   ├── scan_resolver.py               # RT+m/z+isolation → scan_number
│   │   ├── theoretical_fragments.py       # pyteomics.mass b/y + ppm 匹配
│   │   ├── xic_service.py                 # MS1 提取离子色谱
│   │   ├── spectrum_facade.py             # raw_format 分发；组装 SpectrumV1
│   │   ├── chromatogram_service.py        # TIC/BPC 统一入口（调 mzML 或 tdf）
│   │   ├── overview_service.py            # QC 聚合、rt-mz 分箱
│   │   └── lists_service.py               # proteins / peptides / matches 查询
│   └── tdf_reader/
│       ├── __init__.py
│       ├── session_cache.py               # run_id → tdfpy 句柄 LRU
│       ├── root_resolver.py               # 复用 ingest run_discovery 规则或 import
│       ├── chromatogram.py                # G2/G3 from .d
│       ├── dia_windows.py                 # G5
│       └── mobility_slice.py              # G9
├── api/v1/
│   ├── __init__.py                        # 改：+ include bu.router
│   └── bu/
│       ├── __init__.py                    # 聚合子 router
│       ├── overview.py                    # G1, G4
│       ├── chromatogram.py                # G2, G3, G5
│       ├── lists.py                       # 蛋白/肽段/鉴定列表
│       ├── matches.py                     # match 摘要、G6–G9
│       └── proteins.py                    # 蛋白详情 + G10 coverage
└── ingest/bu/                             # 导入专用（见导入规划，非本文实施）
    └── ...
```

**与导入模块共享**（只 import，不复制算法）：

- `ingest/bu/run_discovery.resolve_bruker_tdf_root()` — `.d` 有效根路径（含 zip 嵌套下钻）。

---

## 5. `bu/services` 模块

### 5.1 `scan_resolver.py`

**职责**：当 `identification_matches.scan_number == -1` 时，在指定 run 的 mzML 中定位 MS2 scan（与 demo_04 一致）。

| 项 | 约定 |
|---|---|
| 输入 | `run_id`, `rt_apex`（分钟）, `precursor_mz`, `charge`；可选 `rt_start`/`rt_stop` |
| 输出 | `scan_number`, `native_id`, `scan_rt_min`, `isolation` 元数据 |
| 算法 | 见 [谱图查看说明 §10](./谱图查看说明.md#10-ms2-scan-定位规则鉴定谱图) |
| 依赖 | `spectrum_memory.get_mzml_spectrum` 的 scan 索引 / 或 bundle 上迭代 ms_level=2 |
| 缓存 | 成功后可 `UPDATE extra_metadata.resolved_scan`（可选，加速二次打开） |

```python
# 公开 API（示意）
def resolve_ms2_scan(
    *,
    dataset_id: int,
    run_id: int,
    rt_apex_min: float,
    precursor_mz: float,
    rt_window_min: float = 0.5,
) -> ResolvedScan: ...
```

**禁止**：无候选时返回随机 scan；禁止跨 `run_id` 解析。

---

### 5.2 `theoretical_fragments.py`

**职责**：由 `Stripped.Sequence` 计算理论 b/y（z=1,2），与实验峰 ±ppm 匹配。

| 项 | 约定 |
|---|---|
| 输入 | `sequence: str`, `mz: float[]`, `intensity: float[]`, `ppm: float = 20` |
| 输出 | `matched_ions: MatchedIon[]`（一峰一最佳匹配，强度优先去重） |
| 库 | `pyteomics.mass`（viewer 已有依赖） |
| v1 范围 | **不含 PTM 修饰质量偏移** |

参考实测：LLLPGELAK @ scan 67726，12 个 b/y 匹配，ppm &lt; 2（demo_04）。

---

### 5.3 `xic_service.py`

**职责**：沿 RT 提取 precursor m/z ± ppm 的 MS1 最强峰强度（G6）。

| 项 | 约定 |
|---|---|
| 输入 | `run_id`, `precursor_mz`, `ppm`, `rt_lo`, `rt_hi`（默认 match RT.Start/Stop ± 5 min） |
| 输出 | `{ rt[], intensity[], precursor_mz, ppm, rt_apex, rt_start, rt_stop }` |
| mzML | 遍历 MS1 scan，`argmax(intensity)` within m/z window |
| .d | v1 可复用 tdf MS1 帧逻辑（与 chromatogram 共用帧迭代） |
| 性能 | 单 match &lt; 2s（demo_05：424 MS1 帧） |

---

### 5.4 `spectrum_facade.py`

**职责**：对上层 API 隐藏 `raw_format` 差异，统一输出 `SpectrumV1`。

```python
def get_ms2_for_match(session, match_id: int, *, ppm: float) -> SpectrumV1: ...
def get_ms1_for_match(session, match_id: int) -> SpectrumV1: ...
```

| `runs.run_metadata.raw_format` | MS2 来源 |
|---|---|
| `mzml` | `scan_resolver` + `get_mzml_spectrum` |
| `bruker_d` | `tdf_reader` 帧 MS2（v1 可与 mzML 同 RT 规则；M8 验收） |

---

### 5.5 `chromatogram_service.py` / `overview_service.py` / `lists_service.py`

| 模块 | 职责 | 对应图表 |
|---|---|---|
| `chromatogram_service` | `type=tic\|bpc`，降采样 ≤8000 点 | G2, G3 |
| `overview_service` | stats + DB COUNT；`rt-mz` 分箱 | G1, G4 |
| `lists_service` | 分页 SQL + 筛选（q_max, run_id, …） | 列表页 P2–P4 |

列表 API 形状与 [BU前端接入规划 §4.4](./BU前端接入规划.md#44-列表-api-形状前端-typescript-期望) 的 `BuListResponse<T>` 对齐。

---

## 6. `tdf_reader` 模块

Viewer **现有代码无** Bruker 读取层；基于 `d:\dia-shuju\plot_spectra.py` / `view_d.py` 的 **tdfpy** 用法封装为独立包，**不**修改 `spectrum_memory`。

### 6.1 `session_cache.py`

| 项 | 约定 |
|---|---|
| 键 | `(dataset_id, run_id)` |
| 值 | 已打开的 `tdfpy` 会话 + 解析后的 `tdf_path` |
| 容量 | LRU ≤ 2 runs（与谱图查看说明 §8 一致） |
| 失效 | 进程重启；路径 `mtime` 变化时驱逐 |

### 6.2 `root_resolver.py`

调用 `ingest.bu.run_discovery.resolve_bruker_tdf_root(outer_path)`，保证与导入期 `runs.file_path` 一致（含 `xxx.d/xxx.d/` 嵌套）。

### 6.3 功能子模块

| 文件 | API 能力 | 算法摘要 |
|---|---|---|
| `chromatogram.py` | G2/G3 | 遍历 `dia.ms1` 帧，`centroid(min_peaks=2)` 后 sum / max intensity；RT 转 **分钟** |
| `dia_windows.py` | G5 | `dia.windows` 按 `isolation_mz` 去重 → `{ mz, width, label }` |
| `mobility_slice.py` | G9 | 找 `abs(frame.time/60 - rt_apex) < 0.1` 的帧 → centroid N×3 |

### 6.4 依赖

```text
# pyproject.toml 新增（实施时）
tdfpy>=0.1  # 与 demo 环境一致
```

`.d` run 在 `capabilities` 中：`has_im: true`, `spectra_source` 可为 `tdf_memory` 或 `mixed`。

---

## 7. `spectrum_memory` 复用边界

| 操作 | 做法 |
|---|---|
| 读 mzML 单 scan | ✅ `from app.spectrum_memory import get_mzml_spectrum` |
| 预载 dataset | ✅ 复用 `spectrum_memory_wiring.ensure_mzml_dataset_resident` |
| 扩展 LRU / 索引结构 | ❌ 不改 `spectrum_memory/*` |
| BU 专用批量迭代 MS1 | ✅ 在 `bu/services` 内通过已载入 bundle 的公开接口迭代；缺接口则在 **bu** 包内写薄 wrapper，不向 spectrum_memory 提 PR |

**`GET /datasets/{slug}` 行为**（现有 `datasets.py`）：

- 已对 `spectra_source == mzml_memory` 预载；BU 混合数据集（`spectra_source=mixed`）时：
  - v1：**仍执行** `ensure_mzml_dataset_resident`，但**只加载 mzML runs**（`.d` run 不进入 spectrum_memory）；
  - `.d` 按需由 `tdf_reader.session_cache` 打开。

**capabilities 扩展**（导入 finalize 写入，运行时读取）：

```json
{
  "spectra_source": "mixed",
  "has_ms1": true,
  "has_ms2": true,
  "has_im": true,
  "analysis_shape": "bottom_up_dia"
}
```

---

## 8. Router 挂载与 API 分层

### 8.1 挂载点（`api/v1/__init__.py`）

```python
from app.api.v1 import bu

api_router = APIRouter(prefix="/api/v1")
# ... 现有 include_router ...
api_router.include_router(bu.router)   # 新增，放在末尾避免路径遮蔽
```

### 8.2 `api/v1/bu/__init__.py` 聚合

```python
from fastapi import APIRouter
from app.api.v1.bu import chromatogram, lists, matches, overview, proteins

router = APIRouter(tags=["bottom-up"])
router.include_router(overview.router)
router.include_router(chromatogram.router)
router.include_router(lists.router)
router.include_router(matches.router)
router.include_router(proteins.router)
```

### 8.3 与 Top-Down 路由共存

| 路径 | TD | BU | 分叉方式 |
|---|---|---|---|
| `GET /datasets/{slug}` | ✅ | ✅ | 共用；响应 `analysis_mode` 不同 |
| `GET /datasets/{slug}/spectra/ms2/{id}` | ✅ TopFD | ❌ | TD 专用，BU 不调 |
| `GET /datasets/{slug}/matches/{id}/spectrum/ms2` | ❌ | ✅ | `require_bu_dataset` |
| `GET /datasets/{id}/runs/{run_id}/spectra/{scan}` | ✅ mzml_spectra | 🟡 可选 | BU 优先走 match 级 API |

**原则**：BU 端点集中在 `api/v1/bu/`，但 **path prefix 仍为** `/datasets/{slug}`，满足前端「无 `/bu/` 根」约束。

### 8.4 Handler 薄层模板

```python
@router.get("/datasets/{slug}/matches/{match_id}/spectrum/ms2")
def match_ms2(slug: str, match_id: int, ppm: float = 20, session=Depends(get_db)):
    dataset = require_bu_dataset(session, slug)
    match = require_bu_match(session, dataset["dataset_id"], match_id)
    try:
        return spectrum_facade.get_ms2_for_match(session, match_id, ppm=ppm)
    except ScanNotFoundError as exc:
        raise HTTPException(404, detail={"error": "ms2_scan_not_found", **exc.as_dict()})
```

---

## 9. 端点清单（v1）

与 [谱图查看说明 §5–§6](./谱图查看说明.md#5-谱图一览表v1) 及 [Viewer接入规划 §11](./Viewer接入规划-完整版.md#11-后端-api-设计) 对齐。

### 9.1 数据集与整体页

| 方法 | 路径 | 模块 | 图表 |
|---|---|---|---|
| GET | `/datasets/{slug}` | 现有 `datasets.py` | — |
| GET | `/datasets/{slug}/overview` | `bu/overview` | G1 |
| GET | `/datasets/{slug}/overview/rt-mz` | `bu/overview` | G4 可选 |

> Run 列表在 `GET /datasets/{slug}` 的 `bu_runs` 与 `GET .../overview.runs` 中返回；**无**独立 `GET .../runs` 端点。

### 9.2 色谱与窗口（整体页）

| 方法 | 路径 | 模块 | 图表 |
|---|---|---|---|
| GET | `/datasets/{slug}/runs/{run_id}/chromatogram?type=tic\|bpc` | `bu/chromatogram` | G2, G3 |
| GET | `/datasets/{slug}/runs/{run_id}/dia-windows` | `bu/chromatogram` | G5 |

### 9.3 列表（表格，无谱图）

| 方法 | 路径 | 模块 |
|---|---|---|
| GET | `/datasets/{slug}/proteins` | `bu/lists` |
| GET | `/datasets/{slug}/peptides` | `bu/lists` |
| GET | `/datasets/{slug}/matches` | `bu/lists` |

查询参数：见 [BU前端接入规划 §2.5](./BU前端接入规划.md#25-url-查询参数约定列表页共用)。

### 9.4 鉴定详情（谱图核心）

| 方法 | 路径 | 模块 | 图表 |
|---|---|---|---|
| GET | `/datasets/{slug}/matches/{match_id}` | `bu/matches` | 摘要 |
| GET | `/datasets/{slug}/matches/{match_id}/xic?ppm=10` | `bu/matches` | G6 |
| GET | `/datasets/{slug}/matches/{match_id}/spectrum/ms2?ppm=20` | `bu/matches` | G7 |
| GET | `/datasets/{slug}/matches/{match_id}/spectrum/ms1` | `bu/matches` | G8 |
| GET | `/datasets/{slug}/matches/{match_id}/mobility-slice` | `bu/matches` | G9 |

### 9.5 蛋白详情

| 方法 | 路径 | 模块 | 图表 |
|---|---|---|---|
| GET | `/datasets/{slug}/proteins/{protein_id}` | `bu/proteins` | G10 |

---

## 10. 依赖注入与 mode guard

**文件**：`back/app/bu/deps.py`

```python
def require_bu_dataset(session, slug: str) -> dict:
    ds = require_dataset(session, slug)  # 复用 universal_compat
    if ds.get("analysis_mode") != "BOTTOM_UP":
        raise HTTPException(404, "not a bottom-up dataset")
    return ds

def require_bu_match(session, dataset_id: int, match_id: int) -> dict:
    row = ...  # identification_matches + join peptides, runs
    if row is None or row["entity_type"] != "PEPTIDE":
        raise HTTPException(404, "match not found")
    return row
```

| Guard | 行为 |
|---|---|
| TD 数据集访问 BU 路径 | **404** + `not_bottom_up`（与 API §3.2、决策登记表一致） |
| BU 数据集访问 `/spectra/ms2/{id}` | 前端禁止；后端 TD 路由可能 404（无 TopFD 文件） |
| `raw_format != bruker_d` 请求 dia-windows / mobility-slice | 404 `incompatible_run_format` |
| match.run_id ≠ 请求隐式 run | 禁止；match 级 API 以 DB 的 `run_id` 为准 |

---

## 11. 错误码与响应约定

| HTTP | `error` 键 | 场景 |
|---|---|---|
| 404 | `dataset_not_found` | slug 不存在 |
| 404 | `not_bottom_up` | mode guard |
| 404 | `match_not_found` | match_id 无效 |
| 404 | `ms2_scan_not_found` | scan_resolver 无候选 |
| 404 | `run_file_missing` | mzML/.d 路径不存在 |
| 409 | `spectrum_not_resident` | mzML 未预载（同现有 mzml_spectra） |
| 507 | `insufficient_spectrum_memory` | CapacityError |

MS2 失败响应示例（谱图查看说明 §10）：

```json
{
  "error": "ms2_scan_not_found",
  "match_id": 12345,
  "rt_apex": 92.46,
  "precursor_mz": 477.3051
}
```

---

## 12. 缓存策略

| 资源 | 位置 | 策略 |
|---|---|---|
| mzML scan 索引 | `spectrum_memory` | 按 dataset_id 预载；BU 只读 |
| `.d` 句柄 | `tdf_reader.session_cache` | LRU 2 runs |
| TIC/BPC | `chromatogram_service` 可选进程内缓存 | 键 `(run_id, type)` |
| XIC | 默认不缓存 | 可选 `(match_id, ppm)` 短缓存 |
| `resolved_scan` | DB `extra_metadata` | 首次解析后回写 |

---

## 13. 实施顺序与里程碑

| 步骤 | 交付 | 依赖 | 里程碑 |
|---|---|---|---|
| R1 | `bu/deps.py` + `app/schemas/bu.py`（SpectrumV1 等） | 导入完成 M1 | — |
| R2 | `scan_resolver` + `theoretical_fragments` + `spectrum_facade`（mzML） | spectrum_memory | M5 |
| R3 | `api/v1/bu/matches.py`（ms2/ms1/xic）+ router 挂载 | R2 | M5–M6 |
| R4 | `lists_service` + `api/v1/bu/lists.py` | DB 有数据 | M4 |
| R5 | `overview_service` + chromatogram（mzML TIC） | R4 | M4 |
| R6 | `tdf_reader` + chromatogram/dia-windows/mobility | tdfpy | M8 |
| R7 | `proteins` API + coverage | 序列字段 | M7 |

与 [Viewer接入规划 §15](./Viewer接入规划-完整版.md#15-实施里程碑) 前端里程碑对齐：后端 **R4/R5 先于或并行 M4**，**R2/R3 对应 M5–M6**。

---

## 14. 验收清单

| # | 检查项 | 期望 |
|---|---|---|
| 1 | `analysis_mode=BOTTOM_UP` 数据集 | BU 端点 200；TD prsm 端点不可用 |
| 2 | TD histone 数据集 | 现有 API 回归通过；BU 新路由返回 404 |
| 3 | LLLPGELAK match MS2 | scan ≈ 67726；≥10 个 b/y 匹配 |
| 4 | XIC | RT 窗口阴影字段齐全；424 点量级 |
| 5 | TIC | `unit_rt=min`；过长 run 带 `downsampled: true` |
| 6 | `.d` run dia-windows | 返回窗口列表；mzML run 请求 G5 → 404 |
| 7 | `features/prsm` / `spectrum_memory` diff | **零修改** |
| 8 | 列表 `/matches?q_max=0.01` | total ≈ 110,026 |

---

## 15. 已定稿决策（D6–D10）

> 完整 19 项见 [决策登记表.md](./决策登记表.md)。

| # | 问题 | 定稿 | 状态 |
|---|---|---|---|
| D6 | 包名 `bu/` vs `bottom_up/` | 统一 **`back/app/bu/`** | ✅ |
| D7 | 混合数据集预载策略 | v1 仅 mzML 走 spectrum_memory；`.d` 懒打开 | ✅ |
| D8 | BU 列表 API 位置 | **新建 `api/v1/bu/*`**，TD 文件零改 | ✅ |
| D9 | `resolved_scan` 回写 DB | 写 **`extra_metadata.resolved_scan`** | ✅ |
| D10 | MS2 对 `.d` run v1 | M5 仅 mzML；M8 补 tdf；v1 不支持 `.d` match 读 MS2 | ✅ |

---

## 附录：与导入规划 §13 对照

| 导入规划占位 | 本文落点 |
|---|---|
| `bu/services/scan_resolver.py` | §5.1 |
| `bu/services/theoretical_fragments.py` | §5.2 |
| `bu/services/xic_service.py` | §5.3 |
| （未写）`tdf_reader` | §6 |
| （未写）router 挂载 | §8 |

---

## 附录：文档关系

```text
Bottom-Up数据导入规划.md      → ingest/bu/*（一次性入库）
BU运行时后端模块规划.md（本文） → bu/* + api/v1/bu/*（按需读谱）
谱图查看说明.md               → G1–G10 算法与 DTO 真值
BU前端接入规划.md             → 请求顺序与 TypeScript 类型
Viewer接入规划-完整版.md        → 产品页与里程碑总览
```

---

*文档 v1.0 · BU 运行时后端专项规划 · 确认后可进入 R1（schemas + deps）实施。*
