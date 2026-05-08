## `front/src/pages/ProteoformDetailPage.tsx` 逐行解释

> 目标：proteoform 详情页。展示该形式的质量与修饰统计，并列出该 proteoform 下的 PrSM 列表（可跳转到 PrSM detail）。同时提供“回到 protein”的链接。

---

### L1-L3：文件级注释

- **L1-L3**：说明这是 proteoform 详情页：质量、修饰统计与 PrSM 列表。

---

### L4-L15：依赖

- **L4-L5**：`Link`、`useParams`、`useQuery`。
- **L7**：`fetchProteoform` API。
- **L8-L13**：UI：Badge/Card/PageHeader/Skeleton/Stat/Table。
- **L14**：格式化工具：e-value 与数值。

---

### L16-L21：读取 params 并请求 detail

- **L17**：取 `slug/cutoff/proteoformId`。
- **L18-L21**：`useQuery`：
  - key：`["proteoform", slug, cutoff, proteoformId]`
  - queryFn：`fetchProteoform(slug, cutoff, Number(proteoformId))`

这里 `proteoformId` 是 DB 主键（`proteoforms.id`）。

---

### L23-L25：loading/空数据短路

- loading：Skeleton
- 无 data：返回 null

（本页面没有单独渲染 error 分支，意味着 error 时 data 为空会直接 null；这是一个相对简化的处理方式。）

---

### L26-L107：渲染

#### 1) PageHeader（L28-L44）

- title：`Proteoform #${data.proteoform_id}`（展示业务 id）
- description：`data.sequence_name`（所属 protein 名）
- crumbs：Datasets → slug → Proteoforms（列表）→ 当前 proteoform
- actions：一个 Badge，内部 Link 回到 protein detail：
  - URL 使用 `data.protein_id`（DB 主键）
  - 文案 “← back to protein”

#### 2) Stat 网格（L46-L55）

- Mass：`formatNumber(data.proteoform_mass,4)`
- PrSMs：`data.prsm_number`
- Best e-value：`formatEValue(data.best_prsm_e_value)`
- N-acetylations：
  - value：`data.n_acetylation ?? "—"`
  - hint：若 `unexpected_shift_number` 存在，则显示 `${n} unexpected shifts`

#### 3) PrSM 表格（L57-L104）

- 表头：PrSM ID / e-value / Matched frag/peak / precursor m/z / charge / mono mass / MS2 scan
- 每行：
  - PrSM detail 路由参数使用 `p.prsm_id`（业务 id）：`/datasets/${slug}/${cutoff}/prsms/${p.prsm_id}`
  - 其它数值按列格式化与对齐
  - ms2_scans 以字符串展示（后端给什么就展示什么）

---

### 与其它模块的耦合点

- **与 `types.ts`**：这里同样体现了 `proteoformId`（DB）与 `proteoform_id`（业务）并存的区别。
- **与 PrSM detail 页面**：PrSM 链接必须用业务 id 才能与后端 `GET /prsms/{prsm_id}` 对齐。

