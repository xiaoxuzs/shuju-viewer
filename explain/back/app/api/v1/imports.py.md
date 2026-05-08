# `back/app/api/v1/imports.py` 逐行解释

> 来源文件：`back/app/api/v1/imports.py`

## L1-L6（模块说明）

- 该模块负责“从前端上传 ZIP → 解压到 `DATA_ROOT` → 后台导入 universal schema”。
- 强调两个关键约束：
  - 上传是**流式落盘**（避免把大 ZIP 一次性读进内存）
  - 任务状态写入 `import_jobs` 表，前端轮询 job_id 即可（即使 uvicorn reload，DB 里仍有状态）

## L8-L18（依赖导入）

- `shutil/tempfile/Path`：用于将 `UploadFile` 写入临时文件
- FastAPI 参数类型：
  - `UploadFile`：上传文件句柄（支持流式读取）
  - `File/Form`：声明 multipart form 字段
  - `HTTPException/status`：抛出 HTTP 错误
- `ImportJobCreatedOut/ImportJobOut`：API 输出模型
- `import_jobs`：服务层（创建 job、启动后台线程、查询 job）
- `sha256_hex_of_file`：计算 ZIP sha256，用于“相同 ZIP 防重复导入”

## L20

- 创建 `router = APIRouter(tags=["imports"])`

## L23-L99：`POST /imports`（enqueue_import）

### L24-L29（参数定义）

- `file`：必须是 zip（描述里明确是 TopPIC 输出树 ZIP）
- `slug/name/description`：数据集标识与展示信息（来自表单字段）

### L30-L35（文件类型校验）

- 必须有文件名且以 `.zip` 结尾，否则 400。

### L36-L68（流式落盘到临时文件）

- `NamedTemporaryFile(delete=False)`：
  - Windows 下常见需要 `delete=False`，否则关闭前可能被占用无法再次打开
- `shutil.copyfileobj(file.file, tf, length=1024*1024)`：
  - 1MiB chunk 拷贝，避免占用过大内存
- 若写入后大小为 0：400（空文件）
- 异常处理策略：
  - 若已生成 `zip_path`，尽力删除临时文件
  - `HTTPException` 原样抛出；其它异常封装为 500
  - `finally` 里关闭 UploadFile（避免句柄泄露）

### L69-L83（重复 ZIP 检测）

- 计算 zip sha256：`zip_sha256_hex = sha256_hex_of_file(zip_path)`
- 调用 `import_jobs.find_dataset_with_zip_sha256(...)`：
  - 若数据库里已有 `datasets.source_zip_sha256` 相同的行，则认为该 ZIP 已被导入过
  - 删除临时文件并返回 409
  - `detail` 返回结构化信息（message + 已存在 dataset 的 slug/name），前端会把它拼到错误提示里

### L85-L98（创建 job + 启动后台导入）

- `import_jobs.create_job(...)`：
  - 插入 `import_jobs` 表（status=queued）
  - 存储 `slug/name/description/source_zip_name`
- `import_jobs.start_zip_import_background(...)`：
  - 以 daemon thread 启动后台导入（解压 + ingest + 原子替换目录）
  - 传入 zip_path、slug/name/description、zip sha256

### L99（返回）

- 返回 `202 Accepted` + `{ job_id, status }`

## L102-L119：`GET /imports/{job_id}`

- `import_jobs.get_job(job_id)` 从 DB 取当前 job 状态（并顺便 GC 过旧 job）
- job 不存在：404
- 否则映射为 `ImportJobOut` 返回给前端轮询显示进度条

