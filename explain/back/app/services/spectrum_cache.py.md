# `back/app/services/spectrum_cache.py` 逐行解释

> 来源文件：`back/app/services/spectrum_cache.py`

## L1-L9（模块定位）

- 这是“磁盘谱图文件”的读取缓存层（MS1/MS2）。
- 谱图文件仍在磁盘（TopFD `spectrum*.js`），不入库。
- 解析根目录的优先级：
  1. DB 里 `datasets.source_root`（导入时写入的绝对路径）
  2. `DATA_ROOT/<slug_dir>`（fallback，方便迁移机器/盘符后仍可用）

## L11-L20（导入）

- `re`：用于把 slug 规整成安全目录名
- `lru_cache`：对单个谱图文件读取结果做 LRU 缓存（减少重复 IO）
- `Path`：路径处理
- `settings`：拿 `resolved_data_root`
- `load_js_object`：解析 `.js` 文件内容成 Python dict

## L22-L23：`SpectrumNotFoundError`

- 自定义异常类型：
  - 语义：请求的谱图文件在磁盘不存在
  - 上层 API（`api/v1/spectra.py`）会把它转换为 HTTP 404

## L26-L28：`_slug_dir_name(slug)`

- 把 slug 转成可用作文件夹名的字符串：
  - 允许字符集：`[A-Za-z0-9._-]`
  - 其它字符都替换为 `_`
  - 去掉首尾 `._-`
  - 空则返回 `"dataset"`
- 与导入服务 `import_jobs.py::_slug_dir_name` 保持一致，确保 fallback 目录命名一致。

## L31-L43：`_candidate_roots(slug, source_root)`

- 生成“候选数据集根目录列表”：
  - 如果 `source_root` 给了：
    - 若不是绝对路径：当作相对 `DATA_ROOT` 的路径
    - 若是绝对路径：直接 resolve
  - 再加入 fallback：`DATA_ROOT/_slug_dir_name(slug)`
  - 去重（避免两者相同）

## L46-L52：`_load_spectrum(abs_path)`

- `@lru_cache(maxsize=256)`：缓存 256 个谱图文件的解析结果
- 若文件不存在：抛 `SpectrumNotFoundError`
- 存在：`load_js_object(path)` 解析 `.js` 返回 dict

## L54-L63：`_resolve_spectrum(...)`

- 构造相对路径：`topfd/<sub>/spectrum{spec_id}.js`
- 在所有候选 root 下查找：
  - 找到第一个存在的文件就返回
  - 若都不存在：返回“第一个候选 root 拼出来的路径”（即便不存在）
    - 这样报错信息会指向“规范路径”，排查更直观

## L65-L72：`get_ms1_spectrum` / `get_ms2_spectrum`

- 分别解析 `ms1_json` 与 `ms2_json` 子目录
- 解析路径后交给 `_load_spectrum`（LRU 缓存 + 文件不存在异常）

## L75-L76：`clear_cache()`

- 清空 LRU 缓存（调试/排障用；线上一般不需要）

