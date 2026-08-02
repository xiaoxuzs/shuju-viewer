# ZP 独立 Worker 与访问层接入设计

状态：设计稿，尚未修改 Viewer 主业务代码。

本文目标是把 `viewer-two` 的 `.zp` 转换和读取能力接入 Viewer，同时保持低耦合、可取消、可回滚、可观测。接入方式采用独立 Worker + 窄访问层，不把大文件转换塞进 Viewer Web 进程。

## 1. 当前结论

可以进入内部试点接入，但不直接生产上线。

已完成的前置验证：

- `viewer-two` 依赖已放宽到 `pyarrow>=23,<25`；
- 本地使用 `pyarrow 24.0.0` 跑通 `viewer-two` 完整测试；
- `viewer-two` 已有 `SourceAdapter` 注册边界，后续新增格式不再优先改 `PlanBuilder` 大分支。

仍不承诺：

- 1GB / 60 秒稳定达标；
- 5GB、10GB 统一 60 秒达标；
- `.zp` 能防止用户获得已展示的科学数据；
- 直接把转换任务放进 Viewer Web 进程。

## 2. 为什么需要独立 Worker

Viewer Web 进程负责响应页面和 API，请求应该快速返回。`.zp` 转换属于重任务，会长时间占用 CPU、内存和磁盘。

如果在 Web 进程内直接转换，会出现：

- 页面接口等待或超时；
- 一个转换拖慢所有用户；
- 转换崩溃可能影响 Web 服务；
- 取消任务只能改数据库状态，不能真正杀掉转换；
- 依赖冲突会污染 Viewer 主环境；
- 多 GB 临时文件失败后更容易泄漏。

推荐结构：

```text
Viewer API
  -> 写入转换任务
  -> 独立 Worker 领取任务
  -> Worker 调用 viewer-two CLI / Python API
  -> 产出 .zp + 校验证书
  -> Viewer zp_access 读取 .zp
  -> 现有前端 API 返回原有响应结构
```

Worker 可以与 Web 进程在同一台机器上运行，但必须是独立进程。当前服务器是容器环境，内部不能再使用 Docker，因此隔离方式以独立 Python 环境、子进程、进程组、资源限制和固定目录为主。

## 3. 推荐新增模块

### 3.1 Worker 编排模块

建议新增：

```text
back/app/zp_conversion/
    contracts.py
    repository.py
    service.py
    worker_runner.py
    process_control.py
    paths.py
```

职责：

- 创建、查询、取消 ZP 转换任务；
- 保存任务状态、进度、错误码、输入/输出大小、校验结果；
- 固定调用 viewer-two 的入口；
- 控制临时目录和最终 `.zp` 目录；
- 失败时清理半成品；
- 取消时真正终止 Worker 进程树。

禁止：

- 不在 `import_jobs.py` 里继续堆复杂转换逻辑；
- 不接受用户传入 Python 解释器路径、脚本路径、输出路径；
- 不把 Worker stdout/stderr 原样返回前端；
- 不让 Agent 或用户控制服务器任意文件路径；
- 不在 Web 进程内直接做多 GB 转换。

### 3.2 ZP 读取访问层

建议新增：

```text
back/app/zp_access/
    contracts.py
    locator.py
    reader.py
    spectrum_store.py
    identification_store.py
    chromatogram_store.py
```

职责：

- 根据 dataset/run 定位 `.zp` 产物；
- 隐藏真实磁盘绝对路径；
- 给业务层提供窄接口；
- 把 `.zp` Reader 输出转换成 Viewer 当前 API 需要的结构。

业务层只依赖接口：

```python
class SpectrumStore:
    def get_spectrum(dataset_id: int, run_id: int, scan_number: int) -> dict: ...
    def list_scan_index(dataset_id: int, run_id: int, offset: int, limit: int) -> dict: ...

class ChromatogramStore:
    def get_chromatogram(dataset_id: int, run_id: int, kind: str) -> dict: ...

class IdentificationStore:
    def get_match(match_id: int) -> dict: ...
    def list_matches(dataset_id: int, filters: dict) -> dict: ...
```

禁止：

- API 层直接解析 `.zp` 字节；
- 前端知道 `.zp` 文件路径；
- 业务页面依赖 viewer-two 内部类名；
- 一次性读取全部扫描或全部 Extension 后再分页。

## 4. 建议数据库记录

第一阶段不要求重构全部导入表，但需要至少新增 ZP 产物记录和转换任务记录。

### 4.1 `zp_conversion_jobs`

建议字段：

| 字段 | 含义 |
|---|---|
| `job_id` | 转换任务 ID |
| `dataset_slug` | 目标数据集 slug |
| `status` | queued/running/success/failed/cancelled |
| `stage` | inspect/convert/write/validate/commit |
| `progress` | 0-100 |
| `input_root` | 内部保存的来源根路径，不直接返回前端 |
| `zp_temp_path` | 半成品路径 |
| `zp_final_path` | 最终路径 |
| `worker_pid` | 当前 Worker 进程 |
| `format_version` | ZP 格式版本 |
| `viewer_two_version` | 转换器版本或源码 hash |
| `input_bytes` | 输入大小 |
| `output_bytes` | 输出大小 |
| `output_sha256` | `.zp` 文件 SHA-256 |
| `validation_mode` | quick/deep/integrated |
| `validation_certificate_path` | 校验证书路径 |
| `error_code` / `error_message` | 稳定错误信息 |
| `created_at` / `updated_at` / `finished_at` | 时间戳 |

### 4.2 `dataset_zp_assets`

建议字段：

| 字段 | 含义 |
|---|---|
| `dataset_id` | Viewer 数据集 |
| `run_id` | 可为空；多 run 时定位具体 run |
| `zp_path` | 内部绝对路径，不返回前端 |
| `format_version` | ZP 版本 |
| `source_fingerprint` | 来源 manifest 指纹 |
| `output_sha256` | ZP 文件 hash |
| `status` | active/deleted/stale |
| `capabilities` | spectra、bottom_up、top_down、chromatogram 等能力 |

## 5. API 建议

第一阶段新增管理型 API，不改现有科学展示 API：

```text
POST   /api/v1/zp-conversions
GET    /api/v1/zp-conversions/{job_id}
POST   /api/v1/zp-conversions/{job_id}/cancel
GET    /api/v1/datasets/{dataset_id}/zp-status
```

现有展示 API 后续只在服务层切换数据源：

```text
GET /api/v1/datasets/{dataset_id}/runs/{run_id}/spectra/{scan_number}
GET /api/v1/datasets/{dataset_id}/runs/{run_id}/scan-index
GET /api/v1/datasets/{dataset_id}/runs/{run_id}/chromatogram
```

这些响应结构应保持不变。前端不需要知道数据来自 mzML、数据库还是 `.zp`。

## 6. Worker 调用 viewer-two 的边界

Viewer 只能调用固定配置的 Worker 入口，例如：

```text
ZP_WORKER_PYTHON=/opt/viewer-two-venv/bin/python
ZP_WORKER_MODULE=binary_layer.service
ZP_OUTPUT_ROOT=/data/viewer-zp
ZP_TEMP_ROOT=/data/viewer-zp/.tmp
```

这些只能由管理员配置，不能来自用户请求或 Agent。

Worker 输入只允许：

- 已解析且受信任的数据集根；
- 目标 dataset/job 标识；
- 固定格式版本；
- 固定线程数和内存预算；
- 由 Viewer 后端生成的输出路径。

Worker 输出只允许：

- 结构化 JSON 进度事件；
- 最终 `.zp` 路径；
- 校验证书；
- 稳定错误码。

## 7. 取消与失败处理

取消不能只改数据库状态，必须终止 Worker 进程。

建议流程：

```text
用户点击取消
  -> API 标记 cancelling
  -> process_control 发送 terminate 给进程组
  -> 等待短暂宽限期
  -> 未退出则 kill 进程树
  -> 删除 .partial.zp 和临时目录
  -> 任务状态改 cancelled
```

失败处理：

- `.partial.zp` 不得暴露给 Viewer；
- 最终提交必须是原子 rename / replace；
- 失败后清理临时目录；
- 已成功旧版本 `.zp` 不被覆盖；
- 错误信息不包含服务器绝对路径、命令行、环境变量和 stdout/stderr 原文。

## 8. 安全要求

第一阶段必须满足：

- 输入路径必须在 `DATA_ROOT` 或管理员配置的允许根下；
- 输出 `.zp` 只能在 `ZP_OUTPUT_ROOT`；
- API 不返回 `source_root`、RAW、mzML、`.zp` 的绝对路径；
- 禁止 `.zp` 和原始文件下载；
- Worker 进程设置 CPU、内存、时间限制；
- 单任务默认最多 32GB；
- 同时转换任务数默认 1；
- 记录任务审计日志；
- 删除数据集时要标记/清理对应 `.zp` 产物。

## 9. 分阶段实施顺序

### 阶段 A：只做基础设施

- 增加 `zp_conversion` 模块；
- 增加任务表和产物表；
- 增加固定路径解析和安全校验；
- 用 fake Worker 跑通创建、查询、取消、失败清理。

验收：

- 单元测试覆盖状态流转；
- 取消会调用进程终止逻辑；
- 非允许根路径被拒绝；
- API 不返回绝对路径。

### 阶段 B：接 viewer-two Worker

- 在独立环境安装 viewer-two；
- 后端只调用固定 Worker；
- 转换完成后写入 `dataset_zp_assets`；
- 转换失败不影响 Web 服务。

验收：

- 小样本转换成功；
- PyArrow 24 环境无冲突；
- 取消真实转换能终止进程；
- 半成品不会出现在最终目录。

### 阶段 C：接 `zp_access`

- 增加 `zp_access` 定位和 Reader 包装；
- 为谱图 API 增加数据源选择；
- ZP 数据集优先读 `.zp`，没有 ZP 继续走现有 mzML/DB 路径；
- 响应结构保持兼容。

验收：

- 同一谱图从 mzML 和 ZP 返回一致关键字段；
- scan-index 支持分页；
- chromatogram 不一次性返回超大数组；
- Bottom-Up / Top-Down 页面不需要重写。

### 阶段 D：内部试点

- 功能开关开启给受信任数据；
- 记录性能、失败原因、输出大小；
- 不对外宣称 60 秒目标达成。

## 10. 不在本阶段做的事

- 不直接把 viewer-two 装进 Viewer Web 进程执行转换；
- 不删除原始 RAW/mzML；
- 不开放 `.zp` 下载；
- 不让前端解析 `.zp`；
- 不承诺 10GB / 60 秒；
- 不引入 Docker，因为当前服务器内部不能再使用 Docker。

## 11. 下一步代码实施建议

下一步如果开始写 Viewer 代码，建议先做阶段 A：

1. 新增 `back/app/zp_conversion/contracts.py`；
2. 新增 `back/app/zp_conversion/paths.py`；
3. 新增 `back/app/zp_conversion/repository.py`；
4. 新增 fake Worker runner；
5. 新增 `back/tests/test_zp_conversion_worker.py`；
6. 暂不调用真实 viewer-two。

这样可以先把 Viewer 的任务、安全、取消、清理边界做稳，再接真实转换器。
