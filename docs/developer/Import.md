# Import

## 1.模块定位

Import 模块负责从服务器本机目录创建导入任务，识别数据集类型，调度对应 ingest adapter 写入数据库，并在导入后触发派生数据生成。当前实现是 path-based folder import，不是浏览器上传 ZIP 文件。

## 2.核心职责

* 提供选择目录、创建导入任务、查询任务状态的 HTTP API。
* 校验 `source_path` 是否存在且为目录。
* 解析唯一 ingest root。
* 计算 dataset metadata fingerprint，用于重复识别。
* 调用 planner 判断 TopPIC、PrSM bundle、DIA-NN parquet、mzML-only、Thermo RAW-only 等形态。
* 调用对应 adapter 写入 universal schema。
* 导入完成后触发 scan index 和 chromatogram summary 等派生数据生成。

## 3.关键目录和文件

* `back\app\api\v1\imports.py`：导入任务 HTTP 入口，提供 `pick-folder`、创建任务、查询任务状态。
* `back\app\schemas\imports.py`：导入请求和任务响应 schema。
* `back\app\services\import_jobs.py`：导入任务编排层，负责 job 状态、阶段进度、adapter 调度、finalize 和 post-import derived data。
* `back\app\dataset_ingest_root\resolver.py`：从用户选择目录中解析唯一 ingest root。
* `back\app\fingerprint\dataset_metadata_fingerprint.py`：计算元数据 manifest MD5 指纹。
* `back\app\services\import_planner\planner.py`：判断导入 shape 和 spectra source。
* `front\src\pages\DatasetsPage.tsx`：前端导入对话框、folder picker、任务轮询。
* `front\src\api\client.ts`：`enqueueImport`、`pickImportFolder`、`fetchImportJob`。

## 4.核心数据流

1. 前端 `DatasetsPage` 收集 `source_path`、slug、name、description。
2. `enqueueImport` 调用 `POST /api/v1/imports`。
3. `enqueue_import` 校验路径并调用 `resolve_ingest_root` 做快速失败检查。
4. `create_job` 写入 `import_jobs`，`start_path_import_background` 启动后台线程。
5. `run_path_import_job` 再次解析 ingest root，并调用 `compute_dataset_metadata_fingerprint`。
6. `find_dataset_with_fingerprint` 检查重复导入。
7. `plan_zip_ingest` 判断数据形态和 RAW 转换需求。
8. 必要时调用 RAW conversion；然后调用 TopPIC、PrSM bundle、DIA-NN 或 mzML-only adapter。
9. 编排层更新 `datasets.source_root`、`datasets.source_dataset_fingerprint` 和 `runs.run_metadata`。
10. `build_post_import_derived_data` 触发 scan index 和 chromatogram summary 生成。
11. 前端轮询 `GET /api/v1/imports/{job_id}` 展示进度和错误。

导入 HTTP 入口基于 FastAPI，入参和响应 schema 来自 Pydantic，例如 `ImportEnqueueIn`。`start_path_import_background` 使用 `threading.Thread` 启动后台导入，状态写入 `import_jobs` 表。BU DIA-NN parquet 读取由 `back\app\ingest\bu\diann_parquet_reader.py` 使用 `pyarrow.parquet` 完成。`python-multipart` 只在后端依赖中存在，当前源码未确认 multipart upload 入口，不能写成 multipart upload 已实现。

## 5.关键API或关键组件

* `POST /api/v1/imports/pick-folder`：在 API host 上打开本机目录选择器。
* `POST /api/v1/imports`：创建导入任务，入参来自 `ImportEnqueueIn`。
* `GET /api/v1/imports/{job_id}`：查询导入任务状态。
* `create_job`、`get_job`、`run_path_import_job`：导入任务核心函数。
* `enqueueImport`、`pickImportFolder`、`fetchImportJob`：前端导入 API client 方法。

## 6.和其他模块的关系

Import 依赖 ImportMiddleware 做格式识别和 adapter 调度，依赖 RawFile 处理 Thermo RAW，依赖 DataModelStorage 写 DB，依赖 DerivedDataIndex 生成派生文件。BottomUp 和 TopDown 的导入 adapter 被 Import 调用。

参见：`ImportMiddleware.md`、`DataModelStorage.md`、`DerivedDataIndex.md`。

## 7.扩展和维护建议

新增导入格式时应优先扩展 root resolver、planner、detector 和独立 adapter，再由 `import_jobs.py` 做薄编排。不要在 `back\app\api\v1\imports.py` 中塞入格式解析、递归扫盘、DB 大批量写入或文件转换逻辑。与指纹、根路径解析相关的功能必须遵守 `AGENTS.md` 中的模块边界。

相关测试入口以 `Testing.md` 的完整分层为准；本模块重点参考 `back\tests\test_import_planner.py`、`back\tests\test_import_planner_raw.py`、`back\tests\test_import_jobs_raw_conversion.py`。

## 8.当前限制和注意事项

* 当前未找到 multipart upload 或 ZIP 上传入口；旧文档中的 ZIP 上传流程不是当前主实现。
* `python-multipart` 在依赖中存在，但当前源码未确认 multipart upload 主路径。
* 当前未找到 MGF 导入支持。
* FASTA 不是独立数据集导入类型，更多用于 BU 蛋白序列补全或覆盖。
* `plan_zip_ingest` 是历史命名，当前实际处理 folder ingest。
* 失败回滚不是统一跨文件事务框架；不能写成强事务文件回滚。
* `import_jobs.delete_dataset` 当前是 DB only，不删除磁盘源目录。

## 9.可复用入口

HTTP 和 schema 入口：

* `back\app\api\v1\imports.py::pick_import_folder`：`POST /api/v1/imports/pick-folder`，返回 `ImportPickFolderOut`。
* `back\app\api\v1\imports.py::enqueue_import`：`POST /api/v1/imports`，入参 `ImportEnqueueIn`，返回 `ImportJobCreatedOut`。
* `back\app\api\v1\imports.py::get_import_job`：`GET /api/v1/imports/{job_id}`，返回 `ImportJobOut`。
* `back\app\schemas\imports.py::ImportEnqueueIn`、`ImportJobOut`、`ImportJobCreatedOut`、`ImportPickFolderOut`。

编排和业务入口：

* `back\app\services\import_jobs.py::ensure_jobs_table`：启动时保证 `import_jobs` 表结构。
* `back\app\services\import_jobs.py::ensure_dataset_fingerprint_schema`：保证 `datasets.source_dataset_fingerprint` 和唯一索引。
* `back\app\services\import_jobs.py::ensure_runs_metadata_schema`：保证 `runs.run_metadata`。
* `back\app\services\import_jobs.py::create_job`、`get_job`、`cancel_active_import_jobs_for_slug`、`has_active_job_for_slug`。
* `back\app\services\import_jobs.py::run_path_import_job`：后台导入主编排入口。
* `back\app\services\import_jobs.py::start_path_import_background`：启动后台线程。
* `back\app\services\import_jobs.py::delete_dataset`：dataset 删除入口，当前是数据库侧删除，不删除源目录。
* `back\app\dataset_ingest_root\resolver.py::resolve_ingest_root`：从用户选择目录解析唯一 ingest root。
* `back\app\fingerprint\dataset_metadata_fingerprint.py::compute_dataset_metadata_fingerprint`：计算元数据 manifest MD5 指纹。
* `back\app\services\post_import_derived_data.py::build_post_import_derived_data`：导入完成后生成 scan index 和 chromatogram summary。

前端入口：

* `front\src\api\client.ts::enqueueImport`
* `front\src\api\client.ts::pickImportFolder`
* `front\src\api\client.ts::fetchImportJob`

## 10.调用链

创建导入任务的调用链：

1. `front\src\pages\DatasetsPage.tsx` 收集 `source_path`、slug、name、description。
2. `front\src\api\client.ts::enqueueImport` 请求 `POST /api/v1/imports`。
3. `back\app\api\v1\imports.py::enqueue_import` 校验 `source_path`，调用 `resolve_ingest_root` 做快速失败检查。
4. `back\app\services\import_jobs.py::create_job` 写入 `import_jobs`。
5. `back\app\services\import_jobs.py::start_path_import_background` 使用 `threading.Thread` 执行 `run_path_import_job`。
6. `run_path_import_job` 再次调用 `resolve_ingest_root`，随后调用 `compute_dataset_metadata_fingerprint`。
7. `run_path_import_job` 调用 `find_dataset_with_fingerprint` 做重复识别。
8. `run_path_import_job` 调用 `back\app\services\import_planner\planner.py::plan_zip_ingest` 判断 `DatasetShape`、spectra source、RAW/mzML 状态。
9. 如需 RAW 转换，调用 `back\app\raw_conversion\service.py::convert_raw_files_for_import`。
10. 根据 shape 调用 adapter：`ingest_universal_toppic`、`assign_toppic_runs_from_prsm_headers`、`ingest_universal_prsm_js`、`ingest_universal_diann` 或 `ingest_mzml_only`。
11. 编排层补写 `datasets.source_root`、`datasets.source_dataset_fingerprint`、`datasets.extra_metadata`、`runs.run_metadata`。
12. `run_path_import_job` 调用 `build_post_import_derived_data` 生成派生数据。
13. 前端通过 `front\src\api\client.ts::fetchImportJob` 轮询 `GET /api/v1/imports/{job_id}`。

目录选择调用链：

1. `front\src\api\client.ts::pickImportFolder` 请求 `POST /api/v1/imports/pick-folder`。
2. `back\app\api\v1\imports.py::pick_import_folder` 先用 `_client_is_loopback` 限制本机调用。
3. route 返回 `ImportPickFolderOut`，前端把路径带入 `enqueueImport`。

删除调用链：

1. `front\src\api\client.ts::deleteDataset` 请求 `DELETE /api/v1/datasets/{slug}`。
2. `back\app\api\v1\datasets.py::delete_dataset` 调用 `back\app\services\import_jobs.py::delete_dataset`。
3. `import_jobs.delete_dataset` 删除 `import_jobs` 和 `datasets` 记录；当前不是磁盘源目录删除。

## 11.新增功能接入方式

新增导入格式时按这个顺序接入：

1. root 识别：如输入目录布局变化，先扩展 `back\app\dataset_ingest_root\resolver.py::has_dataset_layout`、`has_bu_diann_layout`、`has_spectra_only_layout` 或新增等价窄接口。
2. planner 识别：在 `back\app\services\import_planner\types.py::DatasetShape` 增加 shape，并在 `planner.py::plan_zip_ingest` 返回新的 `ImportPlan`。
3. detector：把轻量格式判断放到 `back\app\services\import_planner\detectors.py`，例如现有 `detect_spectra_source`、`detect_bu_spectra_source`。
4. adapter：新增独立 adapter，职责是把外部格式写入 universal schema，不处理 HTTP 请求。
5. 编排：在 `run_path_import_job` 增加薄调度分支，只做 job 状态、progress、adapter 调用和 finalize。
6. 前端：如导入参数变化，同步 `ImportEnqueueIn`、`front\src\api\types.ts::ImportEnqueueIn` 和 `DatasetsPage`。
7. 派生数据：如果新格式产出 mzML run，应确保 `build_post_import_derived_data` 能在导入后处理对应 run。

新增导入 job 状态字段时：

1. 更新 `back\app\services\import_jobs.py::ensure_jobs_table` 和 `_ALLOWED_UPDATE_COLUMNS`。
2. 更新 `back\app\services\import_jobs.py::ImportJob`。
3. 更新 `back\app\schemas\imports.py::ImportJobOut`。
4. 更新 `front\src\api\types.ts::ImportJobOut`。
5. 更新 `DatasetsPage` 展示逻辑。

## 12.内部实现边界

以下函数是内部实现，不建议跨模块直接调用：

* `back\app\api\v1\imports.py::_client_is_loopback`：只服务 native folder picker 安全检查。
* `back\app\services\import_jobs.py::_gc_old_jobs`、`_row_to_job`、`_update_job`：job 表维护内部 helper。
* `back\app\services\import_jobs.py::_phase_percent`、`_make_adapter_progress_handler`、`_make_bu_adapter_progress_handler`、`_fingerprint_progress_handler`：progress 映射内部 helper。
* `back\app\services\import_jobs.py::_validate_bu_mzml_mapping`：BU mzML mapping 校验内部 helper。
* `back\app\services\import_jobs.py::_run_post_import_derived_data`：封装 `build_post_import_derived_data` 的 job 状态更新内部 helper。
* `back\app\services\import_jobs.py::_raw_conversion_output_dir`、`_raw_conversion_progress_handler`、`_raw_conversion_error_detail`、`_raw_conversion_metadata_by_mzml_key`、`_dataset_raw_conversion_summary`：RAW conversion 编排内部 helper。
* `back\app\dataset_ingest_root\resolver.py::_has_mzml_or_raw_file`、`_matching_layouts`：root resolver 内部布局扫描 helper。

`run_path_import_job` 是编排层入口，但不应承载算法细节。它可以做状态更新、调用 planner、调用 adapter、finalize；不应新增递归扫盘 MD5 算法、parquet 解析、PFMB 二进制读取或 mzML 全量解析。

## 13.不要绕过的层

* 不要绕过 `resolve_ingest_root` 直接把用户选择目录传给 adapter。
* 不要绕过 `compute_dataset_metadata_fingerprint` 自己写 MD5 或读取文件内容；指纹必须保持 metadata manifest 语义。
* 不要绕过 `plan_zip_ingest` 在 API route 中判断 TopPIC/DIA-NN/mzML/RAW 格式。
* 不要绕过 RAW conversion contract 直接调用外部 converter；应走 `convert_raw_files_for_import`。
* 不要绕过 adapter 直接在 `imports.py` 或 `import_jobs.py` 写 `proteins`、`runs`、`identification_matches` 等业务大表。
* 不要在前端组件中直接请求 `/api/v1/imports`；应走 `enqueueImport`、`pickImportFolder`、`fetchImportJob`。

## 14.相关测试

本节列出修改导入链路时应参考或补充的测试；当前任务不运行这些测试。

* planner 和 detector：`back\tests\test_import_planner.py`、`back\tests\test_import_planner_raw.py`。
* RAW conversion 编排：`back\tests\test_import_jobs_raw_conversion.py`。
* RAW converter 和 indexed mzML 验证：`back\tests\test_raw_conversion_thermo.py`、`back\tests\test_raw_conversion_discovery.py`。
* RAW/mzML mapping：`back\tests\test_raw_mzml_mapping.py`。
* fingerprint/root 相关修改还需参考 `cs\性能测验约定.md` 和 `cs\指纹性能测验.py`，但 `cs\` 是能力测验/性能验收，不替代 `back\tests`。
