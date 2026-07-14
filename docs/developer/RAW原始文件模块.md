# RawFile

## 1.模块定位

RawFile 模块负责 Thermo RAW 文件发现、RAW 到 mzML 转换、converted mzML 校验，以及 RAW-only 和 mzML-only 导入链路的衔接。当前谱图读取不直接读取 RAW，而是统一读取 uncompressed indexed mzML。

## 2.核心职责

* 发现导入目录中的 `.raw` 文件。
* 查找 ThermoRawFileParser 外部可执行文件。
* 对需要转换的 RAW 文件调用转换器。
* 校验 converted mzML 或 same-stem mzML 是否为 uncompressed indexed mzML。
* 将 RAW path、mzML path 和 raw conversion metadata 交给导入链路写入 `runs.run_metadata`。

## 3.关键目录和文件

* `back\app\raw_conversion\contracts.py`：RAW 转换请求、结果、批处理状态和 vendor 常量。
* `back\app\raw_conversion\discovery.py`：RAW 文件和 same-stem mzML 候选发现。
* `back\app\raw_conversion\tool_discovery.py`：ThermoRawFileParser 查找逻辑。
* `back\app\raw_conversion\thermo_raw_file_parser.py`：ThermoRawFileParser 子进程适配和 mzML 校验。
* `back\app\raw_conversion\service.py`：RAW 转换批处理服务。
* `back\app\ingest\mzml_only_adapter.py`：mzML-only 和 RAW 转换后 mzML 的导入 adapter。
* `back\app\core\config.py`：RAW 转换配置项。
* `back\.env.example`：RAW 转换环境变量示例。

## 4.核心数据流

1. import planner 检测到 `.raw` 文件并标记 `requires_raw_conversion`。
2. `convert_raw_files_for_import` 调用 discovery 查找 RAW 和 same-stem mzML。
3. 如果存在 same-stem mzML 且未强制转换，则先调用 indexed 校验。
4. 如果需要转换，则通过 `resolve_thermo_raw_file_parser_exe` 查找 converter。
5. `run_thermo_raw_file_parser` 执行转换并记录 stdout/stderr log。
6. `validate_converted_mzml` 校验输出为 uncompressed indexed mzML。
7. 导入 adapter 将 converted mzML 当作 mzML 数据源写入 `runs`。
8. 后续谱图读取统一通过 mzML scan reader。

## 5.关键API或关键组件

RawFile 没有独立 HTTP API，通过 `POST /api/v1/imports` 触发。关键函数包括：

* `collect_raw_files`
* `discover_raw_file_candidates`
* `resolve_thermo_raw_file_parser_exe`
* `run_thermo_raw_file_parser`
* `validate_existing_mzml`
* `convert_raw_files_for_import`

关键配置包括：

* `THERMO_RAW_FILE_PARSER_EXE`
* `RAW_CONVERSION_TIMEOUT_SECONDS`
* `RAW_CONVERSION_OUTPUT_DIR`
* `RAW_CONVERSION_FORCE`

## 6.和其他模块的关系

RawFile 被 Import 调用，输出 mzML 文件路径和 conversion metadata。SpectrumDataAccess 只读取 mzML，不读取 RAW。DerivedDataIndex 基于 converted mzML 生成 scan index 和 chromatogram summary。

参见：`谱图数据访问.md`、`数据导入模块.md`。

## 7.扩展和维护建议

新增厂商 RAW 支持时应新增 vendor-specific conversion adapter，并扩展 planner/vendor detection，不要把所有 RAW 逻辑写入 Thermo adapter。same-stem reuse、输出校验、metadata 写入应保持统一契约。不要绕过 indexed mzML 校验直接进入谱图读取链路。

相关测试入口以 `测试模块.md` 的完整分层为准；本模块重点参考 `back\tests\test_import_planner_raw.py`、`back\tests\test_import_jobs_raw_conversion.py`、`back\tests\test_raw_conversion_thermo.py`、`back\tests\test_raw_mzml_mapping.py`。

## 8.当前限制和注意事项

* 当前仅确认 Thermo RAW 转换支持，不要写成所有厂商 RAW 都支持。
* RAW 不直接读取，统一转换成 uncompressed indexed mzML 后读取。
* same-stem mzML 可以复用，但必须通过 `indexListOffset` 等 indexed 校验。
* gzip mzML 不支持 indexed random access 和 scan index。
* ThermoRawFileParser 是外部可执行文件；路径和平台环境需要单独配置或放在默认工具目录。
## 9.可复用入口

RAW conversion contracts：

* `back\app\raw_conversion\contracts.py::RawFileCandidate`
* `back\app\raw_conversion\contracts.py::RawConversionRequest`
* `back\app\raw_conversion\contracts.py::RawConversionResult`
* `back\app\raw_conversion\contracts.py::RawConversionBatch`

Discovery 和 tool discovery：

* `back\app\raw_conversion\discovery.py::collect_raw_files`
* `back\app\raw_conversion\discovery.py::expected_converted_mzml_path`
* `back\app\raw_conversion\discovery.py::find_existing_mzml_for_raw`
* `back\app\raw_conversion\discovery.py::discover_raw_file_candidates`
* `back\app\raw_conversion\tool_discovery.py::resolve_thermo_raw_file_parser_exe`
* `back\app\raw_conversion\tool_discovery.py::get_default_thermo_raw_file_parser_candidates`

Thermo adapter 和 service：

* `back\app\raw_conversion\thermo_raw_file_parser.py::build_thermo_raw_file_parser_command`
* `back\app\raw_conversion\thermo_raw_file_parser.py::validate_converted_mzml`
* `back\app\raw_conversion\thermo_raw_file_parser.py::validate_existing_mzml`
* `back\app\raw_conversion\thermo_raw_file_parser.py::run_thermo_raw_file_parser`
* `back\app\raw_conversion\service.py::convert_raw_files_for_import`
* `back\app\raw_conversion\errors.py::RawConversionError`
* `back\app\ingest\mzml_only_adapter.py::ingest_mzml_only`

import planner 入口：

* `back\app\services\import_planner\planner.py::plan_zip_ingest`
* `back\app\services\import_planner\detectors.py::detect_spectra_source`
* `back\app\services\import_planner\detectors.py::detect_bu_spectra_source`
* `back\app\services\import_planner\detectors.py::has_mzml_or_raw_spectra`

## 10.调用链

RAW 导入链路：

1. `plan_zip_ingest` 调 `collect_raw_files` 识别 RAW，并在 `ImportPlan.requires_raw_conversion` 标记是否需要转换。
2. `back\app\services\import_jobs.py::run_path_import_job` 发现 `plan.requires_raw_conversion` 后进入 `raw_conversion` stage。
3. `run_path_import_job` 调 `convert_raw_files_for_import`，传入 `source_root`、`output_dir`、timeout、force 和 progress callback。
4. `convert_raw_files_for_import` 调 `discover_raw_file_candidates` 找 RAW 和 same-stem mzML。
5. same-stem mzML 先走 `validate_existing_mzml`；未命中或 force 时走 converter。
6. `resolve_thermo_raw_file_parser_exe` 解析 ThermoRawFileParser executable。
7. `run_thermo_raw_file_parser` 调外部工具，并用 `validate_converted_mzml` 校验输出是 indexed mzML。
8. `RawConversionBatch.raw_to_mzml` 和 `RawConversionResult.metadata()` 进入 adapter/run metadata 补写链路。
9. 后续谱图读取只读取 mzML，不直接读取 RAW。

RAW-only spectra-only 链路：

1. planner 判断只有 RAW 时，导入仍先转换。
2. 转换结果作为 `extra_mzml_roots` 传入 mzML-only adapter。
3. `ingest_mzml_only` 写 `datasets` 和 `runs`。
4. 后续 SpectrumDataAccess 读取 converted mzML。

## 11.新增功能接入方式

新增厂商 RAW 支持 checklist：

1. 新增 vendor contract 或复用 `RawFileCandidate`、`RawConversionRequest`、`RawConversionResult`、`RawConversionBatch`。
2. 在 discovery 层增加厂商识别规则，不把厂商判断写进 `import_jobs.py`。
3. 新增 tool resolver，类似 `resolve_thermo_raw_file_parser_exe`。
4. 新增 converter adapter，返回 `RawConversionResult`。
5. 接入 `convert_raw_files_for_import` 的批量编排。
6. 接入 `plan_zip_ingest` 和 detector，让 `requires_raw_conversion` 正确表达。
7. 输出必须保持 uncompressed indexed mzML，至少通过 `validate_converted_mzml` 等价校验。
8. 补后端测试，例如 discovery、converter adapter、import job RAW stage。
9. 补本文档，明确支持范围，不把所有厂商 RAW 写成已支持。

调整 same-stem mzML 复用：

1. 复用规则先看 `find_existing_mzml_for_raw`。
2. 跳过转换前必须走 `validate_existing_mzml`。
3. 不允许只凭同名文件存在就跳过转换。

## 12.内部实现边界

以下为内部实现或低层 helper，不建议跨模块直接调用：

* `back\app\raw_conversion\discovery.py::_same_stem_mzml_candidates`
* `back\app\raw_conversion\service.py::_log_paths`
* `back\app\raw_conversion\service.py::_skipped_result`
* `back\app\raw_conversion\thermo_raw_file_parser.py::_now_iso`
* `back\app\raw_conversion\thermo_raw_file_parser.py::_find_embedded_index_markers`
* `back\app\raw_conversion\thermo_raw_file_parser.py::_format_validation_context`
* `back\app\raw_conversion\thermo_raw_file_parser.py::locate_output_mzml` 是 Thermo output 定位 helper，不是导入层入口。
* `back\app\raw_conversion\tool_discovery.py::_repo_root`、`_expand_configured_path`、`_default_missing_message`
* `back\app\services\import_jobs.py::_raw_conversion_output_dir`、`_raw_conversion_progress_handler`、`_raw_conversion_error_detail`、`_raw_conversion_metadata_by_mzml_key`、`_dataset_raw_conversion_summary`

## 13.不要绕过的层

* 不要在 `back\app\services\import_jobs.py` 里直接拼 converter 命令；命令构建属于 `thermo_raw_file_parser.py::build_thermo_raw_file_parser_command`。
* 不要绕过 `validate_existing_mzml` 或 `validate_converted_mzml`。
* 不要把 RAW 直接交给谱图读取层；谱图读取层只读 mzML。
* 不要把所有厂商 RAW 都写成已支持；当前确认的是 Thermo RAW conversion 路径。
* 不要把 same-stem mzML 复用写成存在性检查；必须通过 indexed mzML 校验。
* 不要在 planner 或 detector 中调用外部 converter。

## 14.常见修改场景

调整 ThermoRawFileParser 参数：

1. 修改 `build_thermo_raw_file_parser_command`。
2. 保持输出 uncompressed indexed mzML。
3. 同步 `test_raw_conversion_thermo.py` 中命令断言。

调整 converter 查找顺序：

1. 修改 `resolve_thermo_raw_file_parser_exe` 或 `get_default_thermo_raw_file_parser_candidates`。
2. 不让 mzML-only/no-RAW 路径提前解析 converter。
3. 对照 `test_raw_converter_discovery.py` 和 `test_raw_conversion_discovery.py`。

调整 RAW 导入 job 阶段：

1. 修改 `run_path_import_job` 中 `raw_conversion` stage 编排。
2. 保持 `convert_raw_files_for_import` 为批量入口。
3. 保持 `raw_conversion` metadata 写入 `runs.run_metadata`。

## 15.相关测试

本节列出开发时应参考或补充的测试入口；当前任务不运行这些测试。

* planner RAW：`back\tests\test_import_planner_raw.py`。
* RAW conversion discovery/service：`back\tests\test_raw_conversion_discovery.py`。
* Thermo adapter：`back\tests\test_raw_conversion_thermo.py`。
* converter discovery：`back\tests\test_raw_converter_discovery.py`。
* import job RAW stage：`back\tests\test_import_jobs_raw_conversion.py`。
* RAW/mzML mapping：`back\tests\test_raw_mzml_mapping.py`。
* mzML-only adapter：`back\tests\test_mzml_only_adapter.py`。
