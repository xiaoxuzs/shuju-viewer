# 热图、散点与 DIA

## 1. RT × precursor m/z 热图

组件：[`RtMzMiniHeatmap`](../src/features/bu/components/overview/RtMzMiniHeatmap.tsx)。

- 位置：BU overview。
- 输入：`BuRtMzHeatmapOut`。
- 渲染：固定宽度 React SVG；横轴 RT、纵轴 precursor m/z。
- 颜色：全局 `CHART_COLORS.heat` 六级色板。
- 每个非零 bin 是一个 `<rect>`，原生 `<title>` 提供 RT、m/z 和 count。
- `total_points`、维度或 `max_count` 为零时显示专用空状态。
- 数据请求：`fetchBuRtMzHeatmap`；支持 run、q_max、bin 数和 decoy 参数。

主要测试：[`bu-overview-chart-states.spec.ts`](../tests/bu-overview-chart-states.spec.ts)。

## 2. PFMB slot RT × fragment intensity 热图

组件：[`BuPfmbHeatmap`](../src/features/bu/components/match-detail/BuPfmbHeatmap.tsx)。

- 输入：`BuMs2AnnotationMatrixOut`，包含 slots、fragments、intensity、detected 和 apex slot。
- 行：碎片 family；列：PFMB slot RT。
- 强度颜色：D3 `interpolateViridis(log1p(intensity)/logMax)`。
- 检测状态区分：`detected`、`matched-zero`、`not-detected`、`legacy-zero`。
- 可点击 cell/列以切换 RT/slot，并可高亮碎片 family。
- tooltip 包含离子、slot、RT、强度、归一化 log 和检测状态。
- 默认最多显示 20 行，可展开全部。
- 不能把“匹配但强度为零”误写为“未检测”；旧 matrix 没有 detected 元数据时必须保留 legacy 状态。

外层编排：[`BuPfmbAnnotationCard`](../src/features/bu/components/match-detail/BuPfmbAnnotationCard.tsx)。数据请求：`fetchBuMatchMs2AnnotationMatrix`。

主要测试：[`bu-pfmb-visuals.spec.ts`](../tests/bu-pfmb-visuals.spec.ts)、[`bu-rt-linkage.spec.ts`](../tests/bu-rt-linkage.spec.ts)。

## 3. PFMB 质量摘要图形

组件：[`BuPfmbQualitySummary`](../src/features/bu/components/match-detail/BuPfmbQualitySummary.tsx)。

它把 `BuMs2AnnotationOut` 与可选 matrix 转成多种紧凑视觉指标：

- b/y/c/z· 系列计数。
- 肽段切割覆盖。
- ppm 误差的中位数、四分位和直方分箱。
- 每个 RT slot 的匹配峰计数 SVG，可点击切换 RT。
- 对缺失数据和异常范围有明确提示。

主要测试：[`bu-pfmb-quality.spec.ts`](../tests/bu-pfmb-quality.spec.ts)。

## 4. DIA isolation window map

组件：[`DiaWindowMap`](../src/features/bu/components/spectrum/DiaWindowMap.tsx)。

- 位置：BU overview 的选中 run。
- 输入：`BuDiaWindowsOut`。
- 渲染：React SVG；每个 DIA window 一行矩形，X 轴为 m/z。
- window 的中心、宽度和 label 决定位置、大小和行标签。
- 空 window 数组显示专用空状态。
- 数据请求：`fetchBuRunDiaWindows`。

## 5. m/z × ion mobility scatter

组件：[`MzMobilityScatter`](../src/features/bu/components/spectrum/MzMobilityScatter.tsx)。

- 位置：BU match detail。
- 输入：`BuMobilitySliceOut`。
- 横轴 m/z，纵轴 `1/K0`，颜色表示 `log10(intensity + 1)`。
- 最多渲染约 4500 个点，按固定步长采样，避免 SVG 节点失控。
- `<title>` tooltip 显示 m/z、1/K0 和格式化强度。
- 数据请求：`fetchBuMatchMobilitySlice`。

## 6. 颜色约束

- 通用离散色与热图色板：[`chartColors.ts`](../src/features/theme/chartColors.ts)。
- PFMB 离子系列颜色：[`pfmbSeries.ts`](../src/features/bu/components/match-detail/pfmbSeries.ts)。
- CSS token 实际值：[`globals.css`](../src/styles/globals.css)。

新热图/散点图应读取主题 token，不要硬编码只适合浅色背景的颜色。
