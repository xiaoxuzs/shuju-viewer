## `front/src/components/ui/button.tsx` 逐行解释

> 来源文件：`front/src/components/ui/button.tsx`

> `Button` 基础组件：用 `cva` 管理 variant/size，并支持 `asChild`（通过 Radix `Slot` 把按钮样式套到任意元素上，例如 `<Link>`）。

---

## L1-L6：依赖

- `React`：forwardRef 与类型。
- `@radix-ui/react-slot`：`Slot` 用于 `asChild` 模式。
- `cva`：样式变体管理。
- `cn`：合并 className。

---

## L7-L34：`buttonVariants`

- **L8**：基础按钮样式：flex 对齐、圆角、focus ring、disabled 状态等。
- **L10-L28**：variants：
  - `variant`：default/destructive/outline/secondary/ghost/link
  - `size`：default/sm/lg/icon
- **L29-L33**：默认 `variant=default`、`size=default`。

---

## L36-L40：`ButtonProps`

- 继承原生 `<button>` 属性 + `VariantProps`。
- `asChild?: boolean`：是否使用 `Slot`。

---

## L42-L57：`Button` 组件

- 用 `React.forwardRef` 透传 ref。
- **L44**：`Comp = asChild ? Slot : "button"`：
  - `asChild=true` 时，不强制渲染成 `<button>`，而是把 props 和 className 交给子元素。
- **L46-L50**：className 通过 `buttonVariants({ variant, size, className })` 生成，并用 `cn` 合并。
- **L54**：设置 displayName，方便 React DevTools 调试。

