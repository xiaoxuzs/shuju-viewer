## `front/src/pages/PrsmsPage.tsx` 逐行解释

> 来源文件：`front/src/pages/PrsmsPage.tsx`

> 目标：PrSM 列表页。按 (slug, cutoff) 分页拉取 PrSM，默认按 `e_value` 升序（更好的匹配排前），并提供跳转到 PrSM detail 的链接。

---

### L1-L3：文件级注释

- **L1-L3**：说明该页按 cutoff 分页，默认按 e-value 升序。

---

### L4-L15：依赖

- **L4**：`useState` 保存 page。
- **L5**：`Link`、`useParams` 读取 slug/cutoff。
- **L6**：`useQuery`。
- **L8**：`fetchPrsms` API。
- **L9-L13**：UI：Card/PageHeader/Pagination/Skeleton/Table。
- **L14**：格式化：e-value 与普通数值。

---

### L16-L25：状态与查询

- **L17**：从 URL 取 `slug/cutoff`。
- **L18**：page 初始 1。
- **L19**：pageSize=50。
- **L21-L25**：`useQuery`：
  - key：`["prsms", slug, cutoff, page]`
  - queryFn：`fetchPrsms(slug, cutoff, {page, page_size, sort:"e_value", order:"asc"})`

---

### L27-L106：渲染

#### 1) PageHeader（L29-L37）

- title="PrSMs"
- description：解释这是 protein–spectrum matches 列表，并按 e-value 排序
- crumbs：Datasets → slug → PrSMs

#### 2) 列表 Card（L39-L95）

- loading：10 条 Skeleton。
- 否则渲染 Table：
  - 表头：PrSM ID / e-value / p-value / matched frag/peak / precursor m/z / charge / mono mass / MS2 scan
  - 每行：
    - PrSM ID 列：Link 到 detail：`/datasets/${slug}/${cutoff}/prsms/${p.prsm_id}`
      - **注意**：这里用 `p.prsm_id`（业务 id），不是 `p.id`（DB 主键）。
    - 其它列按右对齐/monospace 展示
    - matched frag/peak 用 `?? "—"` 显示空值

#### 3) Pagination（L97-L104）

- page/pageSize/total/onPageChange 驱动分页。

---

### 与其它模块的耦合点

- **与 `fetchPrsms`**：默认排序字段 `e_value` 必须与后端支持的 sort key 一致。
- **与 PrSM detail**：链接参数必须使用业务 `prsm_id` 才能与后端 detail 路由匹配。

