# `back/app/services/incoming_path_relocate.py` 逐行解释

> 来源文件：`back/app/services/incoming_path_relocate.py`
> 模块职责：修正导入 finalize 前后路径中残留的 `.incoming` 段，保证磁盘路径与 DB 一致。

## L14-L35（`try_fix_stale_incoming_absolute_path`）

- 若路径已是存在的文件，直接 `resolve()` 返回。
- 否则遍历 path 各段：找到以 `.incoming` 结尾的段，去掉后缀重建路径；若重建路径存在则返回。
- 用于 legacy 行或 slash 不一致时，从 `pkg.incoming/foo.mzML` 找到 `pkg/foo.mzML`。

## L38-L49（`relocate_incoming_root`）

- 将 `path` 相对 `incoming_root` 的相对路径，映射到 `final_root` 下同名相对路径。
- 若 `path` 不在 `incoming_root` 子树内，原样返回 `str(path)`。
- import finalize 时批量改写 `runs.run_metadata.mzml_file_path` 等绝对路径。

## 与相邻模块的耦合

- **import_jobs.py**：atomic rename 成功后调用 `relocate_incoming_root` 更新路径字段。
- **spectrum_memory_wiring.py**：读盘前用 `try_fix_stale_incoming_absolute_path` 修正 stale 路径。
