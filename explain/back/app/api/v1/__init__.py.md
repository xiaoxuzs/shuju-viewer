# `back/app/api/v1/__init__.py` 逐行解释

> 来源文件：`back/app/api/v1/__init__.py`

## L1-L1

- 模块 docstring：说明该文件负责“聚合 v1 子路由”，并统一挂载在 `/api/v1` 前缀下。

## L3

- 导入 `APIRouter`：FastAPI 路由聚合器。

## L5

- 导入各子模块（每个模块各自提供 `router`）：
  - `datasets`：数据集列表/详情/删除
  - `imports`：路径导入（POST `/imports`）+ 原生选目录 + 轮询 job
  - `proteins`：按 cutoff 的蛋白列表/详情
  - `proteoforms`：按 cutoff 的 proteoform 列表/详情
  - `prsms`：按 cutoff 的 PrSM 列表/详情
  - `spectra`：TopFD `spectrum*.js`（磁盘读取+缓存）谱图 API
  - `mzml_spectra`：mzML memory（按 run_id 懒加载）谱图 API

## L7

- 创建聚合路由 `api_router` 并设置统一前缀 `/api/v1`：
  - 这确保所有业务 API 都在同一个 namespace 下，便于前端 axios `baseURL="/api/v1"` 调用。

## L8-L14

- 逐个 include 子路由：
  - 每个 `include_router(...)` 会把对应模块内声明的 path（例如 `"/datasets"`）挂在 `/api/v1` 下。
  - 顺序通常不影响路由匹配，但保持“资源类型分组”有助于读 OpenAPI 文档。

