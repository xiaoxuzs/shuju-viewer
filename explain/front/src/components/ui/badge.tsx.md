## `front/src/components/ui/badge.tsx` 逐行解释

> `Badge` 是一个小型标签组件，用 `class-variance-authority (cva)` 做 variant 变体管理，统一不同语义的颜色/边框（default/secondary/destructive/outline/success）。

---

## L1-L3：依赖

- `React`：类型与 props。
- `cva`：定义可组合的样式变体。
- `cn`：合并 className（避免外部覆盖时冲突）。

---

## L5-L21：`badgeVariants`

- **L5-L6**：基础类名：inline-flex、圆角、边框、padding、字体等。
- **L8-L16**：variants：
  - `default`：主色弱背景
  - `secondary`：次级背景
  - `destructive`：红色语义（错误/删除）
  - `outline`：仅边框
  - `success`：绿色语义（成功状态）
- **L17-L19**：默认 variant 为 `default`。

---

## L23-L29：类型与组件

- **L23-L25**：`BadgeProps`：继承 div 的 HTMLAttributes + variant 的类型。
- **L27-L28**：`Badge`：渲染为 `<div>`，className 由 `badgeVariants({variant})` 与外部 className 合并。

