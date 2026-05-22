# `back/tests/test_incoming_path_relocate.py` 逐行解释

> 来源文件：`back/tests/test_incoming_path_relocate.py`
> 模块职责：验证 `.incoming` → final 目录 rename 后的路径映射与 stale 路径修复。

## 测试用例

| 测试 | 行为 |
|------|------|
| `test_relocate_incoming_root_relative` | `ds.incoming/sub/a.mzML` 映射到 `ds/sub/a.mzML` |
| `test_try_fix_stale_incoming_absolute_path` | stale 路径 `pkg.incoming/b.mzML` 解析到 `pkg/b.mzML` |

## 与相邻模块的耦合

- **import_jobs** finalize 阶段写入 DB 的路径依赖 `relocate_incoming_root`。
- **spectrum_memory_wiring** 读盘前用 `try_fix_stale_incoming_absolute_path`。
