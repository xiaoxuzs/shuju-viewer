## `front/src/api/client.ts` 逐行解释

> 来源文件：`front/src/api/client.ts`

> 目标：封装前端对后端 FastAPI `/api/v1` 的所有 HTTP 调用。该文件提供一个带 `baseURL`/超时配置的 axios 实例，并把每个后端路由映射成一个类型安全的函数（返回值类型来自 `front/src/api/types.ts`）。

---

### L1-L4：文件级注释（用途与术语）

- **L1-L4**：说明这是一份“前端 HTTP 客户端”，通过 Vite 代理访问后端 `/api/v1`。
  - `slug`：数据集标识（datasets.slug）。
  - `cutoff`：结果层级/阈值类别（常见为 `prsm`、`proteoform`），对应后端“虚拟 cutoffs”。

---

### L5-L18：依赖（axios + 后端输出类型）

- **L5**：导入 axios。
- **L6-L18**：从 `./types` 导入所有响应类型：
  - 数据集：`DatasetOut`、删除响应 `DatasetDeletedOut`
  - 导入任务：`ImportJobCreatedOut`、`ImportJobOut`
  - 分页：`Page<T>`
  - 业务实体：Protein/Proteoform/PrSM 的 list/detail 类型

这些类型与后端 Pydantic 输出一一对应，保证 `api.get<T>()` 的泛型能把 `data` 推断成正确形状。

---

### L20-L24：axios 实例 `api`

- **L20**：注释指出：开发环境下 Vite 会把 `/api` 请求转发到后端（通常由 `vite.config.ts` 的 proxy 配置实现）。
- **L21-L24**：创建 axios 实例：
  - `baseURL: "/api/v1"`：所有请求都相对这个前缀拼接路径。
  - `timeout: 30_000`：默认 30s 超时（对大多数查询足够）。

这里使用 axios 实例而不是直接用 `axios.get`，方便未来统一加拦截器（例如 auth header、统一错误处理、日志）。

---

### L26-L35：列表接口通用参数 `ListParams`

- 字段名与后端 Query 参数一致（因此不需要前端额外映射）：
  - `page` / `page_size`：分页
  - `sort` / `order`：排序字段与方向
  - `search`：模糊搜索
  - `protein_id` / `proteoform_id`：用于在下钻页面里按外键过滤（例如“某蛋白下的 PrSM”）

---

### L37-L41：`fetchDatasets`

- **L39**：GET `/datasets`，返回 `DatasetOut[]`。
- **L40**：解构 axios 的 `{data}` 并返回。

该接口用于首页/列表页展示数据集与各 cutoff 统计。

---

### L46-L52：`enqueueImport`（路径导入并入队后台任务）

- POST `/imports`，JSON body：`ImportEnqueueIn`（`source_path`、`slug`、`name`、`description`）。
- `Content-Type: application/json`；timeout 600s（入队 + 后台 ingest 可能较久）。
- 返回 `ImportJobCreatedOut`（`job_id`），前端轮询 `fetchImportJob`。

### L54-L62：`pickImportFolder`（API 主机原生选目录）

- POST `/imports/pick-folder`，空 body；`timeout: 0`（对话框阻塞至用户选择）。
- 返回 `ImportPickFolderOut`（`path` 或 `cancelled`）；需后端 `IMPORT_NATIVE_FOLDER_PICKER=true`。

---

### L51-L54：`fetchImportJob`（轮询导入任务状态）

- GET `/imports/{jobId}`，返回 `ImportJobOut`（包含进度、阶段、错误等）。

---

### L56-L60：`fetchDataset`（单个数据集详情）

- GET `/datasets/{slug}`，返回 `DatasetOut`。

通常用于 dataset 页面读取 capabilities（例如支持 topfd_js vs mzml_memory）。

---

### L62-L71：`deleteDataset`（永久删除）

- 注释解释了常见失败原因：
  - 404：不存在
  - 409：仍有运行中的 import job（后端拒绝删除以防竞争条件）
- DELETE `/datasets/{slug}`，返回 `DatasetDeletedOut`（包含 DB 与磁盘清理结果）。

---

### L73-L96：Protein 列表/详情

#### `fetchProteins`（L74-L84）

- GET `/datasets/{slug}/cutoffs/{cutoff}/proteins`
- axios params 直接传 `ListParams`，后端统一解析。
- 返回 `Page<ProteinListItemOut>`。

#### `fetchProtein`（L87-L96）

- GET `/datasets/{slug}/cutoffs/{cutoff}/proteins/{proteinId}`
- 注意注释强调：这里的 `proteinId` 是库表主键 `proteins.id`，不是 TopPIC 的 `sequence_id`。

---

### L98-L121：Proteoform 列表/详情

- `fetchProteoforms`：GET `/.../proteoforms`，分页返回 `Page<ProteoformListItemOut>`。
- `fetchProteoform`：GET `/.../proteoforms/{proteoformId}`，返回 `ProteoformDetailOut`。
  - 注释同样强调 `proteoformId` 是 DB 主键 `proteoforms.id`。

---

### L123-L149：PrSM 列表/详情

- `fetchPrsms`：GET `/.../prsms`，分页返回 `Page<PrsmListItemOut>`。
- `fetchPrsm`：GET `/.../prsms/{prsmId}`，返回 `PrsmDetailOut`。
  - **L136-L139** 注释非常关键：`prsmId` 是 TopPIC 业务 id（`prsms.prsm_id`），不是数据库自增主键。URL 与列表展示都用这个业务 id。

这也是为什么 `PrsmListItemOut` 同时包含 `id` 与 `prsm_id` 两个字段：一个是 DB 行 id，另一个是业务编号。

---

### L151-L161：TopFD JS 模式：按 specId 读取磁盘缓存谱图

- `fetchMs1Spectrum`：GET `/datasets/{slug}/spectra/ms1/{specId}`，返回原始 JSON（不做强类型约束，用 `Record<string, unknown>`）。
- `fetchMs2Spectrum`：GET `/datasets/{slug}/spectra/ms2/{specId}`。

这里返回的是 TopFD `spectrum*.js` 解析出来的 JSON 结构，字段复杂且前端会再用 `parse.ts` 归一化，因此不在 `types.ts` 中硬编码。

---

### L163-L171：mzML-memory 模式：按 (dataset_id, run_id, scan_number) 动态取谱图

- `fetchMzmlSpectrum`：GET `/datasets/{datasetId}/runs/{runId}/spectra/{scanNumber}`。
- mzML-memory 数据集需先驻留：`spectrum_memory` 池（经 `spectrum_memory_wiring.ensure_mzml_dataset_resident`）；legacy 路径仍可能用 `mzml_store.py`。

同样返回原始 JSON，前端再解析/归一化。

补充：当数据集导入时选择 `spectra_source="mzml_memory"`，后端会在 finalize 阶段把每个 `run_id` 对应的 `run_metadata.mzml_file_path` 写入 `runs.run_metadata`，从而保证这里的 `(datasetId, runId, scanNumber)` 能被严格定位到唯一 mzML 文件。

