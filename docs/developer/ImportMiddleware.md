# ImportMiddleware

## 1.模块定位

ImportMiddleware 是本文档中的概念层，不是源码中的单独包名。它描述业务导入编排和底层文件解析之间的适配、标准化、调度和转换层，由 resolver、planner、detectors、adapter、raw_conversion、pfmb、mzml_mapping 等模块共同组成。

## 2.核心职责

* 从用户选择目录定位可导入的唯一 ingest root。
* 根据目录内容判断数据集 shape。
* 将 TopPIC、PrSM bundle、DIA-NN parquet、mzML-only、Thermo RAW-only 等外部格式统一写入 universal schema。
* 决定 spectra source，例如 TopFD JS、mzML-backed、Bruker TDF 或 mixed。
* 协调 RAW 转 mzML、PFMB sidecar 准备、mzML mapping 校验等旁路流程。

## 3.关键目录和文件

* `back\app\dataset_ingest_root\resolver.py`：解析用户选择目录中的唯一 ingest root。
* `back\app\services\import_planner\planner.py`：核心 planner，输出 import shape 和 RAW/mzML 需求。
* `back\app\services\import_planner\detectors.py`：TopPIC、DIA-NN、spectra-only、spectra source 检测。
* `back\app\services\import_planner\types.py`：`DatasetShape` 和 `ImportPlan` 数据结构。
* `back\app\ingest\universal_toppic_adapter.py`：TopPIC HTML 导入 adapter。
* `back\app\ingest\universal_prsm_js_adapter.py`：PrSM bundle 导入 adapter。
* `back\app\ingest\mzml_only_adapter.py`：mzML-only 和 RAW 转换后 mzML 导入 adapter。
* `back\app\ingest\bu\universal_diann_adapter.py`：DIA-NN BottomUp 导入 adapter。
* `back\app\raw_conversion`：Thermo RAW 转 mzML 适配层。
* `back\app\pfmb`：BU PFMB sidecar 读取、索引和准备。
* `back\app\services\mzml_mapping.py`：TopDown/PrSM 与 mzML 文件名的 strict mapping。

## 4.核心数据流

1. `resolve_ingest_root` 从用户目录中找出唯一可导入根。
2. `plan_zip_ingest` 是历史命名，当前实际处理 folder ingest，并检查 TopPIC、DIA-NN、PrSM bundle、mzML-only、RAW-only 等形态。
3. planner 输出 `ImportPlan`，包括 `shape`、`spectra_source`、`contains_raw`、`requires_raw_conversion`、`mzml_files`、`raw_files`。
4. 编排层根据 `requires_raw_conversion` 调用 `raw_conversion`。
5. 对 TD mzML-backed 数据，`mzml_mapping` 校验 PrSM headers 与 mzML 文件。
6. 对 BU DIA-NN 数据，adapter 读取 parquet、发现 run、准备 PFMB sidecar。
7. 对应 adapter 将外部格式写入 `datasets`、`runs`、`proteins`、`proteoforms`、`peptides`、`identification_matches` 等表。

## 5.技术实现点

planner 和 detector 负责格式识别，adapter 负责把 TopPIC、PrSM bundle、DIA-NN parquet、mzML-only 和 RAW 转换后的 mzML 写入 universal schema。DIA-NN parquet 读取依赖 `pyarrow.parquet`，RAW 转换依赖 ThermoRawFileParser 外部工具，PFMB 准备涉及 sidecar 发现、`index.json` 映射和 DB baked metadata。adapter 写库路径主要使用 SQLAlchemy `create_engine`、Session 或 `text` SQL。

## 6.关键API或关键组件

ImportMiddleware 没有独立 HTTP API。关键函数包括：

* `resolve_ingest_root`
* `plan_zip_ingest`
* `detect_spectra_source`
* `detect_bu_spectra_source`
* `ingest_universal_toppic`
* `ingest_universal_prsm_js`
* `ingest_mzml_only`
* `ingest_universal_diann`
* `prepare_bu_pfmb_sidecar`
* `build_mapping_from_extracted_dataset`

## 7.和其他模块的关系

ImportMiddleware 被 Import 调用，依赖 RawFile、PFMB、mzML mapping、DataModelStorage。它向 BottomUp、TopDown 和 spectra-only 提供统一入库结果。DerivedDataIndex 在 adapter 入库后由 Import 编排层触发。

参见：`Import.md`、`RawFile.md`、`BottomUp.md`、`TopDown.md`。

## 8.扩展和维护建议

新增格式时应新增 detector、planner 分支、独立 adapter 和对应测试。adapter 应负责格式到 universal schema 的映射，不应直接处理 HTTP 请求。planner 应只做识别和计划，不应读入大文件内容或写数据库。RAW、PFMB、mzML mapping 这类旁路能力应保持独立模块。

相关测试入口以 `Testing.md` 的完整分层为准；本模块重点参考 `back\tests\test_import_planner.py`、`back\tests\test_import_planner_raw.py`、`back\tests\test_raw_mzml_mapping.py`。

## 9.当前限制和注意事项

* `ImportMiddleware` 是文档概念层，当前源码没有同名单独包。
* `plan_zip_ingest` 是历史命名，当前实际处理 folder ingest。
* 失败回滚不是统一跨文件事务框架；导入失败后的文件系统状态不能写成强事务可回滚。
* 不同 adapter 的抽象层级不完全一致，TD route 和 adapter 内仍有较多业务逻辑。
* 当前未找到 MGF adapter。
* `DatasetShape.UNSUPPORTED` 是保留枚举；当前 `plan_zip_ingest` 未返回该 shape，未匹配布局时直接抛出 `ImportLayoutError`。

## 10.可复用入口

root resolver：

* `back\app\dataset_ingest_root\resolver.py::has_dataset_layout`
* `back\app\dataset_ingest_root\resolver.py::has_bu_diann_layout`
* `back\app\dataset_ingest_root\resolver.py::has_spectra_only_layout`
* `back\app\dataset_ingest_root\resolver.py::find_ingest_root`
* `back\app\dataset_ingest_root\resolver.py::resolve_ingest_root`

planner 和 detector：

* `back\app\services\import_planner\types.py::DatasetShape`
* `back\app\services\import_planner\types.py::ImportPlan`
* `back\app\services\import_planner\types.py::ImportLayoutError`
* `back\app\services\import_planner\planner.py::plan_zip_ingest`
* `back\app\services\import_planner\detectors.py::is_toppic_html_tree`
* `back\app\services\import_planner\detectors.py::detect_spectra_source`
* `back\app\services\import_planner\detectors.py::detect_bu_spectra_source`
* `back\app\services\import_planner\detectors.py::has_mzml_or_raw_spectra`

adapters：

* `back\app\ingest\universal_toppic_adapter.py::ingest_universal_toppic`
* `back\app\ingest\universal_toppic_adapter.py::assign_toppic_runs_from_prsm_headers`
* `back\app\ingest\universal_prsm_js_adapter.py::ingest_universal_prsm_js`
* `back\app\ingest\mzml_only_adapter.py::ingest_mzml_only`
* `back\app\ingest\bu\universal_diann_adapter.py::ingest_universal_diann`

BU ingest helpers：

* `back\app\ingest\bu\diann_parquet_reader.py::find_diann_report`
* `back\app\ingest\bu\diann_parquet_reader.py::inspect_report`
* `back\app\ingest\bu\diann_parquet_reader.py::iter_filtered_rows`
* `back\app\ingest\bu\run_discovery.py::discover_bu_runs`
* `back\app\ingest\bu\run_discovery.py::match_diann_runs_to_files`
* `back\app\ingest\bu\field_mapping.py::should_import_match`
* `back\app\ingest\bu\field_mapping.py::match_extra_metadata`
* `back\app\ingest\bu\field_mapping.py::peptide_metadata`
* `back\app\ingest\bu\field_mapping.py::protein_metadata`

旁路能力：

* `back\app\services\mzml_mapping.py::collect_mzml_files`
* `back\app\services\mzml_mapping.py::build_mapping_from_extracted_dataset`
* `back\app\services\mzml_mapping.py::build_one_to_one_mapping`
* `back\app\raw_conversion\discovery.py::collect_raw_files`
* `back\app\raw_conversion\service.py::convert_raw_files_for_import`
* `back\app\pfmb\sidecar_prepare.py::prepare_bu_pfmb_sidecar`
* `back\app\pfmb\locator.py::resolve_sidecar`

## 11.调用链

统一导入识别和调度链路：

1. `back\app\api\v1\imports.py::enqueue_import` 做路径和基本参数校验。
2. `back\app\dataset_ingest_root\resolver.py::resolve_ingest_root` 解析唯一 ingest root。
3. `back\app\services\import_jobs.py::run_path_import_job` 调用 `compute_dataset_metadata_fingerprint` 做重复识别。
4. `back\app\services\import_planner\planner.py::plan_zip_ingest` 读取目录特征，返回 `ImportPlan`。
5. `ImportPlan.shape` 当前由 `plan_zip_ingest` 返回 `DatasetShape.TOPPIC_HTML`、`PRSM_BUNDLE`、`DIANN_DIA` 或 `MZML_ONLY`；`DatasetShape` 中保留 `UNSUPPORTED` 枚举，但当前未作为正常 plan 返回。
6. `ImportPlan.contains_raw` 和 `ImportPlan.requires_raw_conversion` 决定是否进入 `raw_conversion`。
7. TD mzML-backed 数据通过 `back\app\services\mzml_mapping.py::build_mapping_from_extracted_dataset` 校验 PrSM headers 与 mzML 文件名。
8. BU DIA-NN 数据通过 `diann_parquet_reader` 读取 report，通过 `run_discovery` 匹配 mzML/Bruker TDF run，通过 `prepare_bu_pfmb_sidecar` 准备 PFMB sidecar。
9. adapter 写入 universal schema 后，`import_jobs.py` 补写 `datasets` 和 `runs` 的导入 metadata。

shape 到 adapter 的对应关系：

| `DatasetShape` | detector/planner 依据 | adapter 或后续入口 |
|---|---|---|
| `TOPPIC_HTML` | `is_toppic_html_tree`、TopPIC HTML/JS 目录 | `ingest_universal_toppic`，必要时 `assign_toppic_runs_from_prsm_headers` |
| `PRSM_BUNDLE` | `ingest_root_has_supported_prsm_files`、PrSM 文件目录 | `ingest_universal_prsm_js` |
| `DIANN_DIA` | `has_bu_diann_layout`、DIA-NN parquet report | `ingest_universal_diann` |
| `MZML_ONLY` | `collect_mzml_files` 或 RAW 转换后 mzML | `ingest_mzml_only` |

## 12.新增功能接入方式

新增一个导入格式：

1. 在 `types.py::DatasetShape` 增加枚举值，并扩展 `ImportPlan` 需要携带的最小字段。
2. 在 `detectors.py` 增加轻量检测函数；检测函数只判断目录/文件特征，不解析大文件，不写 DB。
3. 在 `planner.py::plan_zip_ingest` 中增加 shape 分支，返回 `ImportPlan`。
4. 新增独立 adapter，例如现有 `universal_toppic_adapter.py`、`universal_prsm_js_adapter.py`、`universal_diann_adapter.py`、`mzml_only_adapter.py` 的模式。adapter 负责外部格式到 universal schema 的映射。
5. 在 `import_jobs.py::run_path_import_job` 增加薄调度分支，调用 adapter 并处理 progress/finalize。
6. 如格式依赖 RAW、PFMB 或 mzML mapping，接入现有 `raw_conversion`、`pfmb`、`mzml_mapping` 模块，不要把这些逻辑复制进 adapter。
7. 增加后端测试，至少覆盖 planner shape、adapter 入库边界和 import_jobs 调度。

新增 detector：

* 输入应是 `Path` 或小型数据结构。
* 输出应是 bool、字符串或枚举。
* 不应依赖 FastAPI、SQLAlchemy Session 或 adapter。
* 不应读取完整 mzML、parquet 或 PFMB 二进制内容。

新增 adapter：

* 输入应包含 `database_url`、`root`、slug/name/description、必要的 mapping/sidecar 信息。
* 输出应是 stats dataclass，例如 `UniversalImportStats`、`UniversalDiannImportStats`、`MzmlOnlyImportStats`。
* adapter 可以写 universal schema，但不处理 HTTP 请求，不启动 background thread，不做 job 表状态。

## 13.内部实现边界

以下函数或类是内部实现，不建议跨模块直接调用：

* `back\app\dataset_ingest_root\resolver.py::_has_mzml_or_raw_file`、`_matching_layouts`：只服务 root resolver。
* `back\app\services\import_planner\planner.py::_collect_uncompressed_mzml_files`：只服务 `plan_zip_ingest`。
* `back\app\ingest\universal_toppic_adapter.py::_RunRegistry`、`_create_dataset`、`_import_proteins_and_forms`、`_insert_protein`、`_insert_proteoform`、`_insert_relation`、`_import_fast_prsm_summaries`。
* `back\app\ingest\universal_prsm_js_adapter.py::_json`、`_accession_from_sequence_name`。
* `back\app\ingest\mzml_only_adapter.py::_collect_viewable_mzml_files`、`_create_dataset`、`_insert_runs`。
* `back\app\ingest\bu\universal_diann_adapter.py::_create_dataset`、`_insert_runs`、`_collect_entities_and_matches`、`_pfmb_match_block`、`_insert_proteins`、`_insert_peptides`、`_insert_matches`、`_insert_relations`。
* `back\app\raw_conversion\tool_discovery.py::_repo_root`、`_expand_configured_path`、`_default_missing_message`。
* `back\app\pfmb\sidecar_prepare.py::_run_generation_commands`、`_run_bridge`、`_safe_slug`、`_write_generation_manifest`。
* `back\app\pfmb\index_builder.py::_iter_pos_rows`、`_columnar_rows`、`_required_str`、`_required_int`、`_required_float_list`。

这些 helper 可以在本文件内维护，但不要作为跨模块公共 API 写入新调用链。跨模块优先调用上面的“可复用入口”。

## 14.不要绕过的层

* 不要从 route 直接调用 adapter；route 应通过 import job 编排创建任务。
* 不要从 adapter 直接打开 native folder picker 或修改 `import_jobs` 状态。
* 不要在 planner 中写数据库。
* 不要在 detector 中读取大文件内容。
* 不要绕过 `mzml_mapping` 自己拼 PrSM 到 mzML 的宽松匹配。
* 不要绕过 `prepare_bu_pfmb_sidecar` 直接假设 PFMB sidecar 一定存在。
* 不要绕过 `convert_raw_files_for_import` 直接拼 ThermoRawFileParser 命令。

## 15.相关测试

本节列出开发时应参考或补充的测试入口；当前任务不运行这些测试。

* planner/detector：`back\tests\test_import_planner.py`、`back\tests\test_import_planner_raw.py`。
* RAW import 调度：`back\tests\test_import_jobs_raw_conversion.py`。
* RAW converter 和 existing mzML 校验：`back\tests\test_raw_conversion_thermo.py`、`back\tests\test_raw_conversion_discovery.py`。
* mzML mapping：`back\tests\test_raw_mzml_mapping.py`。
* BU spectra/import 后运行时：`back\tests\test_bu_spectrum_api.py`、`back\tests\test_bu_runtime_api.py`。
* PFMB reader/sidecar 人工验收脚本在 `cs\`，例如 `cs\test_pfmb_reader.py`、`cs\test_index_reader.py`；这些是能力验收，不替代 `back\tests`。
