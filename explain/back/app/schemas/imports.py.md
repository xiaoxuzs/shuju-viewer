# `back/app/schemas/imports.py` 逐行解释

> 来源文件：`back/app/schemas/imports.py`
> 模块职责：路径导入相关 Pydantic 请求/响应模型。

## L10-L16（`ImportEnqueueIn`）

- `source_path`：服务端可见的文件夹绝对路径（或 `~` 展开）。
- `slug` / `name`：数据集 URL 标识与展示名。
- `description`：可选说明，导入成功后写入 `datasets.description`。

## L19-L51（`ImportJobOut`）

- 轮询响应：`status`（queued/running/success/failed）、`progress` 0–100。
- `stage` 机器码：`queued | fingerprint | init | proteins | matches | finalize | success | failed`（**无 extract 阶段**）。
- `stage_label` 中文标签；`stage_detail` 自由格式进度行。

## L54-L58（`ImportJobCreatedOut`）

- POST `/imports` 立即返回：`job_id` + `status="queued"`。

## L61-L65（`ImportPickFolderOut`）

- 原生对话框结果：`path` 或 `cancelled=true`。

## 与相邻模块的耦合

- **imports.py** 路由绑定上述模型。
- **front/src/api/types.ts** 镜像 TypeScript 接口。
