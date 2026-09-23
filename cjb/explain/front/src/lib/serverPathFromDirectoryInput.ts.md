# `front/src/lib/serverPathFromDirectoryInput.ts` 逐行解释

> 来源文件：`front/src/lib/serverPathFromDirectoryInput.ts`
> 模块职责：将浏览器目录选择结果映射为服务端可用的绝对路径字符串，并生成默认 slug。

## L6（`FileWithNativePath`）

- 扩展 `File`：部分桌面宿主（Electron 等）在 `File.path` 暴露绝对路径；标准浏览器通常没有。

## L9-L23（`commonParentDirectory`）

- 多文件 path 归一化为 `/` 后求最长公共前缀，再截到上一级目录（不含部分文件名段）。

## L25-L33（`inferServerPathFromDirectoryFileList`）

- 要求每个 File 都有 `path`；取公共父目录并按首个样本还原 `\` 或 `/` 分隔符。

## L36-L59（`basenamePath` / `slugifyFolderName`）

- `basenamePath`：路径最后一段，供默认 slug/展示名。
- `slugifyFolderName`：Unicode 友好 slug（NFKD、去音标、非字母数字 → `_`）。

## 与相邻模块的耦合

- **DatasetsPage.tsx**：目录 input 或 native picker 后填充 `sourcePath`、`slug`、`dsName`。
