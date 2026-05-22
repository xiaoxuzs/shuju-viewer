# `front/src/pages/DatasetsPage.tsx` 逐行解释

> 来源文件：`front/src/pages/DatasetsPage.tsx`
> 模块职责：数据集列表、**路径导入**弹窗与轮询、删除确认。

## L1-L48（状态）

- React Query 拉取 `fetchDatasets`。
- 导入表单：`sourcePath`、`slug`、`dsName`、`description`（**非 ZIP 文件**）。
- `folderPickBusy` / `importBusy` 控制按钮与轮询期间 UI。

## L75-L103（`onBrowseFolder`）

- 调用 `pickImportFolder()`（API 主机原生对话框）。
- 成功时用 `basenamePath` + `slugifyFolderName` 预填 slug/名称。

## L105-L155（`runImport`）

- 校验 path/slug/name 非空。
- `enqueueImport({ source_path, slug, name, description })` → 获得 `job_id`。
- 循环 `fetchImportJob`（900ms 间隔）直到 success/failed。
- 成功：invalidate datasets 查询并关闭弹窗。
- 失败：展示 `job.error` 或结构化 duplicate fingerprint 详情。

## L157-L168（PageHeader）

- 按钮文案 **Import from folder**（非 ZIP）。

## 空状态（L186+）

- 提示路径导入或 universal CLI 命令示例。

## 与相邻模块的耦合

- **client.ts**：`enqueueImport`、`pickImportFolder`、`fetchImportJob`、`deleteDataset`。
- **serverPathFromDirectoryInput.ts**：slug 与路径辅助（若使用 directory input）。
