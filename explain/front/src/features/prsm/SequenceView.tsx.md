## `front/src/features/prsm/SequenceView.tsx` 逐行解释

> 目标：渲染 PrSM 的序列视图（proteoform 在 protein 上的片段）、断点（cleavage / break points）括号、质量偏移（mass shift）背景与注释，尽量像 TopMSV 的 `draw_prsm.ts` 一样“像素级忠实”。该组件用一个 SVG 一次性绘制全部几何元素，而不是用 HTML 分行拼接。

---

### L1-L4：依赖

- **L1-L2**：本文件主要用 React/JSX 输出 SVG，逻辑计算用 `useMemo`；`ReactElement` 用于生成 rect 数组。
- **L3**：`cn` 拼接 class。
- **L4**：类型导入：`AnnotatedProtein`（包含 residues、cleavages、massShifts、form slice 边界）、`Cleavage`（断点结构）、`Residue`。

---

### L6-L10：Props

- **L7**：`protein`：完整结构化 protein/proteoform 注释。
- **L8**：`className`：外层样式。
- **L9**：`onCleavageClick`：可选回调：点击断点括号时触发（用于未来扩展：例如点开断点详情、联动 ladder/峰等）。

---

### L12-L21：注释：该视图为何用 SVG

- **L15-L18**：强调用“单 SVG”保证几何布局与 TopMSV 一致：字母间距、block gap、行号、断点括号、mass-shift 背景矩形与文字标注。
- **L20**：布局常量镜像 TopMSV `PrsmPara`。

---

### L22-L47：布局常量（TopMSV 风格的“字符网格”）

这些常量定义了“一个 residue 字符占多少像素、每行多少字符、每 10 个字符一个 gap”。

- **L22-L23**：`ROW_LENGTH=30`：每行 30 个 residue。
- **L23**：`BLOCK_LENGTH=10`：每 10 个 residue 加一个额外 gap。
- **L24-L26**：字母宽、gap 宽、行高。
- **L27-L31**：上/下/左/右 margin 与额外 padding。
- **L32-L34**：数字区域宽度与字体宽高估计（用于注释 overlap 计算与右侧行号定位）。
- **L35-L38**：字母字号、middle margin、跳过行高度、注释 y 偏移候选（两档）。
- **L39**：断点括号颜色（蓝色）。
- **L40-L45**：mass shift 背景颜色按类型区分（variable/unexpected 等）。
- **L46**：`SHOW_NUM=true`：显示行号。

---

### L48-L60：位置 → SVG 坐标函数

#### `getX(pos,startPos)`（L48-L55）

- `num = pos - startPos`：把 protein 绝对位置换成“展示窗口内相对位置”。
- `posInRow = num % ROW_LENGTH`：在行内的列号。
- `gapNum = floor(posInRow / BLOCK_LENGTH)`：经历了多少个 block gap。
- 基础 x：`posInRow*LETTER_WIDTH + gapNum*GAP_WIDTH + LEFT_MARGIN`。
- 若 SHOW_NUM：再加 NUMERICAL_WIDTH（左侧行号留白）。

#### `getY(pos,startPos)`（L57-L60）

- `row = floor((pos-startPos)/ROW_LENGTH)`：第几行。
- y：`row*ROW_HEIGHT + TOP_MARGIN`。

这些函数是整个 SVG 布局的“坐标系统核心”。

---

### L62-L67：`Annotation` 结构

- 用于 mass shift 文本注释的中间模型：范围 `[leftPos,rightPos)`、文本、类型（决定背景色）。

---

### L69-L105：组件开始：展示窗口的“扩展规则”与 skip 提示

#### 1) L70-L72：从 protein 取字段与 totalLen

- `residues` 全序列长度可能很长；但 form slice 只覆盖一段。

#### 2) L73-L102：计算 displayFirstPos/displayLastPos/rowNum/skip 文案

这段用 `useMemo` 计算“实际要绘制的 residue 范围”，并在 form slice 两端留出少量上下文：

- **L82-L83**：`dFirst`：把 `firstResiduePosition-5` 向下取整到行边界（ROW_LENGTH 的倍数），并 clamp 到 >=0。
  - 目的：在 form 起点前多显示几位上下文，并保持从整行开始，视觉上更整齐。
- **L84-L85**：`dLast`：把 `lastResiduePosition+6` 向上取整到行边界（最后一行的末尾位置），并 clamp 到 <= totalLen-1。
- **L86**：`rn`：行数，至少 1。
- **L87-L88**：`ss/se`：是否跳过了 N/C 端（display window 没覆盖完整 protein）。
- **L95-L100**：skip 文案：
  - N 端：`... ${dFirst} amino acid residues are skipped ...`
  - C 端：`... ${totalLen-1-dLast} ...`

#### 3) L104：`yShift`

- 如果 showStartSkipped 为真，则把真正的序列区域整体下移一个 `MIDDLE_MARGIN`，给 skip 文本留空间。

---

### L106-L137：fixed PTM 与 mass shift annotations 预处理

#### 1) fixed PTM positions（L107-L113）

- TopPIC 的 fixed 修饰不画背景块，只把 residue 文字染红（L139-L143）。
- 因此这里用 Set 收集所有 `shiftType==="fixed"` 的 leftPosition。

#### 2) annotations（L115-L137）

- 从 `massShifts` 过滤掉 fixed（L116-L117）。
- 转成 `Annotation` 列表（L118-L123），按 leftPos 排序（L124）。
- **合并规则（L126-L135）**：如果连续两个 annotation 的范围完全相同（left/right 一致），则把文本用 `;` 拼接在一起，减少重复标注。

---

### L139-L143：`residueColor`

- 在 form slice 外的 residue → grey（上下文部分）。
- 在 form slice 内且 fixed PTM → red。
- 否则 → black。

这实现了“form 区域强调 + fixed 修饰可视化”的基本规则。

---

### L145-L162：SVG 尺寸与右侧行号位置

#### 1) 宽度（L146-L149）

- 计算一行字符的总宽：`LETTER_WIDTH*(ROW_LENGTH-1) + blockNum*GAP_WIDTH + margins + padding`。
- 若 SHOW_NUM：左右各加 NUMERICAL_WIDTH（左侧/右侧行号区）。

#### 2) 高度（L150-L153）

- 基本高度：`ROW_HEIGHT*(rowNum-1) + LETTER_SIZE + margins`。
- 如果首/尾有 skip 文本：各加一个 `SKIP_LINE_HEIGHT`。

#### 3) `rightNumX`（L155-L161）

- 复刻 TopMSV 的右侧行号定位：从左 margin + 左行号区 + 行内宽 + gap 总宽 + 右行号区 + font 宽微调。

---

### L163-L186：mass shift 注释文本的 Y 偏移（避免重叠）

- 目标：如果两个注释在同一行且水平距离不足以容纳前一个注释的长度，就交替使用 `MOD_ANNO_Y_SHIFTS` 两个高度（-15 / -30）。
- **L170-L180**：计算当前注释的 (x1,y1)，与前一个注释的 (x2,y2) 比较：
  - 只在同一行（y1===y2）时考虑 overlap
  - `annoLen = prev.annoText.length*(FONT_WIDTH-2)` 估算文本像素长度
  - 若 `x1 - x2 < annoLen` 则视为重叠
- **L181-L184**：若 overlap 就 `(prevIdx+1)%2` 在两档偏移间切换，否则回到 0。

这是一种简化但有效的“注释避让”策略。

---

### L188-L368：SVG 渲染（按层绘制）

#### 1) 外层容器（L189）

- `overflow-x-auto`：当 protein 片段较长时允许横向滚动（虽然这里主要是纵向分行，但宽度固定较大）。

#### 2) SVG 画布（L190-L197）

- 指定固定背景白色（TopMSV 风格）。
- `fontFamily` 使用等宽字体，保证字符对齐。

#### 3) start skipped 文本（L198-L207）

- 如果 showStartSkipped，在 TOP_MARGIN 位置绘制提示行。

#### 4) mass-shift 背景矩形（L209-L239）

- **L209**：先画背景，确保字母在上层可读。
- **L211-L238**：对每个 annotation，可能跨越多行：
  - 计算 startRow/endRow（L213-L214）
  - 对每一行 j：
    - 得到该行覆盖范围 rowLeft/rowRight（L217-L220）
    - 过滤掉完全不在 display window 内的部分（L221）
    - 计算 x1/x2/y1 并画 `<rect>`（L226-L235）
  - fill 颜色由 `MASS_SHIFT_COLORS[type]` 控制，透明度 0.4

这是实现“连续范围背景高亮”的关键：跨行时拆成多个 rect。

#### 5) mass-shift 文本注释（L241-L252）

- 在注释的 leftPos 上方绘制文本，y 位置用前面算好的 `MOD_ANNO_Y_SHIFTS`（L245）。

#### 6) 行号（L254-L275）

- 对每行 i：
  - leftPos = displayFirstPos + i*ROW_LENGTH
  - rightPos = min(leftPos+ROW_LENGTH-1, displayLastPos)
  - 左侧行号与右侧行号各绘制一次（L266-L271）

#### 7) 氨基酸字母（L277-L289）

- 遍历所有 residues（这是 O(N)），但只绘制 display window 内的那些（L280）。
- 每个 residue 用 `residueColor` 着色（L284）。

#### 8) form slice 的边界符号（L291-L307）

- 如果 form 的 firstResiduePosition 不等于 displayFirstPos 且 >0，则画 start boundary（L292-L299）。
- 如果 lastResiduePosition 不等于 displayLastPos，则画 end boundary（L300-L307）。
- 这两个符号由 `BoundarySymbol` 组件生成（L371-L407）。

#### 9) cleavage break points（L309-L354）

这是 TopMSV 里“括号断点”的移植：

- **L311-L313**：只对存在 N/C 离子的断点绘制（否则没意义）。
- **L313-L316**：`anchorPos = bp.position - 1`：
  - 断点发生在 residue 之间；这里用左侧 residue 的位置作为锚点。
- **L315-L316**：x/y：以该 residue 的坐标为基准，x 再加半个字母宽让括号居中（L315）。
- **L318-L325**：根据断点是否存在 N ion / C ion 选择 polyline 点集合：
  - 只有 N：画左括号样式
  - 只有 C：画右括号样式
  - 两者都有：画“连起来”的样式
- **L329-L336**：绘制 `<polyline>`：蓝色、圆角端点/连接。
- **L337-L351**：绘制一个透明 `<rect>` 作为点击命中区域：
  - cursor 根据 `onCleavageClick` 是否存在切换 pointer/default
  - onClick 时回调 `onCleavageClick(bp)`
  - `<title>` 提供 hover 文本（位置 + N/C 标记）

这一步是“可交互扩展点”：未来可以点断点联动其它视图。

#### 10) end skipped 文本（L356-L365）

- 如果 showEndSkipped，在最后一行下面绘制提示。

---

### L371-L407：`BoundarySymbol` 组件（form slice 边界红色括号）

- 接收 kind（start/end）、pos、startPos、yShift。
- **start**：
  - x 在 baseX 左侧半个字母宽
  - polyline 形成一个左括号形状（L386）
- **end**：
  - x 在 baseX 右侧半个字母宽
  - polyline 形成右括号形状（L398）
- stroke 红色、稍微粗一点（1.3）。

---

### 与其它模块的耦合点

- **与 `parse.ts`**：依赖 `AnnotatedProtein` 的：
  - `residues`（每个 residue 的 acid + position）
  - `firstResiduePosition/lastResiduePosition`（form slice）
  - `massShifts`（范围/类型/注释文本）
  - `cleavages`（断点、是否存在 N/C ion）
- **与 `FragmentationView.tsx` / `SpectrumChart.tsx`**：同样要遵守 `Z_DOT` 显示、离子分类与颜色的全局约定（虽然本文件本身不画离子颜色，但断点与背景/固定 PTM 的语义要一致）。

