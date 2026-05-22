# `back/app/api/v1/imports.py` 逐行解释

> 来源文件：`back/app/api/v1/imports.py`
> 模块职责：路径导入 HTTP 入口——原生文件夹选择、入队后台导入任务、轮询 job 状态。

## 结构概览

| 路由 | 函数 | 作用 |
|------|------|------|
| `POST /imports/pick-folder` | `pick_import_folder` | API 主机原生选目录 |
| `POST /imports` | `enqueue_import` | JSON body 提交 `source_path` 并启动后台任务 |
| `GET /imports/{job_id}` | `get_import_job` | 轮询进度/阶段/错误 |

## L28-L33（`_client_is_loopback`）

- 判断请求是否来自 localhost，配合 `IMPORT_PICKER_LOOPBACK_ONLY` 限制原生 picker 仅本地开发可用。

## L36-L58（`pick_import_folder`）

- 需 `settings.import_native_folder_picker=True`，否则 403。
- 调用 `pick_folder_native()`；取消返回 `{cancelled: true}`；成功返回绝对路径。

## L61-L119（`enqueue_import`）

- 校验 `source_path` 非空、存在、为目录；`resolve()` 为绝对路径。
- **Fail fast**：`resolve_ingest_root(p)` 在入队前验证 TopPIC 树可解析。
- `create_job(..., source_path=resolved)` 写入 `import_jobs` 行。
- `start_path_import_background(...)` 启动 daemon 线程执行 `run_path_import_job`。
- 记录 `enqueue_timing` 分段日志（path checks / resolve / create job / total）。

## L122-L139（`get_import_job`）

- 委托 `import_jobs.get_job`；未知 id → 404；读取时惰性 GC 7 天前的 finished job。

## 与相邻模块的耦合

- **dataset_ingest_root**：入队前解析 ingest 根。
- **import_jobs**：任务持久化与后台 worker。
- **DatasetsPage.tsx**：`enqueueImport` + `fetchImportJob` 轮询；`pickImportFolder` 填路径。
