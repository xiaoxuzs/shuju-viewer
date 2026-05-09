## `front/src/components/ui/card.tsx` 逐行解释

> 一组轻量 Card 组件：`Card` + `CardHeader/Title/Description/Content/Footer`，通过 forwardRef 便于在上层组合与扩展。

---

## L1-L3：依赖

- `React`：forwardRef 与 HTMLAttributes 类型。
- `cn`：合并 className。

---

## L5-L17：`Card`

- 渲染 `<div>`，提供圆角、边框、背景、阴影与过渡效果。
- 通过 `className` 允许页面自定义布局（例如网格宽度、padding 等）。

---

## L19-L25：`CardHeader`

- 头部容器：默认 `p-6`，并用 `space-y` 给标题与描述留间距。

---

## L26-L36：`CardTitle`

- 用 `<h3>` 渲染标题，提供较醒目的字号与字重。

---

## L37-L43：`CardDescription`

- 用 `<p>` 渲染描述，颜色更淡（muted）。

---

## L44-L50：`CardContent`

- 内容区：默认 `p-6 pt-0`（和 header 连起来看更紧凑）。

---

## L51-L56：`CardFooter`

- 底部区：适合放按钮/操作区，默认 `flex items-center p-6 pt-0`。

