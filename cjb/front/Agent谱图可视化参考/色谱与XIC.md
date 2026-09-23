# 色谱与 XIC

## 1. 基础渲染器

[`BuInteractivePlot`](../src/features/bu/components/spectrum/BuInteractivePlot.tsx) 是当前所有二维连续曲线的基础渲染器，使用 D3 + SVG。它支持：

- 单序列 `points` 或多序列 `series`。
- line/fill、legend、RT band、垂直 guide。
- 最近点 tooltip 和可选点击回调。
- brush X 缩放、Y 缩放、reset、受控/非受控 zoom。
- 自定义 Y domain/ticks、坐标轴缩放单位和 reference max。
- 大图按钮和 `onFirstRender`。

不要在新的 TIC/XIC 组件里重新实现 D3 坐标轴和缩放；优先把业务数据转换为 `BuPlotPoint`/`BuPlotSeries`。

## 2. 组件层次

```text
BuInteractivePlot
├─ BuChromatogramChart
│  ├─ BuOverviewPage
│  └─ SpectraOnly ChromatogramPanel
├─ BuXicChart
│  └─ BuMatchDetailPage
└─ BuProductIonXicChart
   └─ BuProductIonXicCard
      └─ BuMatchDetailPage
```

### TIC/BPC

[`BuChromatogramChart`](../src/features/bu/components/spectrum/BuChromatogramChart.tsx) 接收 `BuChromatogramOut`：

- `type` 为 `tic` 或 `bpc`。
- RT 单位固定为分钟。
- 处理 downsampled/original point count 文案。
- 强度达到十亿级时使用 `×10⁹` 轴缩放。

它由 BU 总览和纯谱图 [`ChromatogramPanel`](../src/features/spectra-only/components/ChromatogramPanel.tsx) 共同复用。后者只负责请求、TIC/BPC 切换和错误状态。

### 前体同位素 XIC

[`BuXicChart`](../src/features/bu/components/spectrum/BuXicChart.tsx) 接收 `BuXicOut`：

- M/M+1/M+2 形成多个 series。
- `rt_start`/`rt_stop` 形成识别 RT band。
- `rt_apex` 形成垂直 guide。
- 点击曲线最近点后返回 `BuXicPointSelection`，用于检查 RT 和 PFMB slot 联动。

### 产物离子 XIC

[`BuProductIonXicCard`](../src/features/bu/components/match-detail/BuProductIonXicCard.tsx) 负责业务编排：

- 选择上限为 8，规则在 [`productIonSelection.ts`](../src/features/bu/components/match-detail/productIonSelection.ts)。
- 使用批量 POST，避免每个离子一条请求；请求和映射在 [`productIonBatch.ts`](../src/features/bu/components/match-detail/productIonBatch.ts)。
- 用 [`productIonColors.ts`](../src/features/bu/components/match-detail/productIonColors.ts) 保持增删选择后的颜色稳定。
- 用 [`productIonXicViewModel.ts`](../src/features/bu/components/match-detail/productIonXicViewModel.ts) 生成 raw/normalized trace。
- 错误、stale、无信号和未选择状态限制在卡片内部，不隐藏 MS1/MS2。

[`BuProductIonXicChart`](../src/features/bu/components/spectrum/BuProductIonXicChart.tsx) 只负责图形：

- raw 模式按可见最大值加 12% headroom。
- normalized 模式范围为 0–115%，100% 为 reference max。
- 可叠加 identification RT、inspected RT、MS2 scan RT 和 RT window。
- 内置大图并为大图保存独立 zoom。

## 3. RT 联动

BU 详情中至少有三种 RT 语义：

| RT | 来源 | 用途 |
|---|---|---|
| identification RT | match metadata | 默认识别位置、XIC guide |
| XIC selected RT | 用户点击 XIC | 选择最近 PFMB slot 或 live MS2 |
| PFMB slot RT | 预计算 Fragment Match | 切换 annotation/matrix 列和可选 live MS2 |

容差常量 `RT_LINK_TOLERANCE_MIN = 0.5` 位于 [`bu/utils.ts`](../src/features/bu/utils.ts)。不要在图表内部重新定义 RT 联动规则。

联动和锁定行为由 [`BuMatchDetailPage.tsx`](../src/features/bu/pages/BuMatchDetailPage.tsx)、[`SelectedEvidenceBar.tsx`](../src/features/bu/components/match-detail/SelectedEvidenceBar.tsx) 和 [`FollowPfmbSlotControls.tsx`](../src/features/bu/components/match-detail/FollowPfmbSlotControls.tsx) 协同完成。

## 4. 数据来源

| 数据 | 前端请求 | 输出类型 |
|---|---|---|
| BU run TIC/BPC | `fetchBuRunChromatogram` | `BuChromatogramOut` |
| 纯谱图 TIC/BPC | `fetchSpectraChromatogram` | `SpectraChromatogramOut` |
| 前体 XIC | `fetchBuMatchXic` | `BuXicOut` |
| 单产物离子 XIC | `fetchBuMatchProductXic` | `BuProductXicOut` |
| 批量产物离子 XIC | `fetchBuMatchProductXics` | `BuProductXicBatchOut` |

前端请求见 [`buClient.ts`](../src/features/bu/api/buClient.ts) 和 [`spectraClient.ts`](../src/features/spectra-only/api/spectraClient.ts)。完整端点见[数据契约与API](./数据契约与API.md)。

## 5. 关键测试

- [`bu-match-detail.spec.ts`](../tests/bu-match-detail.spec.ts)：XIC 点击、产物离子增删、raw/normalized、错误/空状态。
- [`product-ion-selection.spec.ts`](../tests/product-ion-selection.spec.ts)：稳定 ID、上限和选择规则。
- [`bu-rt-linkage.spec.ts`](../tests/bu-rt-linkage.spec.ts)：XIC、PFMB slot、live MS2 的 RT 联动与锁定。
- [`bu-overview-chart-states.spec.ts`](../tests/bu-overview-chart-states.spec.ts)：总览色谱/热图/DIA 的加载、空和错误状态。
- [`page-transition.spec.ts`](../tests/page-transition.spec.ts)：切换 run 时等待新色谱首帧。
