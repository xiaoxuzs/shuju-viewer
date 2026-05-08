## `front/src/api/types.ts` 逐行解释

> 目标：把后端 FastAPI（Pydantic）响应模型在前端用 TypeScript 接口表示出来，以便：
> - `api.get<T>()` 能推断 `data` 的结构；
> - React 组件能获得稳定字段名与可空性约束；
> - 明确区分“数据库主键 id”与“TopPIC 业务 id（sequence_id / proteoform_id / prsm_id）”。

---

### L1-L7：文件级注释（最重要的约定）

- **L1-L3**：声明这些类型与后端 Pydantic 输出对应。
- **L4-L7**：强调“两个 id 体系”的区别：
  - **`id`**：通常是 PostgreSQL 表的主键（如 `proteins.id`、`proteoforms.id`），用于后端 join 与 detail 路由参数。
  - **`sequence_id` / `proteoform_id` / `prsm_id`**：TopPIC/业务侧标识，更适合展示给用户，也用于 PrSM detail 页 URL 中的编号。

这个区别贯穿整个系统，避免出现“用户看到的编号”和“数据库行 id”混用导致的链接/查询错误。

---

### L8-L13：分页容器 `Page<T>`

- **L8-L13**：通用分页结构：
  - `items`：当前页数据
  - `total`：总数
  - `page`：当前页号
  - `page_size`：每页大小

字段名与后端一致，因此前端分页组件可直接用。

---

### L15-L23：`CutoffOut`（虚拟 cutoff 摘要）

- **L15**：注释说明 cutoff 用于表示某一 FDR/结果层级。
- **L16-L23**：
  - `id`：前端用的合成 id（后端生成；不是 DB 表 id，因为 universal schema 没有 cutoff 表）。
  - `kind`：常见是 `"prsm"` 或 `"proteoform"`，也允许 string 扩展。
  - `label`：展示用字符串（例如某个阈值）。
  - `protein_count` / `proteoform_count` / `prsm_count`：统计值。

---

### L25-L32：`DatasetDeletedOut`

- 对应 `DELETE /datasets/{slug}` 的响应：
  - `deleted_db`：数据库是否删除成功
  - `deleted_disk`：磁盘目录是否删除成功
  - `folder`：尝试删除的目录路径（可能为 null）
  - `folder_existed`：删除前目录是否存在（用于解释 “deleted_disk=false 但其实没目录” 这类情况）

---

### L34-L46：`DatasetOut`

- 数据集元数据：
  - `id`：DB 主键
  - `slug`：字符串标识（URL 使用）
  - `name` / `description`
  - `source_path`：后端记录的源路径/解压路径（用于调试与定位）
  - `capabilities`：能力集合（JSON），决定 spectra source、是否有 mzML mapping 等
  - `created_at`：创建时间字符串
  - **`updated_at`**：注释强调 universal schema 没有该列，因此后端总返回 null（L43-L44）
  - `cutoffs`：下属 cutoff 列表（虚拟）

---

### L48-L70：导入任务类型 `ImportJobOut` / `ImportJobCreatedOut`

#### `ImportJobOut`（L49-L65）

- `job_id`：任务 uuid
- `status`：queued/running/success/failed（后端也允许 string 扩展）
- `message`：提示文本
- `error`：失败错误文本
- `dataset_slug`：任务最终绑定的数据集 slug（失败/未完成时可为 null）
- `progress`：0..100 的真实进度
- `stage`：阶段码（extract/init/proteins/matches/...）
- `stage_label`：面向用户的阶段名称（当前构建里是中文）
- `stage_detail`：自由格式细节（例如 “1234/4567 PrSM details”）
- `created_at`/`updated_at`：时间戳字符串

#### `ImportJobCreatedOut`（L67-L70）

- POST `/imports` 的创建响应：包含 `job_id` 与初始 `status`。

---

### L72-L82：`ProteinListItemOut`

- 这是某 cutoff 下 protein 列表的一行：
  - `id`：DB 主键（用于 protein detail 路由）
  - `sequence_id`：TopPIC sequence id（展示/业务标识）
  - `sequence_name` / `sequence_description`
  - `compatible_proteoform_number`：该 protein 下 proteoform 数
  - `prsm_number`：该 protein 下 PrSM 数
  - `best_prsm_id` / `best_prsm_e_value`：用于“最佳 PrSM”快速跳转与展示（可能为空）

---

### L84-L96：`ProteoformListItemOut`

- proteoform 列表行：
  - `id`：DB 主键（用于 detail 路由）
  - `proteoform_id`：TopPIC 业务 id
  - `sequence_id`/`sequence_name`：所属 protein 的标识与名称
  - `proteoform_mass`：可空（有些输入格式可能缺失）
  - `prsm_number`：该 proteoform 下 PrSM 数
  - `best_prsm_id`/`best_prsm_e_value`：最佳 PrSM（可空）
  - `n_acetylation` / `unexpected_shift_number`：TopPIC 特征字段（可空）

---

### L98-L114：`PrsmListItemOut`

- PrSM 列表摘要字段：
  - `id`：DB 行主键（通常不用在 URL）
  - `prsm_id`：TopPIC 业务 id（URL 与展示用）
  - `sequence_id`：所属 protein 的 TopPIC id
  - `p_value`/`e_value`/`fdr` 等统计指标（可空）
  - `matched_fragment_number`/`matched_peak_number`
  - precursor 信息（mono mass/charge/mz）
  - `proteoform_mass`
  - `ms1_scans`/`ms2_scans`：字符串形式（通常是 “1,2,3” 或类似的 scan 列表）

---

### L116-L125：detail 类型继承

#### `ProteinDetailOut`（L117-L119）

- 继承 `ProteinListItemOut`，额外加 `proteoforms: ProteoformListItemOut[]`。

#### `ProteoformDetailOut`（L122-L125）

- 继承 `ProteoformListItemOut`：
  - `protein_id`：所属 protein 的 DB 主键（用于回链/跳转）
  - `prsms`：该 proteoform 下 PrSM 列表（摘要）

---

### L127-L142：`PrsmDetailOut`（最关键：带原始 JSON）

- **L127-L130**：注释强调：PrSM detail 包含原始 `annotated_protein` 与 `ms_peaks` JSON，前端会用 `features/prsm/parse.ts` 做二次解析与归一化。
- **L131-L142**：在 `PrsmListItemOut` 基础上增加：
  - `dataset_id`：DB 主键（mzML-memory 光谱接口需要）
  - `run_id`：run 主键（mzML mapping 的关键）
  - `proteoform_id`：proteoform 的 DB 主键（注意同名字段在 list 里是 TopPIC id，因此这里用 DB 体系）
  - `spectrum_file_name`：用于 mzML mapping/调试
  - `ms1_ids`/`ms2_ids`：TopFD/TopPIC 的 spectrum id 字符串（TopFD JS 模式使用）
  - `feature_inte`：特征强度
  - `ms_header`：原始 ms header JSON（可空）
  - `annotated_protein`：原始 protein 注释 JSON（可空）
  - `ms_peaks`：原始去卷积峰 JSON（可空）

这些 JSON 字段采用 `Record<string, unknown>` 而不是更细的 TS 类型，是为了：
- 后端输入来源可能不同（TopPIC tree vs prsm.js bundle），字段细节会变；
- 前端统一在 `parse.ts` 做容错与归一；
- 避免在 `types.ts` 里硬编码极其庞杂且易变的 TopPIC JSON schema。

