# `back/app/main.py` 逐行解释

> 来源文件：`back/app/main.py`

## L1-L1

- 定义模块文档字符串：该文件是 FastAPI 应用入口。

## L3-L5

- `from __future__ import annotations`：让类型注解延迟求值，减少循环引用问题。
- 引入 `asynccontextmanager`：用于 FastAPI 的 lifespan（启动/关闭生命周期）管理。

## L7-L8

- 引入 FastAPI 与 CORS 中间件：后端要提供 HTTP API 给浏览器前端访问。

## L10-L17

- `api_router`：从 `app.api.v1` 导入聚合路由（统一挂在 `/api/v1`）。
- `settings`：配置对象（包含 CORS origins、DATA_ROOT 等）。
- `configure_logging/get_logger`：统一日志配置与 logger。
- 从 `app.services.import_jobs` 导入三个“启动时补 schema”的函数：
  - `ensure_jobs_table()`：创建 `import_jobs`（UI 导入进度轮询依赖）
  - `ensure_dataset_zip_fingerprint_schema()`：给 `datasets` 增加 `source_zip_sha256` 与唯一索引（避免同 ZIP 重复导入）
  - `ensure_runs_metadata_schema()`：给 `runs` 增加 `run_metadata`（mzML memory 模式 run ↔ mzML 路径映射依赖）

## L19

- 获取模块级 logger：供启动阶段输出日志。

## L22-L29

- 定义 FastAPI lifespan：
  - L24：初始化日志（例如格式、等级、输出目的地）
  - L25：打印启动信息并输出解析后的 `data_root`
  - L26-L28：确保 DB 中的表/列存在（**允许老库自动升级**）
  - L29：`yield` 之后进入正常运行；关闭时没有额外清理逻辑

## L32-L36

- 创建 FastAPI app：
  - `title/version`：OpenAPI 文档展示信息
  - `lifespan=lifespan`：把上面的启动初始化挂进应用生命周期

## L38-L44

- 注册 CORS 中间件：
  - `allow_origins=settings.cors_origin_list`：允许前端 dev server（通常 `http://localhost:5173`）跨域访问
  - `allow_methods/headers=["*"]`：开发期更方便；如需收敛可在生产环境缩小范围

## L46

- `app.include_router(api_router)`：把所有 v1 API 统一挂载到应用中。

## L49-L51

- `GET /health`：
  - 用于健康检查（脚本/反向代理/容器探针）
  - 返回固定 JSON：`{"status": "ok"}`

