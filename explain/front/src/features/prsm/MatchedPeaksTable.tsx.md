## `front/src/features/prsm/MatchedPeaksTable.tsx` 逐行解释

> 来源文件：`front/src/features/prsm/MatchedPeaksTable.tsx`

> 目标：把 `ms_peaks`（去卷积峰列表）渲染成可筛选的表格，并在“每个峰可能对应多个 matched ions”的情况下，提供“按离子展开为多行”的视图。表格行可点击以打开 matched-peak detail 面板，同时能高亮当前选中的 detail 项。

---

### L1-L4：文件级注释（中文）

- **L1-L4**：说明这个表格的用途、行为与配色规则：
  - 峰可展开为“每个匹配离子一行”
  - 也能把未匹配峰保留为单行
  - 离子类型着色与谱图一致（N 端 / C 端），由 CSS 变量控制

---

### L5-L10：依赖

- **L5**：`useMemo` 用来把 `peaks` 计算成渲染行列表，避免每次 render 都做 `flatMap`；`useState` 保存 filter。
- **L6-L7**：表格 UI 组件与徽章 Badge（项目自有 UI 组件封装）。
- **L8**：`cn` 拼 class。
- **L9**：`formatNumber` 统一数值格式（小数位/空值展示）。
- **L10**：
  - `matchedPeakDetailKey`：把（peak, ion）组合生成稳定 key，用于“当前选中行高亮”。
  - `MatchedIon` 与 `MsPeakRow`：来自 `parse.ts` 的结构化数据类型。

---

### L12-L19：Props

- **L13**：`peaks`：去卷积峰数组（每个峰包含 `matchedIons` 列表）。
- **L14**：`className`：外层样式扩展。
- **L15-L16**：`onMatchedPeakClick`：只有“匹配行”可点击；点击后把 `peak` 与具体 `ion` 传给父组件（通常用于打开/刷新 detail 面板）。
- **L17-L18**：`selectedDetailKey`：父组件告诉表格当前选中的（peak, ion），表格负责把对应行的 Peak cell 高亮。

---

### L21-L25：行模型与离子分类集合

- **L21**：`PeakIonRow`：表格真正渲染的行模型。`ion` 允许为 `null` 表示“未匹配峰占位行”。
- **L23-L24**：N/C 离子集合（与 `SpectrumChart` 同一分类），决定徽章颜色。

---

### L26-L42：组件状态与 `rows` 派生（核心数据变换）

- **L32**：`filter` 初始为 `"matched"`：默认只看匹配项（更常用）。
- **L34-L41**：`rows`：
  - **L35-L39**：对每个 `MsPeakRow` 做 `flatMap`：
    - 如果 `matchedIons.length > 0`：把每个 ion 展开成一行 `{peak, ion}`。
    - 否则：保留一个 `{peak, ion:null}` 行（这样“all peaks”模式能显示未匹配峰）。
  - **L40**：若 filter 是 `"matched"`，则过滤掉 `ion:null` 行；否则保留全部。

这一步把“峰→多离子”的结构转成“表格行”的结构，是表格能直接 map 渲染的前提。

---

### L43-L145：渲染 UI（筛选按钮 + 可滚动表格）

#### 1) L45-L53：filter 切换器

- **L46**：提示文本 “Show:”。
- **L47-L49**：Matched toggle：
  - active 判断 `filter === "matched"`。
  - 同时显示 matched ion 总数：`reduce((n,p) => n + p.matchedIons.length, 0)`（注意：统计的是离子数，不是峰数）。
- **L50-L52**：All peaks toggle：
  - active 判断 `filter === "all"`。
  - 显示峰数量 `peaks.length`。

#### 2) L55-L143：表格主体

- **L55**：限制最大高度并 `overflow-auto`，大数据量也不撑爆页面。
- **L56-L68**：表头列：
  - Peak（峰序号）
  - m/z、Intensity、Charge
  - Ion、Position、Mass err、ppm

#### 3) L70-L133：每行渲染与交互/高亮规则

对每个 `rows` 元素 `r`：

- **L71-L72**：根据 `r.ion.ionType` 判断是 N 还是 C 离子，用于徽章配色 class。
- **L73**：`clickable`：只有同时满足 `r.ion` 存在且父给了 `onMatchedPeakClick`，该行 Peak cell 才可点击。
- **L74**：`active`：当 clickable 且 `selectedDetailKey` 等于 `matchedPeakDetailKey(r.peak,r.ion)` 时高亮。
- **L76**：行 key：`${r.peak.peakId}-${idx}`。注意这里用 idx 是因为同一 peak 可能展开多行，必须区分。
- **L77-L98**：Peak 列（可点击的按钮或不可点击的 span）：
  - **L79-L90**：按钮样式：主色 + hover underline；active 时加背景并加粗（L88-L89）。
  - **L91-L96**：显示 peak 编号：如果 `peakId` 有限，显示 `peakId + 1`（把 0-based 改成人类常用 1-based）；否则显示 `—`。
  - 不可点击时用 muted 文本展示（L94-L97）。
- **L99-L105**：m/z、intensity、charge：
  - m/z 用 `formatNumber(...,4)`
  - intensity 用 `formatNumber(...,1)` 并显示为 muted（强调它不是主键）
- **L106-L120**：Ion 列：
  - 有 ion 时显示 Badge：
    - 文本把 `_DOT` 替换为 `·`（与图一致）
    - class 用 N/C 分类设定背景与前景色（L110-L114）
  - 无 ion 时显示 `—`
- **L122-L130**：position/mass error/ppm 数值列，统一用 `formatNumber` 并在空值时输出 null→占位。

#### 4) L134-L140：空表占位

- 当 `rows.length === 0`（例如 filter=matched 且没有任何 matched ions）显示 “no peaks to show”。

---

### L148-L170：`Toggle` 子组件

- **L148-L156**：定义 Toggle 的 props（active/onClick/children）。
- **L158-L168**：渲染为 `<button>`，根据 active 切换样式：
  - active：主色边框 + 主色淡背景
  - inactive：普通边框 + muted，hover 时变前景色

---

### 与其它模块的耦合点

- **与 `parse.ts`**：`MsPeakRow.matchedIons` 的结构决定了“展开为多行”的逻辑；`matchedPeakDetailKey` 定义了“哪一行被视为同一个 detail selection”。
- **与 `PrsmDetailPage.tsx`**：父组件负责维护 `selection`（peak+ion）与 `selectedDetailKey`，并把点击事件转成打开 `MatchedPeakSpectrumPanel` 的行为。
- **与 `SpectrumChart.tsx`**：表格里 N/C 配色集合必须与谱图一致，才能让用户把表格行与谱图上的颜色建立直觉映射。

