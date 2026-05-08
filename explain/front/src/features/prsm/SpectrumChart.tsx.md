## `front/src/features/prsm/SpectrumChart.tsx` 逐行解释

> 目标：把一个质谱谱图（stick spectrum）画成交互式 SVG：包含坐标轴、网格、峰（未匹配灰色 + 匹配离子着色）、可选标记线（precursor）、可选引导虚线、可选包络同位素“空心圆”覆盖层、悬浮 tooltip、框选 X 缩放（brush）、滚轮缩放（X/Y 两轴）、双击复位、以及“受控/非受控”两种 zoom 状态管理。

下面按源码行号解释（以仓库当前版本为准）。

---

### L1-L4：React、D3、图标与 className 工具

- **L1**：导入 React hooks。该组件大部分渲染发生在 D3 对 SVG 的直接操作上，但仍需要 React 管理容器宽度、tooltip 状态、zoom 状态等。
- **L2**：导入 D3。这里主要用到：
  - `scaleLinear` 做比例尺
  - `axisBottom/axisLeft` 画坐标轴
  - `brushX` 做框选缩放
  - `bisector` 做 hover 最近峰查找
  - `format` 做数值格式化
  - `select` 做 SVG DOM 操作
- **L3**：右上角的按钮图标（放大、复位）。
- **L4**：`cn` 用于拼接 Tailwind class。

---

### L6-L20：`ChartPeak` —— 谱图“渲染峰”统一数据结构

- **L6-L9**：每个峰至少要有 `mz` 与 `intensity`。
- **L9-L20**：可选字段用于“匹配离子”的可视增强：
  - **`ion`**：存在即表示这是“已匹配”峰，会变色并在 tooltip/标注中显示离子类型（如 `C`、`Y`、`Z_DOT`）。
  - **`ionPos`**：离子位置（显示为下标），用于让图上标注更接近 TopMSV 的风格（例如 `C₃₉`）。
  - **`tooltip`**：额外 tooltip 文本（例如组合离子信息）。
  - **`charge`**：电荷（用于 tooltip 与图上上标）。

这些字段来自上游解析逻辑（例如 `PrsmDetailPage.tsx` 里的 `buildMs2ChartPeaks` / `buildRawChartPeaks`）。

---

### L22-L36：缩放模型 `Zoom` 与工具函数

- **L22-L30**：定义 zoom 状态：`x` 与 `y` 两个轴分别可以是：
  - `null`：表示“自动域”（X 用全范围；Y 用当前可见范围内最大强度自动计算）
  - `[min,max]`：明确指定域（即用户缩放/拖拽后的范围）
- **L32**：`DEFAULT_ZOOM` 两轴都为 `null`，代表完全复位。
- **L34-L36**：`isZoomed` 判断当前是否处于任何轴的非默认缩放状态，用于启用/禁用 “reset” 按钮。

---

### L38-L83：Props 与覆盖层/引导线能力

这段是组件对外的“功能开关”和“数据输入”。

- **L38-L47**：基础渲染配置
  - `peaks`：要画的峰列表。
  - `xLabel`/`yLabel`：坐标轴标题。
  - `height`：SVG 高度（宽度由容器自适应）。
  - `marker`：可选垂直线（如 MS1 precursor m/z）。
  - `xDomain`：可选的全局 X 域覆盖（强制显示某个范围，而不是用峰的最小/最大 m/z）。
  - `emptyHint`：无数据时提示文案。
- **L48-L55**：受控 zoom（controlled zoom）
  - `zoom` + `onZoomChange`：父组件可完全接管 zoom 状态（典型场景：全屏 modal 打开/关闭时希望 zoom 不丢失）。
  - 若不提供 `zoom`，本组件用内部 `useState` 自己管理，并在 `peaks` 变化时自动复位（L253-L257）。
- **L55-L57**：`onOpenFull`：若提供则显示右上角 enlarge 按钮。
- **L58-L61**：`annotationGuidesMz`：一组 m/z 竖向虚线（背后逻辑：在 matched-peak detail 或 envelope 场景下，强调特定 m/z）。
- **L62-L74**：`envelopeOverlay` 与 `yPercentBase`
  - **`envelopeOverlay`**：在 stick 上叠加空心圆（一个 envelope 的同位素峰），并允许对其中一个点加文字标注。
  - **`yPercentBase`**：如果传入，则 Y 轴刻度显示为相对百分比（0/25/50/75/100%），用于“局部窗口”视图更符合 TopMSV 习惯。
- **L78-L83**：覆盖层点的结构 `EnvelopeOverlayPoint`。

---

### L85-L103：离子类型 → 配色与显示 token

- **L85-L86**：用集合区分 N 端离子（B/C/A）与 C 端离子（Y/Z/Z_DOT/X）。
- **L88-L93**：`colorFor(peak)`
  - 未匹配（无 `ion`）→ 统一灰色。
  - N 端 → CSS 变量 `--ion-n`
  - C 端 → CSS 变量 `--ion-c`
  - 其他（例如 shift 类）→ `--ion-shift`
  - 这样可以保证颜色在表格、ladder、谱图里一致。
- **L95-L103**：`displayIonLetter`
  - 将 `Z_DOT` 显示为 `Z•`（TopPIC/TopMSV 的约定），其他离子类型直接显示。

---

### L105-L175：高性能渲染的关键：二分 + 下采样

谱图可能非常密（尤其 MS1）。如果把“每个峰都画出来并参与 hover 查找”，性能会很差。这里的策略是：
1) 始终保留所有“匹配峰”（有颜色/有意义）。
2) 对未匹配峰在每个 bucket（类似固定宽度 m/z 区间）里只保留强度最大者（max-pooling）。
3) 目标：最多约 \(2 \times\) 每像素列的峰数量（L139-L145）。

- **L105-L118**：`lowerBound`：在按 m/z 排序数组里找第一个 `mz >= target` 的索引（经典二分）。
- **L120-L175**：`downsampleForRender(peaks, xDomain, innerW)`
  - **L131-L137**：先根据当前可见 X 域裁剪出可见区间 `[start,endIdx)`。
  - **L139-L145**：设定目标 bucket 数：`max(200, innerW*2)`；如果可见峰数不大于目标，直接返回原可见切片，避免不必要的损失。
  - **L147-L173**：遍历可见峰：
    - 若峰是 matched（`p.ion`）→ 直接输出，并且在输出前把当前 bucket 的 tallest flush 掉，保证输出仍按 m/z 单调。
    - 若峰 unmatched → 归入 bucket：bucket 变化时 flush 旧 tallest；同 bucket 内保留强度更高者。
  - **L173-L175**：循环结束后 flush 最后一桶 tallest。

这一段对后续 hover（L724-L737）非常重要：hover 在下采样后的候选上二分查找，成本稳定。

---

### L177-L258：`SpectrumChart` 组件主体：状态、受控/非受控 zoom、排序、全范围

- **L177-L192**：解构 props，并提供默认值。
- **L193-L201**：本组件内部状态/引用
  - `containerRef`：用于 `ResizeObserver` 获取容器宽度。
  - `svgRef`：直接指向 `<svg>`，D3 用它清空并重建结构。
  - `width`：自适应宽度状态。
  - `tooltip`：当前 hover 的峰信息（用于绝对定位的 tooltip div）。
  - `internalZoom`：非受控模式的 zoom 存储。
- **L202-L214**：受控/非受控 zoom 的统一入口
  - `zoom = zoomProp ?? internalZoom`
  - `isControlled = zoomProp !== undefined`
  - `zoomRef`：让事件监听（wheel/brush）在不重绑监听器的情况下读取最新 zoom。
  - `commitZoomRef`：统一“提交 zoom”的动作：若父提供回调则通知父；若非受控则更新内部 state。
- **L216-L227**：`sortedPeaks`
  - 为了让 `lowerBound` 与 D3 `bisector` 正确，必须 m/z 排序。
  - 这里先线性检查是否已排序；若已排序直接复用输入数组（避免复制）。
- **L229-L233**：`fullX`
  - 若 props 提供 `xDomain` 则优先。
  - 否则取 `sortedPeaks` 首尾 m/z。
  - 若无峰，给 `[0,1]` 防止 scale 崩。
- **L235-L238**：把 `marker` 拆成 primitive，避免父组件每次 render 传新对象导致 effect 重建（这是常见的 React 性能坑）。
- **L240-L251**：`ResizeObserver` 监听容器宽度，更新 `width`。
- **L253-L257**：非受控模式下，当数据（`sortedPeaks`）变化时重置 zoom；受控模式不管，因为父要决定什么时候复位。

---

### L259-L857：核心：一次性“骨架构建” + 可复用的 `applyZoom`

这一大段 `useEffect` 的设计目的：
- **只在数据/布局改变时**（peaks、宽高、labels、marker、overlay 等）重建 SVG 结构和事件监听。
- **在用户交互产生 zoom 变化时**，只调用 `applyZoom` 更新 scale、axis、以及峰的 attributes，避免频繁 `selectAll("*").remove()`。

关键点按块解释：

#### 1) L266-L274：初始化与空数据短路

- 清空 SVG（L270）。
- 如果无峰：`applyZoomRef.current = null` 并返回。

#### 2) L276-L346：尺寸、clipPath 与分层组（layers）

- **L276-L278**：margin 与 innerW/innerH。
- **L285-L293**：每个 chart 生成独立 `clipPath id`（随机串），避免同页面多个 chart 冲突；把绘图区裁剪到 innerW×innerH，确保缩放后绘制不会溢出。
- **L295-L346**：创建各种 `<g>`：
  - `gridG`：网格线
  - `xAxisG` / `yAxisG`：轴
  - `peakG`：峰层（整体 clip）
  - `guidesG`：annotation guide 虚线（在峰后面）
  - `linesG`：所有 stick
  - `dotsG`：matched 峰顶端的小实心圆点
  - `envOverlayG`：包络空心圆
  - `envLabelsG`：包络文字标注（pointer-events none，避免遮挡鼠标）
  - `markerG`：垂直 marker 线与文字
  - `labelsG`：自动挑选的峰文字标注（放最上层）
  - `brushG`：X 方向框选层

#### 3) L352-L365：scale 与格式化工具、hover bisector

- 初始化 `xScale`、`yScale`（真正的 domain 会在 applyZoom 中更新）。
- `hoverCandidates`：用于 hover 的候选峰数组（下采样后）。
- `bisectMz`：按 m/z 的 bisector。

#### 4) L366-L682：`applyZoom(z)` —— 每次缩放都调用的“热路径”

这是文件里最重要的函数：它把 zoom 状态映射到 DOM 更新。

- **L367-L374 / L389-L390**：明确强调 **不要对 X/Y scale `.nice()`**。
  - 原因：`.nice()` 会把 domain 扩展到“好看的整数边界”，导致下一次滚轮缩放时读取到的是被“nice”过的 domain，从而出现“缩放像撞墙/跳变”的手感。
- **L375-L377**：X 域：`z.x ?? fullX`，然后构建 `xScale`。
- **L378-L384**：按新的 X 域对峰下采样，并更新 hover 候选。
- **L385-L390**：Y 域：
  - 自动 Y：扫描 `displayed` 找最大强度作为 `autoYMax`。
  - Y 域为 `z.y ?? [0, autoYMax]`。
- **L392-L423**：更新 X/Y 轴：
  - X ticks 数量随宽度变化。
  - Y ticks 5 个；若给了 `yPercentBase` 则用百分比格式，否则用 SI 格式。
  - 同时把 tick text、轴线颜色统一设为主题色变量。
- **L425-L436**：更新横向网格线（用一个 `axisLeft(yScale)` 但 tickFormat 为空），并删除 domain 线。
- **L437-L460**：引导虚线 `annotationGuidesMz`
  - 过滤到当前 X 域可见范围（L439-L441）。
  - 用 data-join 更新/创建/删除 `<line class="guide">`。
- **L462-L487**：峰 stick 的 data-join
  - enter/update 都设置 `x1/x2`、`y1/y2`、stroke 与宽度（matched 更粗）。
  - 因为 `displayed` 已被下采样，所以更新成本受控。
- **L489-L508**：matched 峰顶端圆点（只对 matched 子集做 join）。
- **L510-L553**：包络 overlay（空心圆 + 少量文字）
  - overlay 也会被过滤到当前 X 域（L513-L515）。
  - 圆用 join；文字采用 `envLabelsG.selectAll("*").remove()` 然后 for 循环 append（因为文字数量极少且需要简单的可见性判断）。
- **L555-L578**：marker 线：每次 zoom 都重建 markerG 内容（数量非常少，重建比 join 更简单）。
- **L580-L681**：自动峰标注（离子字母 + charge 上标 + 位置下标）
  - 策略：从 matched 峰里按强度排序（L593），贪心放置 label bbox，避免重叠（L595-L633）。
  - label 的绘制拆成三段 text：主字母、charge 上标、位置下标（L642-L680），用不同字号与相对偏移模拟上/下标效果。

#### 5) L686-L705：brush 框选 X 缩放

- D3 `brushX()` 设 extent 为绘图区大小（L689-L693）。
- 在 `end` 事件中：
  - 无 selection 直接返回。
  - 读出像素 `[a,b]`，马上清除 brush（L697），避免残留遮挡。
  - 太小的 drag（<4px）忽略。
  - 用 `xScale.invert` 转成 m/z 域，提交 `zoom.x`，保留当前 `zoom.y`（L699-L702）。

#### 6) L706-L752：hover tooltip 与双击复位

- tooltip 用 `requestAnimationFrame` 合并 mousemove（L708-L738），避免每个 mousemove 都 setState。
- mousemove：
  - 把鼠标位置转换到 plot 内坐标（减去 margin）。
  - 超出 plot → 清 tooltip。
  - 通过 bisector 在 `hoverCandidates` 找最近峰（L724-L734），并 setTooltip。
- dblclick：
  - 只有在 plot 区域双击才复位（L745-L747），避免误触边框区域。

#### 7) L753-L833：滚轮缩放（X/Y，含合并与轴判定）

滚轮缩放要解决两个问题：  
1) **判定缩放哪个轴**（X 为主；在 Y 轴 gutter 或 Shift 时缩放 Y）。  
2) **把高频 wheel 事件合并**（尤其触摸板）。

- **L770-L780**：计算鼠标在 plot 内的相对位置，判断是否在 Y 轴区域、X 轴区域或 plot 内。只在这些区域响应。
- **L783**：确定 mode：
  - 在 Y 轴 gutter 或（plot 内且 Shift）→ `y`
  - 否则 → `x`
- **L786-L790**：若 mode 变化，清空累积，避免混入。
- **L792-L830**：用 RAF 合并 wheel：
  - factor：`1.35^(dy/100)`，dy>0 表示缩小/放大取决于设备方向，这里按经验选择（见注释）。
  - Y zoom：以 cursor 的 y 对应的数值 `vy` 为锚点，按 factor 拉伸上下边界，并 clamp 到 `>=0`（强度不能为负）。
  - X zoom：以 cursor 的 x 对应的 m/z `vx` 为锚点，按 factor 拉伸左右边界，并 clamp 到 `fullX`。
  - 如果 zoom 后恰好回到 fullX，则把 `zoom.x` 置为 `null`（表示自动域/复位）。
- **L832**：监听 wheel 必须 `passive:false` 才能 `preventDefault()` 阻止页面滚动。

#### 8) L834-L844：首次绘制与清理

- 初始 paint 调用 `applyZoom(zoomRef.current)`（让受控 zoom 立即生效）。
- 清理时移除 wheel/mouse 监听，取消 RAF，清 `applyZoomRef`。

#### 9) L845-L857：依赖项

只要 `sortedPeaks`、尺寸、labels、marker、overlay 等变化，就重建 skeleton。这样做的含义是：
- “数据/布局改变”→ 重建结构与监听；
- “只 zoom 变了”→ 走下面的 hot-path effect。

---

### L859-L866：zoom 热更新 effect（关键优化点）

- **L863-L865**：当 `zoom`（受控或非受控）变化时，仅调用 `applyZoomRef.current?.(zoom)`。
- 注释解释了性能目标：不会 tear-down DOM，不会重绑监听，只更新 axis ticks + 峰 attrs。

---

### L867-L929：React 层 JSX：容器、按钮、tooltip

- **L869-L879**：外层容器 `relative`，便于右上角按钮与 tooltip 绝对定位。
- **L871-L878**：无峰时显示 `emptyHint` 占位。
- **L879-L903**：有峰时渲染 `<svg>`，右上角按钮：
  - reset：调用 `commitZoomRef.current(DEFAULT_ZOOM)`，并在未 zoom 时禁用（`disabled={!zoomed}`）。
  - enlarge：只有 `onOpenFull` 存在才显示。
- **L904-L923**：tooltip：
  - `pointer-events-none` 防止遮挡 hover。
  - left/top 用 `Math.min/Math.max` 做边界约束，避免出屏。
  - 显示 m/z、intensity、charge，以及匹配离子信息（颜色与峰一致）。

---

### 这个文件与其它模块的耦合点（阅读提示）

- **与 `PrsmDetailPage.tsx`**：父组件决定如何构造 `peaks: ChartPeak[]`，以及是否采用受控 zoom（例如 inline chart 与 modal chart 的 zoom 共享/隔离策略）。
- **与 `parse.ts`**：`peaks` 的 matched 信息（ion、position、charge）来自对后端 JSON 的解析与归一化。
- **与 `MatchedPeakSpectrumPanel.tsx`**：该面板会传入 `xDomain`（局部窗口）、`envelopeOverlay`（同位素空心圆）、`yPercentBase`（百分比 Y 轴），让这一个 `SpectrumChart` 同时覆盖“全谱图”和“局部 envelope 视图”两种需求。

