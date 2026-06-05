# Sequence Coverage UI 改版规划（验收图 10 标准）

> **状态**：规划稿，待确认后交给 Codex 实现  
> **验收样张**：`docs/sequence-coverage-参考/10_demo_P62805_验收布局.png`  
> **规格来源**：`D:\dia-shuju\demo\demo_07_sequence_coverage_p62805.py`  
> **范围**：**仅前端**；不改后端 API、不改 DB、不改导入链路

---

## 1. 目标

将 `SequenceCoverage` 组件从「纯文本 + 单色背景高亮」改为与 **demo_07 图 10** 一致的 **双层布局**：

```
标题 + Coverage: N% · M peptides
─────────────────────────────────
  1  MSGRGKGGKGLGKGGAKRHRKVLRDNIQGITKPAIRRLARRGGVKRISGLIYEETRGVLK  ← 50 aa/行，按肽段分色
 51  VFLENVIRDAVTYTEHAKRKTVTAMDVVYALKRQGRTLYGFGG
─────────────────────────────────
[████████░░░░████████████░░░░░░░░]  ← 线性 coverage 条（灰底 + 彩色肽段块）
─────────────────────────────────
■ GKGGKGLGKGGAKR  ■ DNIQGITKPAIR  …   ← 肽段图例（多列）
```

**成功标准**：在 `bu_pr1_dia` 打开 **P62805** 蛋白详情，肉眼与 `10_demo_P62805_验收布局.png` 布局一致（允许字体渲染差异，不允许缺层）。

---

## 2. 范围边界

### 2.1 本次做（P0）

| 项 | 说明 |
|---|---|
| 双层 UI | 序列行 + 底部 coverage bar + 肽段图例 |
| 50 aa 行宽 | `CHUNK = 50`（替换现有 `LINE_LENGTH = 70`） |
| 肽段分色 | 12 色 palette，按肽段分配 |
| 标题/副标题 | 对齐 demo 文案格式 |
| `coverage_mode` 降级 | 保持现有四级逻辑，仅改「有序列」时的呈现 |
| 悬停 tooltip | segment 上显示 sequence、区间、peptide_id（轻量，无新依赖） |

### 2.2 本次不做

| 项 | 原因 |
|---|---|
| UniProt domain / PTM 轨道 | 超出图 10，属 P1 |
| 横向缩放 / Plotly | 超出图 10 |
| 按 run 分行 | 需 API 扩展 |
| 后端 segment 算法调整 | API 已够用 |
| `BuProteinHeader` 改版 | 标题信息并入 Coverage 卡片即可 |
| `BuPeptideLinksTable` 改版 | 不在验收图内 |

---

## 3. 现状与差距

| 维度 | 现状 `SequenceCoverage.tsx` | 目标（图 10） |
|---|---|---|
| 行宽 | 70 aa | **50 aa** |
| 序列着色 | `bg-primary/25` 背景块，未覆盖 `text-muted` | **字体颜色**按肽段色，覆盖区 **bold** |
| Coverage 条 | 无 | **必须有**，灰底 `#f3f3f3` + 彩色 `axvspan` |
| 图例 | mapped / ambiguous 两色 | **每条肽一段文字 + 色块**，约 4 列 |
| 标题 | `Sequence coverage` + Badge + `33.0% covered` | `Sequence coverage — {accession} ({name})` + `Coverage: 75% · 12 peptides` |
| ambiguous | 琥珀色背景 | 图 10 未单独区分；**P0 保持 ambiguous 可辨识**（见 §5.4） |
| 数据 | `BuProteinDetailOut` 已有 | **无需改 API** |

---

## 4. 视觉规格（量化，从 demo_07 提取）

### 4.1 色板

与 demo 一致，按索引循环（`index % 12`）：

```ts
export const COVERAGE_PEPTIDE_COLORS = [
  "#1f77b4", "#d62728", "#2ca02c", "#ff7f0e",
  "#9467bd", "#8c564b", "#e377c2", "#17becf",
  "#bcbd22", "#7f7f7f", "#aec7e8", "#ffbb78",
] as const;
```

### 4.2 排版

| 元素 | 规格 |
|---|---|
| 卡片标题 | `text-base font-semibold`；文案见 §6.1 |
| 副标题 | `text-sm text-[#444444]`（或 `text-muted-foreground` 近似） |
| 行号 | 右对齐，3 位数字，起始 1/51/101…，`text-xs text-[#666666]`，宽约 `2.5rem` |
| 序列字体 | `font-mono`，约 `text-[10.5px]` ~ `text-sm`，`tracking-wide` |
| 未覆盖氨基酸 | `#111111`，`font-normal` |
| 已覆盖氨基酸 | 对应肽段色，`font-bold` |
| 卡片内容区背景 | 白色为主；可保留浅边框，**去掉**大面积 `bg-muted/20` 灰底 |
| Coverage 条高度 | **14–18px** |
| Coverage 条背景 | `#f3f3f3` |
| Coverage 条色块 | 对应肽段色，`opacity: 0.92` |
| 50 aa 分隔线 | 条内竖向虚线 `#cccccc`，与序列行起始对齐 |
| 图例 | 色块 `12×8px` + 肽段序列；`flex-wrap`，目标 **4 列**（`grid-cols-2 md:grid-cols-4`） |
| 图例字号 | `text-xs`（≈ demo 8.5pt） |
| 区块间距 | 序列区 → 条 → 图例，约 `12–16px` |

### 4.3 长蛋白

参考 `11_demo_P60709_验收布局.png`（375 aa）：

- 序列区纵向增高可接受；
- **coverage 条始终一条**横贯全长（比例缩放，容器 `width: 100%`）；
- 外层 `overflow-x-auto` 仅防极端窄屏，不做横向双滚动条。

---

## 5. 数据映射规则（前端纯函数，建议抽到 `coverageLayout.ts`）

### 5.1 输入

`BuProteinDetailOut` 中：

- `base_sequence`
- `coverage_segments[]`（`start`/`end` 为 0-based `[start, end)`）
- `coverage_percent`（**0–1 小数**，展示时 ×100）
- `coverage_mode`

### 5.2 有效 segment

```ts
mapped = segments.filter(s => s.start != null && s.end != null)
```

### 5.3 排序（与 demo 一致）

```ts
mapped.sort((a, b) =>
  a.start! - b.start! || (b.end! - b.start!) - (a.end! - a.start!)
);
```

### 5.4 肽段 → 颜色

1. 按 **首次出现的 `peptide_id`** 顺序分配 color index（不是按 occurrence 数）。
2. 同一 `peptide_id` 的所有 segment **共用一个颜色**。
3. **ambiguous**（`is_ambiguous === true`）：
   - 序列文字：仍用该肽段色；
   - coverage 条：同色实色块（与 demo 一致）；
   - 图例该项末尾加 `*` 或 `(ambiguous)` 小字——**唯一允许与 demo 的微小扩展**，避免丢失现有语义。

### 5.5 序列逐字着色

对每个位置 `pos`：

1. 找所有满足 `start <= pos < end` 的 segment；
2. 若多个重叠，取 **排序后第一个** segment 的颜色（与 demo `position_color` 一致）；
3. 无覆盖 → 未覆盖样式。

### 5.6 Coverage 条几何

- 容器宽度 100%，x 域 `[0, sequence.length]`。
- 每个 segment 渲染 `left: (start/len)*100%`，`width: ((end-start)/len)*100%`。
- 在 `start % 50 === 0`（且 `start > 0`）处画竖向虚线分隔（与 50 aa 行对齐）。

### 5.7 图例项

- 来源：**有 mapped segment 的 `peptide_id` 去重**，顺序 = 该 id **首次 segment** 在排序列表中的位置。
- 每项：`color` + `sequence`（用 segment 上的 `sequence` 字段）。
- 计数 `M` = 图例项个数（去重肽段数），**不是** `peptides.length`。

### 5.8 `coverage_percent` 展示

- 副标题：`Coverage: {Math.round(coverage_percent * 100)}% · {M} peptides`
- 与 demo 一致用 **整数百分比**（非现有 `33.0%` 一位小数）。
- 右上角现有 `CoverageBadge`（full/partial/…）**保留**，放在副标题右侧或标题行末尾，不替代副标题。

---

## 6. 组件结构与文件

### 6.1 建议改动文件

```
front/src/features/bu/components/sequence/
  SequenceCoverage.tsx      # 编排 + coverage_mode 分支
  coverageColors.ts         # COVERAGE_PEPTIDE_COLORS（新建，~15 行）
  coverageLayout.ts         # 排序、peptideId→color、行切分（新建，~80 行）
  CoverageBar.tsx           # 线性条（新建，可选；也可内联在 SequenceCoverage）
  PeptideLegend.tsx         # 图例（新建，可选）
```

**原则**：逻辑进 `coverageLayout.ts`（可单测），JSX 保持薄。是否拆子组件由 Codex 自定，但 **`SequenceCoverage.tsx` 单文件不超过 ~200 行**为宜。

### 6.2 `SequenceCoverage` 结构（伪代码）

```
Card
  CardHeader
    Title: "Sequence coverage — {accession} ({gene_name || truncate(description)})"
    Subtitle + CoverageBadge
  CardContent
    if decoy → Notice
    if list_only → Notice
    if partial → Warning Notice (unmapped count)
    if has sequence && mode not in (decoy, list_only):
      SequenceLines (50 aa rows)
      CoverageBar
      PeptideLegend
```

### 6.3 标题中的蛋白名

优先级：`gene_name` → `description` 前 40 字符 → 省略括号部分。

示例：`Sequence coverage — P62805 (Histone H4)`

---

## 7. `coverage_mode` 行为（不改语义，只改呈现）

| mode | 序列 + 条 + 图例 | Notice |
|---|---|---|
| `full` | ✅ 全套 | 无 |
| `partial` | ✅ 已映射部分正常展示 | ⚠️ `N 条肽段未能映射到序列` |
| `list_only` | ❌ 不渲染三层 | 蛋白序列不可用… |
| `decoy` | ❌ | Decoy 不提供 coverage… |

`BuPeptideLinksTable` 逻辑不变。

---

## 8. 交互（P0 最小）

| 交互 | 行为 |
|---|---|
| 悬停 coverage 条色块 | `title` 或 shadcn `Tooltip`：`{sequence} [{start}, {end}) · peptide #{id}` |
| 悬停序列字符 | 同上（已有 `title` 可保留并统一格式） |
| 点击 | **不做**跳转（肽段表负责链接 match） |

不引入 Plotly / D3。

---

## 9. 实现步骤（Codex 任务单）

按顺序执行，每步可独立验收：

### Step 1 — 布局常量与纯函数

- [ ] 新建 `coverageColors.ts`
- [ ] 新建 `coverageLayout.ts`：`splitSequenceRows(seq, 50)`、`buildPeptideColorMap(mapped)`、`resolveResidueColor(pos, mapped, colorMap)`
- [ ] 本地 `console.assert` 或临时 vitest（可选，非必须）

**验证**：对 P62805 _mock segments 输出 12 色、2 行序列、12 图例项。

### Step 2 — CoverageBar + PeptideLegend

- [ ] 实现比例定位条 + 50 aa 虚线
- [ ] 实现 4 列图例

**验证**：Storybook 无则直接用 P62805 页面肉眼看条与图例。

### Step 3 — SequenceLines 改写

- [ ] 50 aa 行宽 + 字体色/bold
- [ ] 移除 `bg-primary/25` / `bg-amber-300/50` 背景高亮方案

**验证**：与图 10 序列区对比。

### Step 4 — 卡片标题/副标题

- [ ] 标题含 accession + 蛋白名
- [ ] 副标题 `Coverage: N% · M peptides`
- [ ] Badge 位置调整，避免与副标题重复

### Step 5 — 整合与降级

- [ ] 四种 `coverage_mode` 走通
- [ ] `partial` / `list_only` / `decoy` 不回归

### Step 6 — 构建

```powershell
cd E:\viewer\front
npm run build
```

---

## 10. 验收清单

### 10.1 主验收（P62805）

数据集：`bu_pr1_dia`，蛋白 **P62805**（导入后应有 `base_sequence`）。

| # | 检查项 | 期望 |
|---|---|---|
| 1 | 标题 | 含 `P62805` 与基因/描述名 |
| 2 | 副标题 | `Coverage: …% · … peptides`，整数百分比 |
| 3 | 序列行宽 | 每行 50 个氨基酸（最后一行可不足 50） |
| 4 | 行号 | 1, 51, … |
| 5 | 序列颜色 | 多色、覆盖区加粗，非单色背景块 |
| 6 | Coverage 条 | 灰底 + 彩色块，宽度贯穿全序列 |
| 7 | 图例 | 每条肽一色块 + 序列字符串，多列排列 |
| 8 | 与图 10 对照 | 布局三层齐全，视觉风格一致 |
| 9 | 肽段表 | 下方 `BuPeptideLinksTable` 仍正常、可点 match |

### 10.2 辅验收（P60709，长蛋白）

| # | 检查项 |
|---|---|
| 1 | 375 aa 蛋白序列多行但不破版 |
| 2 | Coverage 条仍为单行比例条 |
| 3 | 图例换行正常 |

### 10.3 降级验收

| # | 条件 | 期望 |
|---|---|---|
| 1 | `list_only` | 仅 Notice，无序列/条/图例 |
| 2 | `decoy` | 仅 Notice |
| 3 | `partial` | 三层 + unmapped 警告 |

### 10.4 回归

```powershell
cd E:\viewer\front
npm run build
git diff -- front/src/features/prsm   # 应为空
```

后端测试 **无需跑**（本次不改后端）。

---

## 11. 风险与待确认

| 项 | 说明 | 建议 |
|---|---|---|
| API `coverage_percent` 与图 10 数值差 | demo 人为补了 `EXTRA_PEPTIDE` 凑 12 条；线上以 API 为准 | **以 API 为准**，不追 demo 75% 绝对值 |
| ambiguous 多 occurrence | API 可返回同一肽多段；图 10 每肽一段 | 条上画多段，**同色**；图例每肽一项 |
| 重叠肽段颜色 | 多肽覆盖同一位置 | 取排序后第一个（§5.5） |
| 极长蛋白（>1000 aa） | 图例可能很长 | P0 允许换行；不做折叠 |
| 字体差异 | 浏览器 vs matplotlib | 验收看布局不看像素级一致 |

**无需用户再确认即可开干**的默认决策：

1. 百分比用整数（demo 标准）。
2. ambiguous 图例加 `*` 后缀。
3. 不改 `BuProteinHeader`。

---

## 12. 参考文件索引

| 文件 | 用途 |
|---|---|
| `docs/sequence-coverage-参考/10_demo_P62805_验收布局.png` | 主验收样张 |
| `docs/sequence-coverage-参考/11_demo_P60709_验收布局.png` | 长蛋白样张 |
| `docs/sequence-coverage-参考/01_Viewer当前实现.png` | 改版前 |
| `D:\dia-shuju\demo\demo_07_sequence_coverage_p62805.py` | 像素级规格源 |
| `front/src/features/bu/components/sequence/SequenceCoverage.tsx` | 改动主文件 |
| `budocs/Sequence-Coverage数据方案.md` | API / coverage_mode 契约 |
| `back/app/bu/services/protein_detail_service.py` | 后端 segment 来源（只读） |

---

## 13. 给 Codex 的一句话摘要

> **只改 `front/src/features/bu/components/sequence/*`，把 `SequenceCoverage` 做成 demo_07 图 10 的三层结构（50aa 分色序列 + 底部比例 coverage 条 + 肽段图例），用现有 `BuProteinDetailOut` 数据，不改 API；验收打开 `bu_pr1_dia` 的 P62805 与 `10_demo_P62805_验收布局.png` 对照。**
