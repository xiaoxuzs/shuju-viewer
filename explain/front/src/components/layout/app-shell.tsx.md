## `front/src/components/layout/app-shell.tsx` 逐行解释

> 全局页面壳：顶部导航栏 + 主内容区域。并在进入具体数据集路由后，根据 URL 参数 `slug` 显示第二级入口（当前数据集）。

---

## L1-L8：依赖

- **L1-L4**：文件注释：说明是壳层组件，子路由通过 `<Outlet />` 渲染。
- **L5**：`react-router-dom`：
  - `NavLink`：根据 active 状态自动加样式
  - `Outlet`：渲染子路由页面
  - `useParams`：读取路由参数 `slug`
- **L6**：图标：数据集/当前数据集入口。
- **L7**：`cn`：拼接 className。

---

## L9-L47：`AppShell`

- **L10**：读取 `{ slug }`：当路由匹配 `/datasets/:slug/...` 时存在。
- **L13-L16**：背景层：soft glow + grid，并用 `pointer-events-none` 防止遮挡交互。
- **L17-L40**：header：
  - 左侧品牌：图标 + 标题 + 副标题。
  - 右侧导航：
    - 永远显示 `Datasets`（`/datasets`）
    - 如果有 `slug`，额外显示指向 `/datasets/{slug}` 的链接（相当于“回到当前数据集概览”）。
- **L42-L45**：main：限定最大宽度并留白，渲染 `<Outlet />`。

---

## L49-L73：`HeaderLink`（内部小组件）

- 统一 `NavLink` 的样式逻辑：
  - hover：背景高亮
  - active：`bg-accent text-foreground`
- `children` 做 truncate，避免 slug 过长撑破导航栏。

