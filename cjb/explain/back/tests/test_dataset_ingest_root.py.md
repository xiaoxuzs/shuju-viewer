# `back/tests/test_dataset_ingest_root.py` 逐行解释

> 来源文件：`back/tests/test_dataset_ingest_root.py`
> 模块职责：验证 ingest 根路径解析的三种典型场景。

## 测试用例

| 测试 | 场景 |
|------|------|
| `test_resolve_when_root_is_layout` | 选中路径本身含 `topfd/` → 返回自身 |
| `test_resolve_nested_single_child` | 外层 wrapper + 唯一子目录含 `toppic_prsm_cutoff/` → 返回内层 |
| `test_resolve_multiple_matches_errors` | 两个子目录均像数据集 → `ValueError` "Multiple" |

## 与相邻模块的耦合

- 被测：`app.dataset_ingest_root.resolve_ingest_root` / `find_ingest_root`。
- 与 **import_planner** 配合：resolver 只找根，planner 再判 PrSM 明细与谱图模式。
