## `front/src/components/ui/input.tsx` 逐行解释

> `Input` 基础输入框组件：封装 Tailwind 样式、focus ring 与 disabled 状态，并通过 forwardRef 让表单库更容易接入。

---

## L1-L3：依赖

- `React`：forwardRef 与原生 input props 类型。
- `cn`：合并 className。

---

## L4-L18：`Input`

- **L4-L5**：forwardRef：透传 ref 到 `<input>`。
- **L6-L14**：渲染 `<input>` 并设置 className：
  - 尺寸、边框、背景、placeholder 颜色
  - `focus-visible:ring-*`：键盘导航时的可访问性 focus 样式
  - `disabled:*`：禁用态的光标与透明度
- **L17**：displayName 便于调试。

