## `front/src/features/prsm/MatchedPeakSpectrumPanel.tsx` 逐行解释

> 来源文件：`front/src/features/prsm/MatchedPeakSpectrumPanel.tsx`

> 目标：当用户在 `MatchedPeaksTable` 点选某个“匹配离子行”时，在页面下方展开一个“局部谱图”面板：以该去卷积峰的 isotope envelope（若能在 raw spectrum 中找到）为中心，展示局部 m/z window；对 envelope 中每个同位素峰画空心圆，并在 apex 峰标注离子（如 `Z• 19`）；Y 轴可用百分比（相对局部最大值）显示；同时提供一个 “masses” 表格 tab 复刻 TopMSV 的局部峰列表。

---

### L1-L7：文件级注释说明

- **L1-L7**：概述该组件复刻 TopMSV 的关键 UI/数据规则：
  - X window = envelope m/z 跨度
  - `env_peaks`（同位素峰）画空心圆
  - tallest 峰上方显示离子标注
  - Y 轴使用局部最大值百分比

---

### L8-L26：依赖

- **L8**：`useMemo` 计算 envelope/window/overlay/表格行等派生数据；`useState` 保存 tab、showGuides、zoom。
- **L9**：关闭按钮图标。
- **L11**：Button UI。
- **L12**：`formatNumber`。
- **L13-L19**：从 `parse.ts` 导入：
  - `findMatchedEnvelope`：核心：把“去卷积峰”与 raw spectrum 的 envelope 对齐（优先 id，其次 monoMass+charge）。
  - 类型：`MatchedIon`、`MsPeakRow`、`RawEnvelope`、`RawSpectrum`。
- **L20-L26**：从 `SpectrumChart` 导入：
  - `SpectrumChart` 复用主谱图组件，但以局部 window/overlay/percent-y 的方式使用。
  - `DEFAULT_ZOOM`、`Zoom`：这个面板自己管理受控 zoom（在面板不卸载时保持状态）。

---

### L28-L34：Props

- **L29**：`selection`：当前选择（peak+ion）；为空表示没有选中，面板应隐藏（L169）。
- **L30**：`ms2ChartPeaks`：用于渲染的 MS2 峰（已经包含 matched ion 着色等）。
- **L31**：`ms2RawSpectrum`：raw spectrum（包含 envelopes / 原始 peak arrays），用于定位 envelope。
- **L32**：`ms2ScanLabel`：用于 UI 文本（例如 “MS2 scan 1234”）。
- **L33**：`onClose`：关闭面板（父组件清 selection）。

---

### L36-L48：离子类型→颜色与显示 letter

- **L36-L38**：N/C ion 集合。
- **L39-L43**：`ionColorFor`：返回与全局一致的 CSS 色值（N/C/shift）。
- **L45-L48**：`ionLetter`：把 `Z_DOT` 显示为 `Z•`。

---

### L50-L69：局部 window 的计算策略

该面板必须在“找到 envelope”与“找不到 envelope”两种情况下都能工作。

- **L50-L54**：`fallbackWindow(center)`：
  - 用 peak centroid 作为中心，窗口半宽为 `max(3, center*0.003)`（大约 0.3% 的相对窗口或至少 3 m/z）。
  - 目的：即便 envelope 缺失，也能给用户一个可用的局部视图。
- **L56-L69**：`envelopeWindow(env)`：
  - 扫描 `env.envPeaks` 找最小/最大 m/z。
  - span 至少 0.5，margin = `max(0.3, span*0.3)`，给窗口留出边界空白。
  - 返回 `[lo-margin, hi+margin]`。

---

### L71-L168：组件状态与派生数据（面板逻辑核心）

- **L78-L80**：内部状态：
  - `tab`：`scan`（谱图）或 `masses`（表格）。
  - `showGuides`：是否显示竖向引导线。
  - `zoom`：受控 zoom（传给 `SpectrumChart`），让用户滚轮缩放只影响此局部窗口视图。

#### 1) L82-L85：定位 envelope

- `findMatchedEnvelope(ms2RawSpectrum, selection?.peak)`：
  - selection 空时返回 null。
  - 这一步把“去卷积峰”与 raw spectrum 的 `envelopes` 对齐，是 overlay 与精确 window 的基础。

#### 2) L87-L96：计算 `xDomain`

- 优先使用 `envelopeWindow(envelope)`。
- 否则若有 `centerMz`（peak.monoMz）就用 fallbackWindow。
- 最终可能为 null（selection 缺失或 center 无效）。

#### 3) L98-L112：生成 `overlayPoints`（空心圆 + apex label）

- 没有 envelope 或 selection → `[]`。
- `color` 用离子类型映射。
- `labelText` 形如 `Z• 19`（letter + 空格 + position）。
- 找 envelope 中强度最大峰索引 `maxIdx`（L102-L105）。
- 对每个 envPeak 输出 `{mz,intensity,color,label?}`，只在 apex 峰上带 label（L106-L111）。

#### 4) L114-L132：计算 `annotationGuidesMz`

这一组 m/z 虚线的优先级是：

- 如果 `showGuides` 关闭 → 空数组（L115）。
- 如果有 envelope 且 `envPeaks` 非空 → 直接用每个 envPeak 的 m/z（L116-L118）。  
  这是最“忠实 TopMSV”的模式：强调 envelope 的每个同位素位置。
- 否则（没有 envelope）：
  - 必须有 selection 与 xDomain（L119）。
  - 从 `ms2ChartPeaks` 里挑选“有 ion 的峰”，落在 xDomain 内。
  - 用 `Math.round(mz*1e6)/1e6` 做去重键（L126），避免非常接近的浮点重复线。

#### 5) L134-L148：计算 `yPercentBase`

为 `SpectrumChart` 提供 `yPercentBase`：

- 如果没有 `xDomain` → null（无法定义局部最大值）。
- 扫描 `ms2ChartPeaks` 在 window 内的强度最大值。
- 如果有 envelope，再扫描 `envPeaks` 最大值，确保 overlay 强度也被计入。
- 最终返回 max（>0）或 null。

这样 `SpectrumChart` 的 Y 轴可以显示为 “占局部最大值的百分比”。

#### 6) L150-L167：masses 表格的数据 `massesInView`

- 若有 envelope：用 envelope 的 `envPeaks`，按 m/z 排序，并标记 apex（强度最大）行。
- 否则：用 `ms2ChartPeaks` 在 xDomain 内的峰，按 m/z 排序。
- 输出 `MassRow`：`{mz,intensity,isApex}`，供 “masses” tab 渲染。

---

### L169：隐藏条件

- **L169**：如果 `!selection || !xDomain`，直接返回 null（不渲染面板）。
  - selection 为 null：用户没选中任何 matched ion。
  - xDomain 为 null：没有有效窗口（例如 peak.monoMz 非法且无 envelope）。

---

### L171-L323：渲染 UI（标题、概要、tab、谱图/表格）

#### 1) L174-L189：面板头部

- **L175-L189**：标题“Peak detail · local m/z” + 一行 monospace 概要（peak id、m/z、mono mass、ion type、position）。
- 右侧 Close 按钮调用 `onClose`。

#### 2) L191-L216：指标网格（dl）

展示 peak/ion 的关键字段：
- charge、intensity、theoretical mass、mass err、ppm、isotopes 数（envelope.envPeaks.length）。

#### 3) L218-L252：tab 与 showGuides 开关

- 两个按钮切换 `tab`：
  - `scan`：谱图
  - `masses`：局部峰表格
- 只有在 `tab === "scan"` 时显示 “Show annotation lines” checkbox（因为 masses 表格不需要 guide lines）。

#### 4) L254-L272：scan tab：复用 `SpectrumChart`

- 无 peaks → 文本提示 “No MS2 spectrum loaded.”
- 有 peaks → 渲染 `SpectrumChart`，关键 props：
  - `xDomain={xDomain}`：强制局部窗口（即使用户 reset zoom，也回到该窗口而不是全谱）。
  - `envelopeOverlay={overlayPoints}`：空心圆覆盖层 + apex label。
  - `yPercentBase={yPercentBase}`：Y 轴百分比。
  - `annotationGuidesMz={annotationGuidesMz}`：竖向虚线。
  - `zoom={zoom} onZoomChange={setZoom}`：受控 zoom 由该面板维护。
  - `emptyHint="no peaks in window"`：窗口里没有峰时提示。

#### 5) L273-L320：masses tab：表格视图

- 一个固定高度的可滚动表格。
- 每行展示：
  - m/z（4 位）
  - intensity（2 位）
  - `% base`：若 `yPercentBase` 存在则显示百分比，否则 `—`
  - Note：apex 行显示离子 `letter position`（L311-L312）
- apex 行用主色淡背景高亮（L297-L303），对应 TopMSV“最强同位素峰”的视觉重点。

---

### 与其它模块的耦合点

- **与 `parse.ts`**：`findMatchedEnvelope` 的匹配规则决定了 envelope 是否能找到；这直接影响局部 window、overlay、guides 的行为。
- **与 `SpectrumChart.tsx`**：该面板把 `SpectrumChart` 当作“底层渲染引擎”，通过 `xDomain`/overlay/guides/percent-y/controlled-zoom 把它塑造成 TopMSV 的局部 envelope 视图。
- **与 `MatchedPeaksTable.tsx`**：selection 的来源是表格行点击；`matchedPeakDetailKey` 的稳定性确保高亮与该面板展示一致。

