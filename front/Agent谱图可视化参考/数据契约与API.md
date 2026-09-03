# 数据契约与 API

## 1. 事实来源优先级

Agent 判断可视化数据结构时按以下顺序核对：

1. 前端组件实际 Props。
2. 前端 TypeScript 类型。
3. 前端 API 客户端的请求路径和参数。
4. 后端 route 的 response model。
5. 后端 service/reader 实现。

不要只根据截图或字段名称猜测单位。前端 Axios base URL 是 `/api/v1`，见 [`client.ts`](../src/api/client.ts)。

## 2. BU 契约

主要前端类型：[`features/bu/types.ts`](../src/features/bu/types.ts)。前端请求：[`features/bu/api/buClient.ts`](../src/features/bu/api/buClient.ts)。后端 schema：[`back/app/schemas/bu.py`](../../back/app/schemas/bu.py)。

| 功能 | 方法与相对路径 | 前端函数 | 输出/输入 | 后端路由 |
|---|---|---|---|---|
| overview | `GET /datasets/{slug}/overview` | `fetchBuOverview` | `BuOverviewOut` | [`overview.py`](../../back/app/api/v1/bu/overview.py) |
| RT-m/z heatmap | `GET /datasets/{slug}/overview/rt-mz` | `fetchBuRtMzHeatmap` | `BuRtMzHeatmapOut` | [`overview.py`](../../back/app/api/v1/bu/overview.py) |
| protein coverage | `GET /datasets/{slug}/proteins/{id}` | `fetchBuProtein` | `BuProteinDetailOut` | [`proteins.py`](../../back/app/api/v1/bu/proteins.py) |
| match detail | `GET /datasets/{slug}/matches/{id}` | `fetchBuMatch` | `BuMatchDetailOut` | [`matches.py`](../../back/app/api/v1/bu/matches.py) |
| live MS2 | `GET /datasets/{slug}/matches/{id}/spectrum/ms2` | `fetchBuMatchMs2` | `BuSpectrumV1` | [`matches.py`](../../back/app/api/v1/bu/matches.py) |
| live MS1 | `GET /datasets/{slug}/matches/{id}/spectrum/ms1` | `fetchBuMatchMs1` | `BuSpectrumV1` | [`matches.py`](../../back/app/api/v1/bu/matches.py) |
| precursor XIC | `GET /datasets/{slug}/matches/{id}/xic` | `fetchBuMatchXic` | `BuXicOut` | [`matches.py`](../../back/app/api/v1/bu/matches.py) |
| product XIC | `GET /datasets/{slug}/matches/{id}/product-xic` | `fetchBuMatchProductXic` | `BuProductXicOut` | [`matches.py`](../../back/app/api/v1/bu/matches.py) |
| batch product XIC | `POST /datasets/{slug}/matches/{id}/product-xics` | `fetchBuMatchProductXics` | `BuProductXicBatchIn` → `BuProductXicBatchOut` | [`matches.py`](../../back/app/api/v1/bu/matches.py) |
| mobility slice | `GET /datasets/{slug}/matches/{id}/mobility-slice` | `fetchBuMatchMobilitySlice` | `BuMobilitySliceOut` | [`matches.py`](../../back/app/api/v1/bu/matches.py) |
| PFMB slots | `GET /datasets/{slug}/matches/{id}/ms2-slots` | `fetchBuMatchMs2Slots` | `BuMs2SlotListOut` | [`ms2_annotations.py`](../../back/app/api/v1/bu/ms2_annotations.py) |
| PFMB slot annotation | `GET /datasets/{slug}/matches/{id}/ms2-annotation/{prsmIndex}` | `fetchBuMatchMs2Annotation` | `BuMs2AnnotationOut` | [`ms2_annotations.py`](../../back/app/api/v1/bu/ms2_annotations.py) |
| PFMB matrix | `GET /datasets/{slug}/matches/{id}/ms2-annotation-matrix` | `fetchBuMatchMs2AnnotationMatrix` | `BuMs2AnnotationMatrixOut` | [`ms2_annotations.py`](../../back/app/api/v1/bu/ms2_annotations.py) |
| run TIC/BPC | `GET /datasets/{slug}/runs/{runId}/chromatogram` | `fetchBuRunChromatogram` | `BuChromatogramOut` | [`chromatogram.py`](../../back/app/api/v1/bu/chromatogram.py) |
| DIA windows | `GET /datasets/{slug}/runs/{runId}/dia-windows` | `fetchBuRunDiaWindows` | `BuDiaWindowsOut` | [`chromatogram.py`](../../back/app/api/v1/bu/chromatogram.py) |

### 关键单位

- BU XIC 和 chromatogram 的 RT 单位是分钟。
- `BuSpectrumV1.mz` 为 m/z，`intensity` 为原始强度。
- PFMB `neutral_mass` 与 live raw peak m/z 不是同一量；叠加前必须结合 charge 转换并映射。
- `BuMobilitySliceOut.one_over_k0` 是 `1/K0`。

## 3. TD PrSM 契约

主要前端类型：[`api/types.ts`](../src/api/types.ts) 中的 `PrsmListItemOut`、`PrsmDetailOut`。后端 schema：[`back/app/schemas/protein.py`](../../back/app/schemas/protein.py)。

| 功能 | 方法与相对路径 | 前端函数 | 后端路由 |
|---|---|---|---|
| PrSM detail | `GET /datasets/{slug}/cutoffs/{cutoff}/prsms/{prsmId}` | `fetchPrsm` | [`prsms.py`](../../back/app/api/v1/prsms.py) |
| TopFD MS1 JSON | `GET /datasets/{slug}/spectra/ms1/{specId}` | `fetchMs1Spectrum` | [`spectra.py`](../../back/app/api/v1/spectra.py) |
| TopFD MS2 JSON | `GET /datasets/{slug}/spectra/ms2/{specId}` | `fetchMs2Spectrum` | [`spectra.py`](../../back/app/api/v1/spectra.py) |
| mzML scan | `GET /datasets/{datasetId}/runs/{runId}/spectra/{scan}` | `fetchMzmlSpectrum` | [`mzml_spectra.py`](../../back/app/api/v1/mzml_spectra.py) |

TD 返回的 annotation、ms_peaks、raw spectrum 是嵌套 JSON；统一解析必须经过 [`features/prsm/parse.ts`](../src/features/prsm/parse.ts)，不要在页面或图表中分散读取未知字段。

## 4. 纯谱图契约

前端类型：[`features/spectra-only/types.ts`](../src/features/spectra-only/types.ts)。请求：[`features/spectra-only/api/spectraClient.ts`](../src/features/spectra-only/api/spectraClient.ts)。后端：[`mzml_spectra.py`](../../back/app/api/v1/mzml_spectra.py)。

| 功能 | 方法与相对路径 | 前端函数 | 输出 |
|---|---|---|---|
| run TIC/BPC | `GET /datasets/{datasetId}/runs/{runId}/chromatogram` | `fetchSpectraChromatogram` | `SpectraChromatogramOut` |
| scan index | `GET /datasets/{datasetId}/runs/{runId}/scan-index` | `fetchSpectraScanIndex` | `SpectraScanIndexOut` |
| full scan index | 多页聚合 | `fetchSpectraFullScanIndex` | 合并后的 `SpectraScanIndexOut` |
| raw scan spectrum | `GET /datasets/{datasetId}/runs/{runId}/spectra/{scan}` | `fetchSpectraSpectrum` | `SpectraSpectrumOut` |

`fetchSpectraFullScanIndex` 以 2000 条为一页并行补齐全部扫描，用于构建 MS1/MS2 亲子关系。大型数据集上不要在组件内重复发起同样的全量聚合。

### 关键单位

- scan index 的 `retention_time` 是分钟。
- raw spectrum 的 `rt_seconds` 是秒。
- chromatogram 的 `unit_rt` 是 `min`。
- isolation lower/upper 是 m/z 边界。

## 5. 错误契约

图表请求的错误解析集中在 [`lib/apiError.ts`](../src/lib/apiError.ts)。当前可视化会区分：

- 普通加载失败。
- 派生 chromatogram/scan-index 缺失。
- 派生数据 stale。
- 数据源不支持某种 match-level 证据。

新组件应复用 `parseApiError`、`chartQueryRetry` 和 [`PlotStatus`](../src/components/common/plot-status.tsx)，不要把后端错误字符串直接散落到绘图组件。
