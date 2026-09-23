# `back/app/fingerprint/dataset_metadata_fingerprint.py` 逐行解释

> 来源文件：`back/app/fingerprint/dataset_metadata_fingerprint.py`
> 模块职责：对 ingest 根目录做元数据 manifest MD5（相对路径|size|mtime），用于路径导入去重。

## 结构概览

| 符号 | 作用 |
|------|------|
| `MetadataFingerprintResult` | 返回 fingerprint hex、file_count、elapsed_seconds |
| `compute_dataset_metadata_fingerprint` | 递归 scandir → 排序 manifest → MD5 |

## L1-L19（常量与结果类型）

- **L1-L6**：docstring 说明与 demo 脚本语义一致；目标墙钟 ≤0.5s（基准见 `cs/`）。
- **L17-L18**：排除 `.DS_Store`、`Thumbs.db`、`manifest_fast.json` 及 `._*` AppleDouble 文件。
- **L21-L29**：`MetadataFingerprintResult`  frozen dataclass，三个字段分别供 DB 写入与日志。

## L32-L84（`compute_dataset_metadata_fingerprint`）

- **L49-L51**：`expanduser().resolve()` 并校验为目录。
- **L58-L75**：内部 `scan_dir` 用 `os.scandir`（不跟随符号链接）收集每文件一行 `rel|size|mtime`。
- **L71-L73**：可选 `on_progress` 回调，每 N 文件报告进度（导入 job 用于 UI 进度条）。
- **L77-L84**：manifest 行 lex 排序 → UTF-8 拼接 → MD5 hex 小写返回。

## 与相邻模块的耦合

- **import_jobs**：导入 phase `fingerprint` 调用本函数；冲突时查 `uq_datasets_source_dataset_fingerprint`。
- **不依赖**：FastAPI、SQLAlchemy、ingest 适配器（独立算法模块）。
