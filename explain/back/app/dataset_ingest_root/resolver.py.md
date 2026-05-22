# `back/app/dataset_ingest_root/resolver.py` 逐行解释

> 来源文件：`back/app/dataset_ingest_root/resolver.py`
> 模块职责：在用户选择的路径下定位唯一的 TopPIC HTML 树或 PrSM bundle 根目录。

## L8-L15（`has_dataset_layout`）

- 判定目录是否像数据集根：存在 `toppic_prsm_cutoff/`、`topfd/`、`toppic_proteoform_cutoff/` 或 `data/` 之一。

## L18-L38（`find_ingest_root`）

- 若 `extract_dir` 本身匹配布局，直接返回。
- 否则在**直接子目录**中找匹配项：
  - 恰好 1 个 → 返回该子目录（兼容外层 wrapper 文件夹）。
  - 0 个 → `ValueError` 提示找不到 TopPIC 树。
  - 多个 → `ValueError` 要求用户只保留一个数据集文件夹。

## L41-L48（`resolve_ingest_root`）

- 对用户输入做 `expanduser().resolve()`，校验存在且为目录，再调用 `find_ingest_root`。

## 与相邻模块的耦合

- **import_planner.detectors**：布局细节判定与 PrSM 文件存在性在 planner 层继续细化。
- **测试**：`test_dataset_ingest_root.py` 覆盖根目录、单层嵌套、多匹配错误。
