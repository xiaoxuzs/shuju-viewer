## `front/src/pages/DatasetPage.tsx` 逐行解释

> 来源文件：`front/src/pages/DatasetPage.tsx`

> 目标：单个数据集概览页。拉取 `/datasets/{slug}`，展示 cutoffs 汇总统计，并提供进入 proteins / proteoforms / prsms 列表页的入口。

---

### L1-L3：文件级注释

- **L1-L3**：说明该页面用于单个数据集概览：汇总各 cutoff 规模，并链接到三类列表页。

---

### L4-L14：依赖

- **L4**：`Link` 用于 cutoff 卡片内的跳转；`useParams` 从 URL 取 `slug`。
- **L5**：`useQuery` 请求 dataset。
- **L6**：图标。
- **L8**：`fetchDataset` API。
- **L9-L13**：UI：Badge/Card/PageHeader/Skeleton/Stat。

---

### L15-L21：读取 slug 并请求数据

- **L16**：`useParams()` 取 `slug`，默认 `""`。
- **L17-L21**：`useQuery`：
  - `queryKey: ["dataset", slug]`：按 slug 分缓存。
  - `queryFn`：调用 `fetchDataset(slug)`。
  - `enabled: !!slug`：slug 为空时不发请求（避免无效请求）。

---

### L23-L26：加载/错误/空数据短路

- **L23**：loading 时返回 Skeleton。
- **L24**：error 时用红色文本显示 error.message。
- **L25**：无 data 返回 null（理论上 enabled 保障，但仍做防御）。

---

### L27-L30：汇总统计

- 对所有 cutoffs 的计数求和得到：
  - proteins 总数
  - proteoforms 总数
  - prsms 总数

这里的逻辑与 `DatasetsPage` 一致，都是把多个 cutoff 的规模汇总成数据集整体规模。

---

### L31-L82：渲染

- **PageHeader**（L33-L37）：
  - title=data.name
  - description：优先 data.description，否则给默认提示
  - crumbs：Datasets → 当前数据集名
- **Stat 网格**（L39-L44）：
  - Cutoffs 数量
  - Proteins / Proteoforms / PrSMs 总量（toLocaleString）
- **Cutoffs 列表**（L46-L79）：
  - 每个 cutoff 一张 Card：
    - 左侧 Filter 图标 + kind badge（uppercase）
    - title 显示 c.label
    - description 显示三类计数
    - CardContent 内三块链接：
      - `/datasets/{slug}/{c.kind}/proteins`
      - `/datasets/{slug}/{c.kind}/proteoforms`
      - `/datasets/{slug}/{c.kind}/prsms`

这里的 `c.kind` 是后端 synthesise 的 cutoff kind（通常是 `"prsm"` 或 `"proteoform"`），决定下游列表页按哪个 cutoff 过滤。

---

### L84-L97：`CutoffLink` 子组件

- 接收 `to/label/count`。
- 渲染为一个 `Link` 卡片：
  - label 用小号 uppercase muted
  - count 用大号数字
  - 右侧 ArrowRight hover 时向右平移并变主色

---

### 与其它模块的耦合点

- **与后端 `/datasets/{slug}`**：返回的 `cutoffs` 决定了页面上显示的入口与计数。
- **与 `App.tsx` 路由表**：这些链接必须与路由定义一致，否则会 404。
- **与列表页组件**：Proteins/Proteoforms/Prsms 页会读取 `slug/cutoff` 参数并发起对应查询。

