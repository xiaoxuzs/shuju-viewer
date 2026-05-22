## `front/src/features/prsm/FragmentationView.tsx` 逐行解释

> 来源文件：`front/src/features/prsm/FragmentationView.tsx`

> 目标：渲染“碎裂/序列阶梯（sequence ladder）+ 去卷积峰 stick plot + ppm 误差图”的复合视图。它是对 TopMSV 中 `mono mass` MS2 图的移植：上方两行 ladder 显示 N/C 端离子覆盖，中间显示去卷积峰（mono mass 轴），底部显示匹配离子的 ppm error 点。X 轴不做缩放，而是通过“固定密度（px/Da）+ 原生横向滚动”实现平移浏览。

---

### L1-L4：依赖

- **L1**：React hooks：容器宽度观测、密度 slider、派生数据 memo。
- **L2**：D3：这里只使用 `scaleLinear()` 与 `ticks()` 生成刻度与坐标映射（不像 `SpectrumChart` 那样用 D3 DOM 操作；本文件主要用 JSX 直接输出 SVG 元素）。
- **L3-L4**：`cn` 与类型导入。

---

### L6-L40：大段注释：视图结构与建模假设（非常关键）

这段注释明确了组件“为什么这样画”：

- **L13-L20**：顶部 ladder：两行 tick（N 端与 C 端），以及 tick 间的氨基酸字母。
- **L21-L26**：中部 stick plot：每个 `ms_peaks` 去卷积峰画在 `monoisotopic_mass`（不是 m/z），匹配峰着色并可标注 `C₃₉` / `Z•₄₂`。
- **L27-L29**：底部 error plot：每个匹配离子贡献一个 (mass, ppmError) 点，0 线为虚线。
- **L31-L34**：X 轴不缩放，只滚动（固定像素密度渲染）。
- **L35-L39**：理论 ladder mass 由 AA 单同位素质量 + mass shifts 推导，并用“dominant ion type 校准 offset”来对齐观测峰（避免不同离子化学导致 ladder 整体偏移）。

---

### L42-L46：Props

- **L43**：`protein`：来自 `parse.ts` 的 `AnnotatedProtein`（包含 residues、massShifts、form slice 边界等）。
- **L44**：`peaks`：去卷积峰 `MsPeakRow[]`（包含 matched ions）。
- **L45**：`className`：外层样式。

---

### L48-L81：离子分类、氨基酸质量表

- **L48-L49**：N/C 离子集合。
- **L51-L77**：`AA_MASS`：单同位素残基质量（Da），包含：
  - 20 个常见氨基酸
  - `U`（硒代半胱氨酸）与 `O`（吡咯赖氨酸）
  - 对 `X/B/Z/J` 等不确定字母默认返回 0（L52-L53 的意图：宁可缺失也不要注入错误偏移）。
- **L79-L81**：`aaMass(letter)`：查表函数。

---

### L83-L108：中间建模结构

这些 interface 是把上游数据“投影”为本视图需要的字段：

- **`LadderIon`**（L83-L91）：来自 matched ions 的结构，包含：
  - position（离子位置）
  - theoreticalMass（上游提供的理论质量）
  - monoMass（峰观测质量）
  - intensity/charge
  - ionType
  - ppmError
- **`DeconvPeak`**（L93-L101）：中间 stick plot 用的峰结构（只保留一个 ion 的摘要字段）。
- **`LadderTick`**（L103-L108）：ladder 每个 position 的 tick：
  - `mass` 是“校准后的理论质量”，用于放置 tick 在 x 轴上的位置。
  - `matchedIon` 若存在则表示该位置有匹配。

---

### L110-L124：显示与配色函数

- **L110-L113**：`displayIonLetter`：`Z_DOT` → `Z•`。
- **L115-L117**：`colorForSide`：N=ion-n、C=ion-c。
- **L119-L124**：`colorForPeak`：
  - 未匹配/无 ionType → 灰色
  - N/C/shift → 对应主题色

---

### L126-L216：组件起始：容器宽度、序列与 form slice、残基质量数组、离子列表

- **L127-L140**：与 `SpectrumChart` 类似，用 `ResizeObserver` 获取 viewport 宽度（用于自动密度）。
- **L142-L147**：把 `protein.residues` 拼成 `seq` 字符串。后续 ladder 需要按索引取字母。
- **L149-L152**：form slice：
  - `formFirst`/`formLast`：proteoform 在整条 protein residues 中的范围
  - `formLen`：长度（>=0）
- **L153-L165**：`residueMasses`：
  - 初始为每个 residue 的 `aaMass(acid)`。
  - 遍历 `protein.massShifts`：如果 `shift` 存在，则把 shift 加到 `leftPosition` 对应残基（L160-L162）。
  - 注意：这里把 mass shift 视为“加在某个 residue 上”的简化模型（与 TopPIC 的 mass shift annotation 结构相匹配）。
- **L167-L198**：从 `peaks` 里提取 matched ladder ions：
  - 遍历每个去卷积峰 `p`（monoMass/intensity 必须有效）。
  - 遍历 `p.matchedIons`：
    - 要求 `ion.theoreticalMass` 存在
    - 组装 `LadderIon`：使用 `ion.ionDisplayPosition` 做 position（这通常已经是 TopMSV 语义下的 1..L）
  - 按 ionType 分类到 N/C 数组（L184-L186）。
  - `dedup`：对同一 position 可能有多个匹配（或多个峰）时，保留强度最高的那一个（L188-L196），并按 position 排序。

---

### L200-L215：构建 prefix/suffix 累积质量 `cumN` / `cumC`

这一步是 ladder 的“理论基准”，用于把 position → 质量。

- **L208-L213**：
  - `cumN[p]`：form 内前 p 个 residue 的质量和（prefix）。
  - `cumC[p]`：form 内后 p 个 residue 的质量和（suffix）。
- **L211-L212**：索引映射：
  - prefix 从 `formFirst` 向右
  - suffix 从 `formLast` 向左

这样 position p（1..formLen-1）就能 O(1) 查到对应的 prefix/suffix base mass。

---

### L217-L264：offset 校准与 tick 列表（ladder rows）

不同离子类型理论质量与“纯 residue 累积质量”之间存在一个近似常数 offset（例如加上某些端基、失去某些基团）。本实现不硬编码化学常数，而是用观测到的 matched ions 来反推。

- **L221-L228**：分别对 N 与 C 做 `calibrateOffset(nIons,cumN)` / `calibrateOffset(cIons,cumC)`。
- **L230-L247**：`nTicks`：
  - 若没有 offset 或 formLen<=1 → []（没有 anchor，不画）。
  - `matchedMap`：position → LadderIon（强度最高的那个）。
  - 对每个 position p=1..formLen-1：
    - 有 matchedIon：tick.mass = `ion.theoreticalMass`（更精确）
    - 无 matchedIon：tick.mass = `cumN[p] + nOffset`（用校准常数补齐）
- **L249-L264**：`cTicks` 同理，但 base mass 用 `cumC[p] + cOffset`。

---

### L266-L285：去卷积峰列表 `deconv`（中间 stick plot 数据）

- **L267-L284**：
  - 遍历 peaks：
    - 要求 `monoMass`/`intensity` 有效且强度>0
    - `ion = p.matchedIons[0]`：只取第一个 ion 作为“代表”（因为 stick plot 对每个峰只标一个离子 label；更完整的信息在表格里）
    - 记录 matched、ionType、position、charge、ppmError（ppmError 同样取第一个 ion）
  - 最后按 mass 排序（L282-L283），方便后续 x-range 与绘制顺序。

---

### L286-L337：X 范围、强度范围、ppm 范围、密度（px/Da）

#### 1) fullX（L290-L305）

- 覆盖：
  - 观测峰 `deconv.mass`
  - ladder ticks（nTicks/cTicks）
- 找 lo/hi 后加 pad：
  - pad = `max(20, span*0.02)`
  - 目的：两端留白，视觉更舒服。

#### 2) intensityMax（L307-L311）

- 去卷积峰强度最大值，至少为 1（避免除 0）。

#### 3) ppmMax（L313-L324）

- 扫描 `deconv.ppmError` 的绝对值最大值。
- 若没有误差数据，给 0.2（避免 error plot 退化）。
- 否则把范围扩大 1.25 并按数量级向上取整（L321-L323），让 y 轴刻度更“整齐”。

#### 4) density 与 effectiveDensity（L326-L337）

- `density` state 允许用户手动调整（range slider）。
- 若 `density == null`：
  - 目标图宽 \( \approx 3 \times viewportW \)
  - `d = target/span`
  - clamp 在 [0.3, 6]

这决定了“每 Da 对应多少像素”，从而决定 SVG 总宽度与滚动体验。

---

### L339-L403：布局常量与刻度

- **L339**：`showLines` 控制 ladder→peak 的虚线是否显示。
- **L341-L346**：各区域高度：
  - ladderH、mainH、errorH 等。
- **L347-L353**：计算 `innerW`（至少 600）与 `totalW/totalH`。
- **L364-L375**：构建三个 scale：
  - `xScale`：fullX → [margin.left, margin.left+innerW]
  - `yScale`：强度 → main 区域 y
  - `errYScale`：ppm → error 区域 y
- **L377-L388**：刻度：
  - xTicks：随 innerW 调整
  - yTicks：固定用 0/25/50/75/100% 的分位（乘 intensityMax）
  - errTicks：`[-ppmMax, -ppmMax/2, 0, ppmMax/2, ppmMax]`
- **L390-L402**：ladder 两行的位置与 letter 显示阈值：
  - 两行 tick 的 y：`nIonRowY`/`cIonRowY`
  - letter baseline y：`nLetterY`/`cLetterY`
  - `minLetterSpacing=5`：tick 间距过小时隐藏字母，避免糊成一团。

---

### L404-L776：渲染（控制条 + 横向滚动 SVG）

#### 1) 顶部控制条（L405-L458）

- 显示 N/C matched 数、未匹配峰数。
- density slider：
  - value=effectiveDensity
  - 用户一旦拖动就 setDensity(number) 固定为手动密度
  - “auto” 按钮把 density 设回 null，回到自适应
- showLines checkbox 控制虚线。

#### 2) 容器与空态（L460-L468）

- 容器 `overflow-x-auto`，让 SVG 横向滚动。
- `deconv.length===0` 显示 “no deconvoluted peaks”。

#### 3) 主 SVG（L469-L771）

整体按顺序绘制多个层：

- **L475-L519**：ladder→peak 虚线（如果 showLines）
  - 对每个 matched tick，拿到 matchedIon.intensity，线从 ladder row 到 peak 顶部附近
  - 颜色统一为灰蓝，虚线 `strokeDasharray="4,4"`
- **L521-L543**：两行 ladder：`<LadderRow side="n" .../>` 与 `<LadderRow side="c" .../>`
- **L545-L600**：中间 stick plot 的 Y 网格、Y 轴、Y tick label（显示百分比）
- **L601-L653**：峰 sticks：
  - 先画 unmatched（灰色，opacity 0.65）
  - 再画 matched（更粗、彩色），并在顶部画离子 letter+position 的小文本（用 `<tspan>` 模拟下标，L646-L648）
- **L655-L694**：X 轴（Mass (Da)），刻度来自 xTicks
- **L696-L770**：error plot：
  - 外框 rect
  - 0 虚线
  - y tick labels（格式根据 ppmMax 大小选择小数位）
  - dots：只对 matched 且有 ppmError 的峰画点，并在 `<title>` 中提供 hover 提示（mass/err/ion）

---

### L778-L898：helpers（校准与 ladder row 渲染）

#### 1) `calibrateOffset`（L789-L816）

- 若没有 ions → null（无锚点就不画 ladder）。
- 按 `ionType` 分组，取数量最多的组作为 dominant（L794-L805），避免少量异类离子污染 offset。
- 对 dominant 组：
  - base = `cum[ion.position]`
  - offset sample = `ion.theoreticalMass - base`
  - 求平均作为 offset（L806-L815）。

#### 2) `LadderRow`（L836-L897）

渲染一个 ladder row：

- **L852-L866**：对每个 tick 画一个短竖线：
  - matched 用 side color（N/C）
  - unmatched 用 mutedColor
  - matched stroke 更粗一点
- **L867-L894**：在相邻 tick 之间画氨基酸字母：
  - gap < minLetterSpacing 则隐藏
  - 字母选择规则（非常关键）：
    - N 端：从 position p → p+1 增加的 residue 在 `seq[formFirst + p]`（L876-L879）
    - C 端：对应 `seq[formLast - p]`（L879）
  - 这样字母就落在两个 tick 的中点，表达“从这个断点到下一个断点之间多了哪个残基”。

---

### 与其它模块的耦合点

- **与 `parse.ts`**：依赖 `AnnotatedProtein` 提供 residues、massShifts、form slice（first/last residue position），以及 `MsPeakRow` 的 matched ions 信息。
- **与 `MatchedPeaksTable`/`SpectrumChart`**：配色与离子显示 token（`Z_DOT`→`Z•`、N/C 色）要一致，否则用户认知会断裂。
- **与后端**：`theoreticalMass` 与 `ionDisplayPosition` 的定义来自 TopPIC/TopFD 导入的 JSON 结构；这决定 ladder 校准是否稳定。

