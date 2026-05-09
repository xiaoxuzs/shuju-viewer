## `front/src/components/common/stat.tsx` 逐行解释

> 一个通用“统计卡片”组件：上方小标题（label）+ 大号数值（value）+ 可选提示（hint）。

---

## L1-L5：依赖

- **L1-L3**：文件注释描述组件用途。
- **L4**：`cn`：合并 className（Tailwind）。

---

## L6-L29：`Stat` 组件

### Props（L6-L16）

- **label/value**：必填（ReactNode，方便传入格式化后的数字或带单位的 JSX）。
- **hint**：可选次要说明行。
- **className**：允许外部覆盖样式（例如改宽度、改背景等）。

### UI（L17-L27）

- 外层：圆角 + 半透明卡片背景 + hover 边框变化（适合作为 dashboard 卡片）。
- label：小号 uppercase + tracking。
- value：较大字号、强调展示。
- hint：可选，弱化颜色。

