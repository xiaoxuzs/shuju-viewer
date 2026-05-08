# `back/app/services/mzml_mapping.py` 逐行解释

> 来源文件：`back/app/services/mzml_mapping.py`

## L1-L9（模块定位）

- 该模块在**导入期**运行（ZIP 解压之后）用于构建 strict 的 run ↔ mzML 映射。
- 关键约束：**不得读取 mzML 内容**（只做文件发现与命名匹配），真正加载 mzML 发生在运行期第一次谱图请求（见 `mzml_store.py`）。
- 映射双方：
  - PrSM 详情文件中 `ms_header.spectrum_file_name`（“期望的谱文件名”）
  - ZIP 中实际存在的 `*.mzML/*.mzml[.gz]` 文件

## L11-L16（导入）

- `dataclass`：返回结果结构体
- `Path`：文件遍历与路径处理
- `load_js_object`：解析 `prsm*.js` 提取 `spectrum_file_name`

## L19-L26：`MzmlMappingResult`

- `mapping`：规范化 key → 唯一 mzML 路径
- `mzml_files`：发现到的 mzML 文件列表（用于诊断）
- `spectrum_file_names`：从 prsm*.js 提取的原始 file name 集合（用于诊断）

## L28-L29：`MzmlMappingError`

- 映射失败时抛出的异常类型（导入服务捕获后会让导入任务失败）

## L32-L49：`collect_mzml_files(extract_root)`

- 在解压根目录下递归搜集：
  - `*.mzML` / `*.mzml`
  - `*.mzML.gz` / `*.mzml.gz`
- Windows 虽然大小写不敏感，但这里同时保留多种 pattern 以保证跨平台
- 通过 `resolve()` 去重，并按路径排序，保证稳定性

## L51-L65：`normalize_spectrum_file_name(value)`

- 将任意 spectrum_file_name 规范化成用于匹配的 key：
  - 取 basename（去掉路径）
  - 去掉末尾一层 `.gz`（如果有）
  - 去掉末尾一层 `.mzml`（大小写不敏感）
  - 全部转小写
- 目的：抵抗来源软件写出的路径差异、大小写差异、是否带扩展名差异

## L68-L88：`extract_spectrum_file_names_from_prsms(prsms_dir)`

- 在某个目录下找 `prsm*.js`：
  - 找不到目录/找不到文件 → 抛 `MzmlMappingError`
- 对每个 `prsm*.js`：
  - `load_js_object(path)` 解析成 dict
  - 兼容三种根形状：
    - `doc["prsm"]`
    - `doc["prsm_data"]["prsm"]`
    - 或 doc 本身就是 prsm root
  - 读取 `ms.ms_header.spectrum_file_name`：
    - 缺失/空字符串 → 抛错误（这是 strict 映射的硬要求）
- 返回 set（去重后的原始 file name 集合）

## L91-L137：`build_one_to_one_mapping(spectrum_file_names, mzml_files)`

- 前置校验：
  - spectrum_file_names 为空 → 失败
  - mzml_files 为空 → 失败
- 先把 mzML 文件按 key 分桶：`mzml_by_key[key] -> [Path, ...]`
- 再遍历每个 raw spectrum_file_name：
  - 规范化 key
  - 查 hits：
    - 0 个 → missing
    - >1 个 → conflicts（同一个 key 匹配到多个 mzML，歧义）
    - 1 个 → 写入 out[key] = path
- 若有 missing/conflicts：
  - 组装可读错误信息（截断列表，避免异常太长）
  - 抛 `MzmlMappingError`
- 成功返回 `out`（key → path），这是后续写入 `runs.run_metadata.mzml_file_path` 的基础

## L140-L167：`build_mapping_from_extracted_dataset(ingest_root)`

- 先收集 mzML 文件列表
- 再尝试定位 `prsm*.js` 的目录候选：
  1. `toppic_prsm_cutoff/data_js/prsms`（TopPIC HTML 树）
  2. `data`（prsm bundle）
- 依次尝试 `extract_spectrum_file_names_from_prsms`：
  - 某个候选成功即停止
  - 失败则记录 last_error，继续尝试下一个
- 若两个都失败 → 抛 `MzmlMappingError`
- 成功则调用 `build_one_to_one_mapping` 并返回 `MzmlMappingResult`

