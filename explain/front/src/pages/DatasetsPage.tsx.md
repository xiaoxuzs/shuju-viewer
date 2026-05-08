## `front/src/pages/DatasetsPage.tsx` 逐行解释

> 目标：数据集首页/列表页。负责：
> - 拉取后端 `/datasets` 并以卡片网格展示；
> - 提供“从 ZIP 导入数据集”的弹窗与轮询逻辑；
> - 提供“删除数据集”的确认弹窗与错误提示；
> - 对 loading/error/empty 三种状态分别给出 UX。

---

### L1-L3：文件级注释

- **L1-L3**：说明该页面展示已导入的数据集卡片，并支持上传 ZIP 导入；空状态仍提示 CLI 备选方案。

---

### L4-L28：依赖

- **L4**：React hooks：
  - `useState` 存弹窗与表单状态
  - `useRef` 访问 `<input type=file>` DOM
  - `useCallback` 稳定化回调，避免不必要的子组件重渲染
- **L5**：`Link` 用于卡片点击跳转到 dataset 页面。
- **L6**：TanStack Query：
  - `useQuery` 拉取 datasets
  - `useQueryClient` 用于在导入/删除后 `invalidateQueries`
- **L7**：直接引入 axios：只用于错误解析（识别 AxiosError 并读取后端 `detail`）。
- **L8-L17**：图标。
- **L19**：API 调用函数：
  - `fetchDatasets`：列表
  - `enqueueImport`、`fetchImportJob`：导入与轮询
  - `deleteDataset`：删除
- **L20-L27**：UI 组件（Badge/Button/Card/Input/Skeleton/PageHeader）与 `cn`。

---

### L29-L31：`sleep` 工具函数

- **L29-L31**：把 `setTimeout` 包成 Promise，用于轮询间隔与“成功后延迟刷新”。

---

### L33-L38：datasets 查询（TanStack Query）

- **L34**：拿到 `queryClient`，用于后续 invalidation。
- **L35-L38**：`useQuery({queryKey:["datasets"], queryFn:fetchDatasets})`：
  - key 固定为 `["datasets"]`，便于导入/删除后统一 invalidation。
  - 返回 `data/isLoading/error`。

---

### L40-L48：导入弹窗状态（import dialog state）

- **L40**：`importOpen`：是否显示导入弹窗。
- **L41**：`zipFile`：用户选择的 zip 文件。
- **L42-L44**：`slug`、`dsName`、`description`：导入表单字段。
- **L45**：`importBusy`：导入进行中（禁用表单与按钮）。
- **L46**：`importError`：导入错误提示。
- **L47**：`fileInputRef`：用于在 reset 时清空 file input 的值（受控文件输入在 React 中不方便直接清）。

---

### L49-L52：删除弹窗状态（delete dialog state）

- **L50**：`deleteTarget`：当前要删除的数据集（存在则显示删除确认弹窗）。
- **L51**：`deleteBusy`：删除进行中。
- **L52**：`deleteError`：删除失败提示（常见为 409：仍有 import job）。

---

### L54-L72：`runDelete`（删除动作）

- **L55**：没有 target 则直接返回。
- **L56-L57**：清错误、置 busy。
- **L59**：调用 `deleteDataset(deleteTarget.slug)`。
- **L60**：删除成功后 invalidation：`["datasets"]`，刷新列表。
- **L61**：关闭弹窗：`setDeleteTarget(null)`。
- **L62-L68**：错误处理：
  - 默认 `Error.message`
  - 若是 axios error，则尝试从 `response.data.detail` 取后端错误字符串
- **L69-L71**：finally 复位 busy。

这段把“后端 detail 文案”透传到 UI，能看到更具体原因（例如 409）。

---

### L74-L81：`resetImportForm`（重置导入表单）

- 清空 zip/slug/name/description/error。
- **L80**：如果有 `fileInputRef.current`，把 `value=""`，实现 file input 的真正清空。

---

### L83-L133：`runImport`（上传 + 轮询导入任务）

#### 1) 前置校验（L84-L87）

- 要求 zipFile、slug、name 都存在，否则在 UI 显示错误文案并返回。

#### 2) 发送请求（L88-L97）

- 清 error、置 busy。
- 构建 `FormData`：
  - `file`：zip
  - `slug`/`name`
  - `description` 可选
- 调用 `enqueueImport(form)` 获取 `jobId`。

#### 3) 轮询（L98-L114）

- 无限循环：
  - `fetchImportJob(jobId)`
  - 若 `success`：
    - sleep 400ms（给后端写入/提交一点缓冲）
    - invalidate `["datasets"]`
    - 关闭弹窗 + reset 表单
  - 若 `failed`：
    - 把 `job.error` 或 `job.message` 写到 `importError`
    - 停止
  - 否则 sleep 900ms 再轮询

这里轮询是“简单但可靠”的方式：不需要 websocket/SSE。

#### 4) catch：解析后端的结构化 detail（L115-L132）

- 默认 `Error.message`。
- axios error：
  - `detail` 可能是 string
  - 或者 object（包含 `message/slug/dataset_name`）
  - 按类型分支拼接更友好的错误文本

最后把 `importError` 与 `importBusy` 复位。

---

### L135-L247：页面主体（header + loading/error/empty/data 卡片网格）

- **PageHeader**（L137-L146）：
  - title/description
  - actions：右上角 “Import from ZIP” 按钮打开导入弹窗
- **loading**（L148-L154）：显示 3 个 `Skeleton` 卡片占位。
- **error**（L156-L162）：Card 显示错误信息。
- **empty**（L164-L180）：提示尚未导入，并展示 CLI ingest 的示例命令（用 `<pre>`）。
- **data list**（L182-L247）：
  - 网格渲染每个 dataset 卡片
  - 计算 totals：把所有 cutoffs 的蛋白/proteoform/prsm 计数求和（L185-L187）
  - 卡片内展示 slug badge、name/description、三个 Metric、小的 cutoff badges
  - 右上角 delete 图标按钮：
    - `ev.preventDefault()` + `stopPropagation()` 防止触发外层 Link 跳转
    - 设置 `deleteTarget` 打开删除弹窗

---

### L249-L374：导入弹窗（importOpen）

- 背景遮罩：`fixed inset-0 ...`，语义为 dialog。
- 卡片内容：
  - file input（accept zip）
  - slug/name/description 输入
  - busy 时显示 indeterminate 的进度条 + spinner
  - 显示 importError
  - Cancel：关闭弹窗并 reset 表单
  - Start import：触发 `runImport`

注意：这里没有显示真实百分比，因为当前后端 `/imports/{job}` 返回了 stage/progress，但本 UI 选择了简化的“忙碌态”提示。

---

### L376-L442：删除弹窗（deleteTarget）

- 背景遮罩 + dialog。
- 文案解释删除会做什么：
  - DB cascade 删除多个表
  - Disk 删除目录（受 DATA_ROOT 约束）
  - 如果有 active import job，后端会拒绝（409）
- Cancel：关闭弹窗并清错误
- Delete permanently：触发 `runDelete`

---

### L447-L465：`Metric` 子组件

- 接收 icon/label/value。
- UI：一个小块，顶部图标+label，下面显示 value（toLocaleString）。

---

### 与其它模块的耦合点

- **与 `front/src/api/client.ts`**：所有网络请求都来自这里的封装函数。
- **与后端 `imports`/`datasets` API**：错误文案 `detail` 的形状决定了 catch 分支里如何解析。
- **与 Query 缓存**：依赖 `["datasets"]` key 的 invalidation 来刷新列表。

