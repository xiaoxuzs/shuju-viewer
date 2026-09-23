# `back/app/services/native_folder_dialog.py` 逐行解释

> 来源文件：`back/app/services/native_folder_dialog.py`
> 模块职责：在 API 主机上弹出原生文件夹选择对话框（本地开发：浏览器与 FastAPI 同机时使用）。

## L10-L11（`NativeFolderDialogError`）

- 无显示环境或 toolkit 不可用时抛出（headless 服务器）。

## L14-L40（`pick_folder_native`）

- 优先 `_try_tk_folder`（tkinter `filedialog.askdirectory`）。
- macOS fallback：`osascript choose folder`。
- Linux fallback：`zenity --file-selection --directory`。
- 返回 `(absolute_path, cancelled)`；取消时 path 为 None。

## L43-L71（`_try_tk_folder`）

- 创建隐藏 Tk 根窗口，`mustexist=True` 选目录；TclError 转 `NativeFolderDialogError`。

## L74-L101（平台 fallback）

- `_ask_mac_osascript` / `_ask_zenity`：subprocess 调用，超时 3600s。

## 与相邻模块的耦合

- **imports.py**：`POST /imports/pick-folder` 受 `IMPORT_NATIVE_FOLDER_PICKER` 与 loopback 限制保护。
- **DatasetsPage.tsx**：`pickImportFolder()` 调用该 API 填充 `sourcePath`。
