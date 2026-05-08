## `front/src/pages/ProteinsPage.tsx` 逐行解释

> 目标：protein 列表页。按 (dataset slug, cutoff) 分页拉取 proteins，支持搜索（name/description），默认按 `best_prsm_e_value` 升序排序，让“最佳匹配更好”的蛋白排在前面。

---

### L1-L3：文件级注释

- **L1-L3**：说明该页按 cutoff 分页显示 protein，支持搜索，默认按最佳 e-value 升序。

---

### L4-L18：依赖

- **L4**：`useState`：存 page 与 search。
- **L5**：`Link` 做可点击链接；`useParams` 读取 URL 的 `slug/cutoff`。
- **L6**：`useQuery` 拉取列表。
- **L7**：搜索图标。
- **L9**：`fetchProteins` API。
- **L10-L16**：UI：Card/Input/PageHeader/Pagination/Skeleton/Table/Badge。
- **L17**：`formatEValue`：统一 e-value 展示格式（科学计数/空值）。

---

### L19-L37：状态与查询

- **L20**：从 URL 取 `slug`、`cutoff`。
- **L21**：`page` 初始为 1。
- **L22**：`search` 初始为空。
- **L23**：`pageSize=50`。
- **L24-L25**：排序固定为：
  - `listSort="best_prsm_e_value"`
  - `listOrder="asc"`
  这样 queryKey 中显式包含 sort/order，未来若允许切换排序不需要改 key 结构。
- **L27-L37**：`useQuery`：
  - key：`["proteins", slug, cutoff, page, search, listSort, listOrder]`
  - queryFn：调用 `fetchProteins(slug, cutoff, {page, page_size, search?, sort, order})`
  - 当 search 为空时传 `undefined`（L33），避免把空字符串当作有效搜索词。

---

### L39-L136：渲染

#### 1) PageHeader（L41-L64）

- title="Proteins"
- description：提示当前 cutoff，点击行可打开详情。
- crumbs：Datasets → slug → cutoff → Proteins（最后一项无链接）
- actions：右侧搜索框：
  - 搜索框前置 icon
  - onChange 更新 `search` 并把 page 重置为 1（L57-L60），保证搜索从第一页开始。

#### 2) 列表 Card（L66-L125）

- loading：用 10 条 Skeleton 模拟表格行。
- 非 loading：渲染 Table：
  - 表头：ID/Sequence Name/Description/Proteoforms/PrSMs/Best e-value
  - 每行（L87-L120）：
    - `<TableRow>` 整行可点击：通过 `window.location.href` 跳转到 detail（L91-L93）。
      - 这里选择 `window.location.href` 而不是 `navigate`，属于简单粗暴的跳转方式（会触发整页路由跳转）。
    - 第一列显示 `sequence_id`（业务 id）并使用 monospace muted（L95-L97）。
    - Sequence Name 用 `Link`，并在点击时 `stopPropagation()`，避免触发行 onClick（L102）。
    - Description 截断显示，空时 `—`。
    - Proteoforms/PrSMs 用 Badge 强调数值。
    - Best e-value 用 monospace 右对齐显示。

#### 3) Pagination（L127-L134）

- 将 page/pageSize/total 传给 `Pagination` 组件。
- `onPageChange={setPage}` 让分页控件驱动 state，进而触发 queryKey 变化与重新拉取。

---

### 与其它模块的耦合点

- **与 `front/src/api/client.ts::fetchProteins`**：参数名必须与后端 query 一致（page_size/sort/order/search）。
- **与路由**：跳转路径 `/datasets/${slug}/${cutoff}/proteins/${p.id}` 中的 `p.id` 是 DB 主键（详见 `types.ts` 的区分）。
- **与 `Pagination` 组件**：该组件决定分页 UI 与边界行为（第一页/最后一页等）。

