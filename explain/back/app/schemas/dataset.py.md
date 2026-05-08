# `back/app/schemas/dataset.py` 逐行解释

> 来源文件：`back/app/schemas/dataset.py`

## L1（模块定位）

- 定义 dataset 与 cutoff 的 API 输出模型，以及删除数据集的返回模型。

## L3-L8（导入）

- `datetime`：created_at/updated_at
- `BaseModel/ConfigDict`：Pydantic 模型与配置

## L10-L21：`CutoffOut`

- `id`：合成稳定整数（由后端 compat 层决定，前端依赖）
- `kind`：`"prsm"` / `"proteoform"` 等
- `label`：展示用字符串
- 三个计数：protein/proteoform/prsm

## L23-L41：`DatasetOut`

- 用于数据集列表卡片与详情页
- 字段：
  - `id`：dataset_id（数据库主键）
  - `slug`：URL/唯一标识
  - `name/description`
  - `source_path`：通常是 `datasets.source_root`
  - `capabilities`：JSON（例如 `{"spectra_source":"mzml_memory"}`）
  - `created_at`
  - `updated_at`：universal schema 没有该列，所以后端通常返回 None，但模型保留以兼容旧前端形状
  - `cutoffs`：嵌套 `CutoffOut[]`

## L43-L53：`DatasetDeletedOut`

- `DELETE /datasets/{slug}` 的结果：
  - `deleted_db`：数据库行是否删除成功（cascade 同步清理子表）
  - `deleted_disk`：磁盘目录是否删除成功
  - `folder`：尝试删除的主目录路径
  - `folder_existed`：该目录在删除前是否存在

