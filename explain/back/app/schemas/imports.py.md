# `back/app/schemas/imports.py` 逐行解释

> 来源文件：`back/app/schemas/imports.py`

## L1（模块定位）

- 定义导入任务（import job）相关的 API 响应模型：
  - `GET /imports/{job_id}` 用 `ImportJobOut`
  - `POST /imports` 用 `ImportJobCreatedOut`

## L3-L7（导入）

- `datetime`：created_at/updated_at
- `BaseModel/Field/ConfigDict`：Pydantic 模型定义与字段约束

## L10-L40：`ImportJobOut`

- `model_config = ConfigDict(from_attributes=True)`：
  - 允许从对象属性构造（本项目多为 dict 映射，但该配置无害）
- 字段含义：
  - `job_id`：轮询用 opaque id（UUID 字符串）
  - `status`：`queued|running|success|failed`（或未来扩展）
  - `message/error`：人类可读状态与错误
  - `dataset_slug`：任务目标 slug（成功后可用它跳转）
  - `progress`：0..100（100 只在 success）
  - `stage/stage_label/stage_detail`：阶段码、中文标签、细节行（进度条旁提示）
  - `created_at/updated_at`：用于排查任务状态与 TTL

## L42-L47：`ImportJobCreatedOut`

- `POST /imports` 刚 enqueue 后立即返回：
  - `job_id`
  - `status` 默认 `"queued"`

