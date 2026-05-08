# `front/src/pages/PrsmDetailPage.tsx` 逐行解释

> 来源文件：`front/src/pages/PrsmDetailPage.tsx`
>
> 这是前端最复杂的页面：把 **PrSM 详情 JSON**（annotated_protein + ms_peaks）与 **谱图来源**（TopFD JS 或 mzML memory）组合起来，渲染 Sequence coverage、MS1/MS2、Fragmentation view、Matched peaks 表格与全屏谱图。

---

## L1-L38（模块定位与依赖）

- React hooks：`useEffect/useMemo/useState`
- Router：`useParams` 读取 `slug/cutoff/prsmId`，`Link` 用于页面跳转
- React Query：统一异步数据获取与缓存
- API：
  - `fetchPrsm`：取 `PrsmDetailOut`
  - `fetchDataset`：取 capabilities（决定谱图来源）
  - `fetchMs1Spectrum/fetchMs2Spectrum`：TopFD JS 谱图
  - `fetchMzmlSpectrum`：mzML memory 谱图
- 解析层（`features/prsm/parse`）：
  - `parseAnnotatedProtein`：序列注释
  - `parseMsPeaks`：去卷积 peak + matched ions
  - `parseRawSpectrum`：把谱图 JSON 归一化成前端 `RawSpectrum`
- 可视化组件：
  - `SpectrumChart`：D3 光谱图（支持 wheel zoom / brush zoom / tooltip）
  - `SequenceView`、`FragmentationView`、`MatchedPeaksTable`、`MatchedPeakSpectrumPanel`、`SpectrumModal`

## L42-L52：`useModalHeight`

- 计算并维护全屏 modal 的图表高度：
  - 默认高度为窗口高度的 72%，下限 360
  - 监听 resize，窗口变化时更新高度

## L54-L79：取路由参数 + 拉取 PrSM 详情 + 解析 JSON

- `useParams()`：
  - `slug/cutoff/prsmId` 来自 URL
  - `prsmIdNum = Number(prsmId)`：后端接口期望 number
- `prsmQuery = useQuery(...)`：
  - key：`["prsm", slug, cutoff, prsmIdNum]`
  - fn：`fetchPrsm(slug, cutoff, prsmIdNum)`
  - enabled：必须是合法数字
- `datasetQuery = useQuery(...)`：
  - key：`["dataset", slug]`
  - 目的：读取 `capabilities.spectra_source`（与 PrSM 并行拉取，避免先拿到 PrSM 仍按旧来源请求谱图）
  - **`staleTime: 0`** + **`refetchOnMount: "always"`**：避免 React Query 缓存里仍是旧 `capabilities`（例如导入后从 TopFD 切到 mzML 时仍误走 `/spectra/ms1/...`）
- `spectraSource`：
  - 默认 `"topfd_js"`
  - 若 `dataset.capabilities["spectra_source"] === "mzml_memory"` 则使用 **`fetchMzmlSpectrum(dataset_id, run_id, scan)`**（`dataset_id`/`run_id` 来自 **`PrsmDetailOut`**）
- `parsed = useMemo(...)`：
  - 把 `prsm.annotated_protein/ms_peaks` 解析成前端更好用的数据结构

## L81-L85：解析 ms1/ms2 的 id/scan（只取第一个）

- TopPIC 字段常是用 `,;空格` 分隔的字符串：
  - `ms1_ids/ms2_ids/ms1_scans/ms2_scans`
- 页面选择“默认 apex”策略：只取 split 后的第一个值

## L86-L117：拉取 MS1/MS2 谱图（两套来源）

- `ms1Query`：
  - 若 `spectraSource === "mzml_memory"`：
    - 必须有 `ms1Scan`，调用 `fetchMzmlSpectrum(prsm.dataset_id, prsm.run_id, ms1Scan)`
  - 否则：
    - 必须有 `ms1Id`，调用 `fetchMs1Spectrum(slug, ms1Id)`
  - enabled 条件按来源分别检查 id/scan 是否存在
- `ms2Query` 同理：
  - mzML：按 ms2Scan
  - TopFD：按 ms2Id

## L119-L132：统一构造图表输入数据（useMemo）

- `ms1ChartPeaks`：
  - `buildRawChartPeaks(ms1Query.data)`：把 raw spectrum 解析成 `{mz,intensity}[]`
- `ms2RawSpectrum`：
  - `parseRawSpectrum(ms2Query.data)`：归一化后的 `RawSpectrum`
- `ms2ChartPeaks`：
  - `buildMs2ChartPeaks(ms2RawSpectrum, parsed.peaks)`：
    - 将 matched ions（来自 ms_peaks 的去卷积峰）叠加到 raw MS2 上（最近邻 m/z + 容差）

## L134-L145：缩放（zoom）与 modal 状态

- 两套 zoom：
  - inline（小图）zoom
  - modal（全屏）zoom
- 设计目的：
  - 全屏图关闭再打开时，zoom 状态可以保留（由父组件 state 持有）
  - 不影响 inline 图的显示
- `peakDetail`：
  - 记录用户在 matched peaks 表格里点击的 peak+ion，用于右侧 detail panel 的局部同位素包络视图

## L153-L168：在“谱图真正切换”时重置 zoom / 清空 peakDetail

- 依赖项使用三元表达式：
  - mzML 模式按 scan 变化
  - TopFD 模式按 spec id 变化
- 这样：
  - 关闭/打开 modal 不会触发 zoom reset
  - 只有换了谱（不同 scan/spec）才 reset

## L170-L172：precursor marker

- 若 `prsm.precursor_mz` 存在，在 MS1 图上画一条 marker（vertical dashed line），用于定位 precursor。

## L174-L199：加载/错误/空态

- prsmQuery loading：用 Skeleton 占位
- prsmQuery error：用 Card 显示错误
- prsm 不存在：return null

## L200-L441：主渲染

### PageHeader（L202-L220）

- breadcrumbs：
  - Datasets → dataset → PrSMs 列表 → 当前 PrSM
- action：
  - 链接回当前 PrSM 的 proteoform 详情页

### Stat cards（L222-L230）

- 展示 e-value/p-value、matched 数量、precursor m/z、charge 等摘要指标

### Sequence coverage（L232-L270）

- 若 `parsed.protein` 存在才显示：
  - SequenceView 渲染 residue/cleavage/mass_shift 等注释

### MS1/MS2 图（L272-L332）

- 左侧 MS1：
  - loading/error/成功三态
  - 成功时渲染 SpectrumChart（允许打开 modal）
- 右侧 MS2：
  - 同上，但 peaks 叠加 matched ions

### Fragmentation view（L334-L356）

- 仅当：
  - `parsed.protein` 存在
  - 且 `parsed.peaks.length > 0`
- 用 FragmentationView 在“质量空间”展示去卷积峰与离子注释

### Matched peaks table + detail panel（L358-L388）

- MatchedPeaksTable：
  - onMatchedPeakClick 设置 `peakDetail`
  - selectedDetailKey 用于高亮选中行
- MatchedPeakSpectrumPanel：
  - 需要 ms2RawSpectrum + ms2ChartPeaks
  - 显示 envelope overlay（靠 `peak_id` 对齐 TopFD `envelopes.id`）

### Fullscreen SpectrumModal（L390-L438）

- MS1/MS2 各自一个 modal
- actions 提供 reset zoom
- modal 内复用 SpectrumChart，但使用 modalZoom state

## L443-L461：`ResetZoomButton`

- 小按钮组件：调用传入 onClick，将 zoom 重置为 DEFAULT_ZOOM

## L463-L537（Chart peaks 构造函数）

- `buildRawChartPeaks(raw)`：
  - `parseRawSpectrum` 后取 `peaks`，映射成 ChartPeak[]
- `buildMs2ChartPeaks(s, deconv)`：
  - 若 raw spectrum 不存在：退化为直接画去卷积峰（monoMz/intensity）
  - 否则：
    - 把 matched 的去卷积峰按 monoMz 排序
    - 对每个 raw peak 用二分近邻搜索找到距离 < tol 的去卷积峰
    - 若命中则给 raw peak 填上 ion/ionPos/charge/tooltip，用于上色与 label

