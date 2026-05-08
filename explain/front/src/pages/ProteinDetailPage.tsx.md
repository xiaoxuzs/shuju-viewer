## `front/src/pages/ProteinDetailPage.tsx` 逐行解释

> 目标：protein 详情页。展示该 protein 的统计信息（proteoform 数、PrSM 数、最佳 e-value、最佳 PrSM 链接），并列出其下属 proteoforms 表格，支持跳转到 proteoform detail 或 PrSM detail。

---

### L1-L3：文件级注释

- **L1-L3**：说明这是蛋白质详情页：展示统计信息与下属 proteoform 表格/链接。

---

### L4-L14：依赖

- **L4**：`Link` 与 `useParams`。
- **L5**：`useQuery`。
- **L7**：`fetchProtein` API。
- **L8-L13**：UI：Badge/Card/PageHeader/Skeleton/Stat/Table。
- **L14**：格式化工具：`formatEValue` 与 `formatNumber`（质量等数值）。

---

### L16-L21：读取 params 并请求 protein detail

- **L17**：从 URL 取 `slug/cutoff/proteinId`，均提供默认空字符串。
- **L18-L21**：`useQuery`：
  - key：`["protein", slug, cutoff, proteinId]`
  - queryFn：`fetchProtein(slug, cutoff, Number(proteinId))`

这里把 proteinId 转成 number，符合后端路由参数类型（DB 主键）。

---

### L23-L26：loading/error/空数据短路

- loading：Skeleton
- error：红色错误文本
- 无 data：返回 null

---

### L27-L117：渲染

#### 1) PageHeader（L29-L39）

- title：`data.sequence_name`
- description：`sequence_description`（可空）
- crumbs：Datasets → slug → Proteins(cutoff) → 当前序列名
- actions：右侧 badge 显示 `sequence_id`（业务 id），提醒用户当前看到的编号与 DB 主键不同。

#### 2) 统计卡（L41-L60）

- Proteoforms 数、PrSM 数、Best e-value。
- Best PrSM：
  - 若 `best_prsm_id` 存在，则渲染 Link 到 PrSM detail：`/datasets/${slug}/${cutoff}/prsms/${data.best_prsm_id}`（注意这里用的是业务 PrSM id）。
  - 否则显示 `—`。

#### 3) Proteoforms 表格（L62-L114）

- Card 标题显示 proteoforms 数量。
- 表头：Proteoform ID / Mass / PrSMs / Best e-value / Best PrSM。
- 每行：
  - Proteoform detail 路由用的是 `pf.id`（DB 主键）
  - 展示文本用 `pf.proteoform_id`（业务 id）
  - 质量格式化 `formatNumber(...,4)`
  - PrSM 数用 Badge
  - Best PrSM 若存在则 link 到 PrSM detail（同样使用业务 id）

---

### 与其它模块的耦合点

- **与 `types.ts`**：字段含义（`id` vs `sequence_id` vs `proteoform_id`）决定了“链接参数用哪个字段”。
- **与后端 `proteins` API**：返回 `proteoforms` 子数组，决定表格内容。
- **与 PrSM detail 路由**：这里拼接的 PrSM URL 与 `App.tsx` 路由表必须一致。

