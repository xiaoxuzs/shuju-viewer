# `front/src/App.tsx` 逐行解释

> 来源文件：`front/src/App.tsx`

## L1-L4（模块说明）

- 文件注释说明：这是前端路由入口，所有业务页挂在 `AppShell` 之下。
- URL 结构约定：`/datasets/:slug/:cutoff/(proteins|proteoforms|prsms)/...`。

## L5

- 从 `react-router-dom` 导入 `Routes/Route/Navigate`：
  - `Routes/Route`：声明式路由表
  - `Navigate`：重定向（例如 index → `/datasets`）

## L7-L15（页面与布局组件）

- `AppShell`：全局布局（导航、容器、Outlet）
- `DatasetsPage`：数据集列表页（导入 ZIP、删除数据集）
- `DatasetPage`：单个数据集概览（cutoff 卡片）
- `ProteinsPage` / `ProteinDetailPage`
- `ProteoformsPage` / `ProteoformDetailPage`
- `PrsmsPage` / `PrsmDetailPage`（PrSM 详情页是谱图与序列注释的核心页面）

## L17-L37（路由树）

- 根组件返回 `<Routes>`：
  - 外层 `<Route element={<AppShell />}>`：
    - 让所有子页面共享同一个壳（导航/布局），并通过 `<Outlet/>` 渲染子路由内容
  - `index` 路由：
    - L21：访问 `/` 自动跳转到 `/datasets`
  - 数据集相关：
    - L22：`/datasets` → `DatasetsPage`
    - L23：`/datasets/:slug` → `DatasetPage`
  - cutoff 下资源列表与详情：
    - proteins：
      - L24：列表 `/datasets/:slug/:cutoff/proteins`
      - L25：详情 `/datasets/:slug/:cutoff/proteins/:proteinId`
    - proteoforms：
      - L26：列表 `/datasets/:slug/:cutoff/proteoforms`
      - L27-L30：详情 `/datasets/:slug/:cutoff/proteoforms/:proteoformId`
    - prsms：
      - L31：列表 `/datasets/:slug/:cutoff/prsms`
      - L32：详情 `/datasets/:slug/:cutoff/prsms/:prsmId`
  - 兜底：
    - L33：其它路径全部重定向回 `/datasets`

