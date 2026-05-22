## `front/src/components/common/page-header.tsx` 逐行解释

> 来源文件：`front/src/components/common/page-header.tsx`

> 页面通用标题区组件：可选面包屑（含首页图标）、主标题/描述、右侧操作区（按钮等）。

---

## L1-L7：依赖与用途

- **L1-L3**：文件注释说明组件职责。
- **L4-L5**：`react-router-dom` 的 `Link` + `lucide-react` 图标：渲染面包屑与首页入口。
- **L6**：`cn`：合并 Tailwind className（见 `front/src/lib/utils.ts`）。

---

## L8-L11：`Crumb` 类型

- **label**：展示内容（ReactNode，允许文本/组件）。
- **to**：可选链接；没有 `to` 时显示为纯文本（当前页）。

---

## L13-L65：`PageHeader` 组件

### 传参（L13-L25）

- **title**：必填主标题。
- **description**：可选说明。
- **crumbs**：可选面包屑数组。
- **actions**：右侧操作区（例如删除按钮/导入按钮）。
- **className**：外部自定义样式补丁。

### 渲染结构（L26-L63）

- **L27**：外层 `div` 默认 `mb-8 space-y-3`，并合并外部 `className`。
- **L28-L52**：当存在 crumbs 时渲染 `<nav>`：
  - 第一个固定是 Home 图标链接到 `/`。
  - 每个 crumb 之间用 `ChevronRight` 分隔。
  - 若 crumb 有 `to`：渲染为可点击 `Link`；否则渲染为文本（当前层级）。
  - `truncate/max-w` 避免长标题把布局撑爆。
- **L54-L62**：主标题区：
  - 左侧：`h1` + 可选 description
  - 右侧：actions（若提供）

