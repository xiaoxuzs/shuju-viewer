## `front/src/lib/utils.ts` 逐行解释

> 来源文件：`front/src/lib/utils.ts`

> 该文件放一些“全局通用的小工具函数”：样式类名合并（Tailwind 常见需求）与数值格式化（表格/统计卡片展示）。

---

## L1-L5：模块说明与依赖

- **L1-L3**：注释说明两类工具：`cn` 合并类名、数值格式化函数。
- **L4-L5**：依赖：
  - `clsx`：把条件 className（字符串/数组/对象）归一化成字符串
  - `tailwind-merge`：对 Tailwind 冲突类做去重与“后者覆盖前者”（例如 `p-2` 与 `p-4`）

---

## L7-L10：`cn(...inputs)` — 合并 className

- **L8-L9**：`twMerge(clsx(inputs))`：
  - 先用 `clsx` 把各种输入形态合成字符串
  - 再用 `twMerge` 合并冲突的 Tailwind 类

它是 UI 组件里最常用的工具：所有 `className={cn("...", className)}` 都靠它保证可扩展且不互相覆盖出错。

---

## L12-L22：`formatNumber` — 一般数值格式化（更偏表格展示）

- **L16-L17**：`null/undefined/NaN` 统一展示为 `"—"`（避免 UI 上出现 `null` 或 `NaN`）。
- **L18-L20**：极小/极大值用科学计数法：
  - \(|n| < 1e-3\) 或 \(|n| >= 1e5\) 时：`toExponential(digits)`
- **L21**：否则用 `toLocaleString`（自动千分位），并允许保留更多小数（`maximumFractionDigits: digits + 2`），避免把一些质量/误差过度截断。

---

## L24-L28：`formatEValue` — e-value/p-value 专用格式化

- **L25-L27**：空值展示 `"—"`；否则固定用两位科学计数法 `toExponential(2)`。

用于 PrSM/Proteoform 列表里显示显著性指标，保证显示风格统一。

