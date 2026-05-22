# `back/app/spectrum_memory/mzml_spectrum_extract.py` 逐行解释

> 来源文件：`back/app/spectrum_memory/mzml_spectrum_extract.py`
> 模块职责：单次读取 mzML 文件，解析为 scan → spectrum dict（无全局缓存）。

## L13-L18（`parse_scan`）

- 从 native id 正则 `scan=(\d+)` 提取 scan 号。

## L21-L29（`rt_seconds`）

- 从 pyteomics spec 的 scanList 取 retention time；minute 单位转秒。

## L32-L63（`extract_precursor`）

- MS2 前体：parent_scan、isolation window、selected ion m/z/charge。

## L66-L77（`extract_spectrum`）

- 输出前端/API 消费的 dict：`scan`、`native_id`、`ms_level`、`rt_seconds`、`mz[]`、`intensity[]`、`precursor`。

## L80-L100（`load_mzml_path_to_scan_map`）

- 支持 plain `.mzML` 与 `.mzml.gz`；pyteomics `mzml.read` 流式遍历；跳过无 scan 的条目。

## L103-L114（`approximate_scan_map_bytes`）

- 用 `sys.getsizeof` + 列表长度启发式估算内存，供 bundle accounting。

## 与相邻模块的耦合

- **mzml_dataset_bundle.py**：`DatasetMzmlBundle.load` 调用 `load_mzml_path_to_scan_map`。
- **与 mzml_store.py 区别**：本模块无 LRU、按数据集 bundle 组织；旧 `mzml_store` 仍可能被 legacy 路由使用。
