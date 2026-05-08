## `front/src/pages/ProteoformsPage.tsx` 逐行解释

> 目标：proteoform 列表页。按 (slug, cutoff) 分页拉取 proteoforms，默认按 `prsm_number` 降序，让“PrSM 多的形式”排在前面，便于优先查看。

---

### L1-L3：文件级注释

- **L1-L3**：说明该页按 cutoff 分页，默认按 PrSM 数量降序。

---

### L4-L15：依赖

- **L4**：`useState`：保存 page。
- **L5**：`Link` 与 `useParams`。
- **L6**：`useQuery`。
- **L8**：`fetchProteoforms` API。
- **L9-L14**：UI：Badge/Card/PageHeader/Pagination/Skeleton/Table。
- **L15**：格式化工具：e-value 与数值。

---

### L17-L31：状态与查询

- **L18**：读 `slug/cutoff`。
- **L19**：page 初始 1。
- **L20**：pageSize=50。
- **L22-L31**：`useQuery`：
  - key：`["proteoforms", slug, cutoff, page]`
  - queryFn：`fetchProteoforms(slug, cutoff, {page, page_size, sort:"prsm_number", order:"desc"})`

---

### L33-L107：渲染

#### 1) PageHeader（L35-L43）

- title="Proteoforms"
- description：展示当前 cutoff
- crumbs：Datasets → slug → Proteoforms（这里 crumbs 没把 cutoff 单独作为 crumb，属于简化）

#### 2) 列表 Card（L45-L95）

- loading：10 条 Skeleton。
- 否则：Table：
  - 表头：ID/Protein/Proteoform/Mass/PrSMs/Best e-value
  - 每行：
    - 第一列显示 `sequence_id`（业务 id）
    - Protein 列显示 `sequence_name`
    - Proteoform 列 Link 到 detail：`/datasets/${slug}/${cutoff}/proteoforms/${pf.id}`（参数用 DB 主键）
    - 展示文本用业务 id：`Proteoform #${pf.proteoform_id}`
    - mass/e-value 格式化
    - PrSM 数用 Badge

#### 3) Pagination（L97-L104）

- 传入 page/pageSize/total 与 onPageChange。

---

### 与其它模块的耦合点

- **与 `fetchProteoforms`**：排序字段 `prsm_number` 必须是后端支持的 sort key。
- **与 detail 路由**：proteoform detail 参数使用 `pf.id`（DB 主键），展示使用 `proteoform_id`（业务 id）。

