# BackendAPI

## 1.模块定位

BackendAPI 模块说明 FastAPI 路由组织、API 版本前缀、通用依赖、分页、错误处理和主要业务 API 分组。它是前端 UI 与后端业务 service、数据库、磁盘文件之间的 HTTP 边界。

## 2.核心职责

* 统一注册 `/api/v1` API 路由。
* 提供 datasets、imports、TopDown、BottomUp、mzML spectra 等 API 分组。
* 通过 `get_db` 注入数据库 Session。
* 使用 Pydantic schema 定义 response model。
* 用 `HTTPException` 表达业务错误和状态码。

## 3.关键目录和文件

* `back\app\api\v1\__init__.py`：v1 API router 注册入口，prefix 为 `/api/v1`。
* `back\app\api\v1\bu\__init__.py`：BottomUp router 注册入口。
* `back\app\api\deps.py`：FastAPI 依赖入口，提供数据库 Session。
* `back\app\schemas\common.py`：通用分页 `Page` schema。
* `back\app\api\v1\datasets.py`：dataset list/detail/delete API。
* `back\app\api\v1\imports.py`：import job API。
* `back\app\api\v1\proteins.py`、`proteoforms.py`、`prsms.py`：TD API。
* `back\app\api\v1\mzml_spectra.py`：mzML scan、chromatogram、scan-index API。
* `front\src\lib\apiError.ts`：前端错误解析和 chart retry 判断。

数据库连接层来自 `back\app\core\db.py` 的 SQLAlchemy engine，默认配置字符串在 `back\app\core\config.py` 中是 `postgresql+psycopg`。

## 4.核心数据流

1. 前端 axios 请求 `/api/v1/...`。
2. FastAPI 根据 `api_router` 找到 route。
3. route 通过 `Depends(get_db)` 获得 Session。
4. route 调用 service 或直接执行 SQLAlchemy `text` 查询。
5. 结果组装为 Pydantic response model。
6. 异常通过 `HTTPException` 返回给前端。
7. 前端 `parseApiError` 将错误转换为 UI 可用结构。

## 5.关键API或关键组件

本节列出代表性 API 分组，不是全量 API 目录；完整路由以 `back\app\api\v1` 及其子目录为准。

主要 API 分组：

* datasets：`GET /datasets`、`GET /datasets/{slug}`、`DELETE /datasets/{slug}`。
* imports：`POST /imports/pick-folder`、`POST /imports`、`GET /imports/{job_id}`。
* TD：`/datasets/{slug}/cutoffs/{cutoff}/proteins|proteoforms|prsms`。
* BU：`/datasets/{slug}/overview|proteins|peptides|matches` 以及 match evidence API。
* mzML spectra：`/datasets/{dataset_id}/runs/{run_id}/spectra/{scan_number}`、`/chromatogram`、`/scan-index`。

## 6.和其他模块的关系

BackendAPI 被 UI 调用，向 Import、BottomUp、TopDown、SpectrumDataAccess、DerivedDataIndex 暴露 HTTP 边界。DataModelStorage 提供数据库表和 Session。

## 7.扩展和维护建议

新增 API 时应先确定属于 datasets、imports、BU、TD、mzML spectra 还是新分组。复杂业务逻辑应放到 service 或 adapter 中，route 保持参数解析、权限/模式校验和 response 组装。分页接口应复用 `Page` schema。

## 8.当前限制和注意事项

* 当前未找到统一错误码注册表。
* `HTTPException.detail` 有字符串、错误码字符串和对象等多种格式，不完全统一。
* 部分 TD route 内含较多 SQL 和业务组装逻辑，service 层不如 BU 清晰。
* 前端错误解析需兼容多种错误格式，新增 API 时不要随意改变错误结构。

## 9.路由注册链路

后端 API 的挂载链路是固定入口，不要在业务模块里绕过：

1. `back\app\main.py` 从 `app.api.v1` 导入 `api_router`，创建 `FastAPI(lifespan=lifespan)` 后调用 `app.include_router(api_router)`，因此所有 v1 API 都继承 `/api/v1` 前缀。
2. `back\app\api\v1\__init__.py::api_router` 使用 `APIRouter(prefix="/api/v1")`，并注册 `datasets.router`、`imports.router`、`proteins.router`、`proteoforms.router`、`prsms.router`、`spectra.router`、`mzml_spectra.router`、`bu.router`。
3. `back\app\api\v1\bu\__init__.py::router` 再注册 BU 子模块：`overview.router`、`lists.router`、`matches.router`、`ms2_annotations.router`、`proteins.router`、`chromatogram.router`。
4. `back\app\api\deps.py::get_db` 是 route 获取 SQLAlchemy `Session` 的通用入口；新增需要 DB 的 route 应使用 `Depends(get_db)`，不要在 route 中自己创建 engine。

## 10.可复用入口

后端可复用入口：

* `back\app\api\deps.py::get_db`：FastAPI DB Session 依赖。
* `back\app\schemas\common.py::Page`：分页响应 schema，TD/BU 列表接口都应优先复用。
* `back\app\schemas\dataset.py::DatasetOut`、`DatasetDeletedOut`、`DatasetRunSummary`、`CutoffOut`：dataset 输出契约。
* `back\app\schemas\imports.py::ImportEnqueueIn`、`ImportJobOut`、`ImportJobCreatedOut`、`ImportPickFolderOut`：import API 契约。
* `back\app\schemas\protein.py::ProteinListItemOut`、`ProteinDetailOut`、`ProteoformListItemOut`、`ProteoformDetailOut`、`PrsmListItemOut`、`PrsmDetailOut`：TD API 契约。
* `back\app\schemas\bu.py::BuOverviewOut`、`BuSpectrumV1`、`BuXicOut`、`BuProductXicOut`、`BuProductXicBatchIn`、`BuProductXicBatchOut`、`BuMs2AnnotationOut`、`BuChromatogramOut`：BU API 契约。

前端可复用入口：

* `front\src\api\client.ts::api`：axios 实例，统一 `baseURL="/api/v1"`。
* `front\src\api\client.ts::fetchDatasets`、`fetchDataset`、`deleteDataset`、`enqueueImport`、`pickImportFolder`、`fetchImportJob`、`fetchProteins`、`fetchProtein`、`fetchProteoforms`、`fetchProteoform`、`fetchPrsms`、`fetchPrsm`、`fetchMs1Spectrum`、`fetchMs2Spectrum`、`fetchMzmlSpectrum`。
* `front\src\features\bu\api\buClient.ts::fetchBuOverview`、`fetchBuRtMzHeatmap`、`fetchBuProteins`、`fetchBuProtein`、`fetchBuPeptides`、`fetchBuPeptide`、`fetchBuMatches`、`fetchBuMatch`、`fetchBuMatchMs2`、`fetchBuMatchMs1`、`fetchBuMatchXic`、`fetchBuMatchProductXic`、`fetchBuMatchProductXics`、`fetchBuMatchMs2Slots`、`fetchBuMatchMs2Annotation`、`fetchBuMatchMs2AnnotationMatrix`、`fetchBuRunChromatogram`。
* `front\src\features\spectra-only\api\spectraClient.ts::fetchSpectraChromatogram`、`fetchSpectraScanIndex`、`fetchSpectraFullScanIndex`、`fetchSpectraSpectrum`。
* `front\src\lib\apiError.ts::parseApiError` 和 `chartQueryRetry`：前端错误解析和图表查询 retry 策略。

## 11.API matrix

本表是代表性矩阵，不是全量 route reference；完整接口以 `back\app\api\v1` 及其子目录为准。

| 模块 | HTTP | 路径 | route 文件和函数 | request schema | response schema | service 或查询层 | 前端 client | 主要页面或组件 |
|---|---|---|---|---|---|---|---|---|
| datasets | GET | `/api/v1/datasets` | `back\app\api\v1\datasets.py::list_datasets` | 无 | `list[DatasetOut]` | `datasets.py` 内 SQL + `_dataset_out` | `fetchDatasets` | `front\src\pages\DatasetsPage.tsx` |
| datasets | GET | `/api/v1/datasets/{slug}` | `datasets.py::get_dataset_detail` | 无 | `DatasetOut` | `require_dataset`、`_cutoffs_payload`、`_runs_by_dataset`、`_bu_runs_by_dataset` | `fetchDataset` | `DatasetModeGate`、BU/TD pages |
| datasets | DELETE | `/api/v1/datasets/{slug}` | `datasets.py::delete_dataset` | 无 | `DatasetDeletedOut` | `back\app\services\import_jobs.py::delete_dataset` | `deleteDataset` | `DatasetsPage` |
| imports | POST | `/api/v1/imports/pick-folder` | `imports.py::pick_import_folder` | 无 | `ImportPickFolderOut` | native folder picker | `pickImportFolder` | `DatasetsPage` |
| imports | POST | `/api/v1/imports` | `imports.py::enqueue_import` | `ImportEnqueueIn` | `ImportJobCreatedOut` | `create_job`、`start_path_import_background` | `enqueueImport` | `DatasetsPage` |
| imports | GET | `/api/v1/imports/{job_id}` | `imports.py::get_import_job` | 无 | `ImportJobOut` | `get_job` | `fetchImportJob` | `DatasetsPage` |
| TD proteins | GET | `/api/v1/datasets/{slug}/cutoffs/{cutoff}/proteins` | `proteins.py::list_proteins` | query | `Page[ProteinListItemOut]` | route 内 SQL + `require_dataset`、`require_cutoff` | `fetchProteins` | `ProteinsPage` |
| TD proteins | GET | `/api/v1/datasets/{slug}/cutoffs/{cutoff}/proteins/{protein_id}` | `proteins.py::get_protein` | 无 | `ProteinDetailOut` | route 内 SQL | `fetchProtein` | `ProteinDetailPage` |
| TD proteoforms | GET | `/api/v1/datasets/{slug}/cutoffs/{cutoff}/proteoforms` | `proteoforms.py::list_proteoforms` | query | `Page[ProteoformListItemOut]` | route 内 SQL + `require_dataset` + `require_cutoff` | `fetchProteoforms` | `ProteoformsPage` |
| TD proteoforms | GET | `/api/v1/datasets/{slug}/cutoffs/{cutoff}/proteoforms/{proteoform_id}` | `proteoforms.py::get_proteoform` | 无 | `ProteoformDetailOut` | route 内 SQL | `fetchProteoform` | `ProteoformDetailPage` |
| TD PrSM | GET | `/api/v1/datasets/{slug}/cutoffs/{cutoff}/prsms` | `prsms.py::list_prsms` | query | `Page[PrsmListItemOut]` | `prsm_list_select_sql`、`prsm_list_item` | `fetchPrsms` | `PrsmsPage` |
| TD PrSM | GET | `/api/v1/datasets/{slug}/cutoffs/{cutoff}/prsms/{prsm_id}` | `prsms.py::get_prsm` | 无 | `PrsmDetailOut` | `load_prsm_detail` | `fetchPrsm` | `PrsmDetailPage` |
| TD spectra | GET | `/api/v1/datasets/{slug}/spectra/ms1/{spec_id}` | `spectra.py::ms1_spectrum` | 无 | `dict[str, Any]` | `get_ms1_spectrum` | `fetchMs1Spectrum` | `PrsmDetailPage` |
| TD spectra | GET | `/api/v1/datasets/{slug}/spectra/ms2/{spec_id}` | `spectra.py::ms2_spectrum` | 无 | `dict[str, Any]` | `get_ms2_spectrum` | `fetchMs2Spectrum` | `PrsmDetailPage` |
| mzML | GET | `/api/v1/datasets/{dataset_id}/runs/{run_id}/spectra/{scan_number}` | `mzml_spectra.py::mzml_spectrum` | 无 | `dict[str, Any]` | `get_spectrum_by_scan` | `fetchMzmlSpectrum`、`fetchSpectraSpectrum` | `SpectrumPanel` |
| mzML | GET | `/api/v1/datasets/{dataset_id:int}/runs/{run_id:int}/chromatogram` | `mzml_spectra.py::mzml_run_chromatogram` | query `type` | `BuChromatogramOut` | `chromatogram_summary.load_summary` | `fetchSpectraChromatogram` | `ChromatogramPanel` |
| mzML | GET | `/api/v1/datasets/{dataset_id}/runs/{run_id}/scan-index` | `mzml_spectra.py::mzml_run_scan_index` | query | `dict[str, Any]` | `load_scan_index` | `fetchSpectraScanIndex`、`fetchSpectraFullScanIndex` | `ScanListPanel` |
| BU overview | GET | `/api/v1/datasets/{slug}/overview` | `bu\overview.py::overview` | 无 | `BuOverviewOut` | `overview_service.get_overview` | `fetchBuOverview` | `BuOverviewPage` |
| BU overview | GET | `/api/v1/datasets/{slug}/overview/rt-mz` | `bu\overview.py::rt_mz` | query | `BuRtMzHeatmapOut` | `overview_service.get_rt_mz_heatmap` | `fetchBuRtMzHeatmap` | `BuOverviewPage` |
| BU list | GET | `/api/v1/datasets/{slug}/proteins` | `bu\lists.py::proteins` | query | `Page[BuProteinListItemOut]` | `lists_service.list_proteins` | `fetchBuProteins` | `BuProteinsPage` |
| BU list | GET | `/api/v1/datasets/{slug}/peptides` | `bu\lists.py::peptides` | query | `Page[BuPeptideListItemOut]` | `lists_service.list_peptides` | `fetchBuPeptides` | `BuPeptidesPage` |
| BU list | GET | `/api/v1/datasets/{slug}/matches` | `bu\lists.py::matches` | query | `Page[BuMatchListItemOut]` | `lists_service.list_matches` | `fetchBuMatches` | `BuMatchesPage` |
| BU match | GET | `/api/v1/datasets/{slug}/matches/{match_id}` | `bu\matches.py::match_detail` | 无 | `BuMatchDetailOut` | `lists_service.get_match_detail` | `fetchBuMatch` | `BuMatchDetailPage` |
| BU spectrum | GET | `/api/v1/datasets/{slug}/matches/{match_id}/spectrum/ms2` | `bu\matches.py::match_ms2` | query | `BuSpectrumV1` | `spectrum_facade.get_match_ms2` | `fetchBuMatchMs2` | `BuSpectrumChart` |
| BU spectrum | GET | `/api/v1/datasets/{slug}/matches/{match_id}/spectrum/ms1` | `bu\matches.py::match_ms1` | 无 | `BuSpectrumV1` | `spectrum_facade.get_match_ms1` | `fetchBuMatchMs1` | `BuSpectrumChart` |
| BU XIC | GET | `/api/v1/datasets/{slug}/matches/{match_id}/xic` | `bu\matches.py::match_xic` | query `ppm` | `BuXicOut` | `xic_service.get_match_xic` | `fetchBuMatchXic` | `BuXicChart` |
| BU product XIC | GET | `/api/v1/datasets/{slug}/matches/{match_id}/product-xic` | `bu\matches.py::match_product_xic` | query | `BuProductXicOut` | `product_xic_service.get_match_product_xic` | `fetchBuMatchProductXic` | `BuProductIonXicCard` |
| BU product XIC | POST | `/api/v1/datasets/{slug}/matches/{match_id}/product-xics` | `bu\matches.py::match_product_xics` | `BuProductXicBatchIn` | `BuProductXicBatchOut` | `product_xic_service.get_match_product_xics` | `fetchBuMatchProductXics` | `BuProductIonXicCard` |
| BU PFMB | GET | `/api/v1/datasets/{slug}/matches/{match_id}/ms2-slots` | `bu\ms2_annotations.py::match_ms2_slots` | 无 | `BuMs2SlotListOut` | `ms2_annotation_svc.get_slots` | `fetchBuMatchMs2Slots` | `BuPfmbAnnotationCard` |
| BU PFMB | GET | `/api/v1/datasets/{slug}/matches/{match_id}/ms2-annotation/{prsm_index}` | `bu\ms2_annotations.py::match_ms2_annotation` | 无 | `BuMs2AnnotationOut` | `ms2_annotation_svc.get_annotation` | `fetchBuMatchMs2Annotation` | `BuPfmbHeatmap` |
| BU PFMB | GET | `/api/v1/datasets/{slug}/matches/{match_id}/ms2-annotation-matrix` | `bu\ms2_annotations.py::match_ms2_annotation_matrix` | 无 | `BuMs2AnnotationMatrixOut` | `ms2_annotation_svc.get_annotation_matrix` | `fetchBuMatchMs2AnnotationMatrix` | `BuPfmbHeatmap` |
| BU chromatogram | GET | `/api/v1/datasets/{slug}/runs/{run_id}/chromatogram` | `bu\chromatogram.py::chromatogram` | query `type` | `BuChromatogramOut` | `chromatogram_service.get_chromatogram` | `fetchBuRunChromatogram` | BU run charts |

## 12.新增功能接入方式

新增 API 时按以下顺序改，避免前后端契约分叉：

1. 在对应 route 文件新增或更新函数，例如 datasets 改 `back\app\api\v1\datasets.py`，BU match evidence 改 `back\app\api\v1\bu\matches.py` 或 `ms2_annotations.py`。
2. 在 `back\app\schemas\*.py` 新增或更新 request/response schema；分页接口复用 `Page[T]`。
3. 复杂业务放入 service，例如 BU 谱图走 `back\app\bu\services\spectrum_facade.py`、XIC 走 `xic_service.py`、product XIC 走 `product_xic_service.py`，不要把复杂解析和 SQL 组装全部塞进 route。
4. 新 router 需要在 `back\app\api\v1\__init__.py` 注册；BU 子模块需要在 `back\app\api\v1\bu\__init__.py` 注册。
5. 前端在 `front\src\api\client.ts` 或 feature client 中增加函数；BU 使用 `front\src\features\bu\api\buClient.ts`，spectra-only 使用 `front\src\features\spectra-only\api\spectraClient.ts`。
6. 前端 DTO 同步到 `front\src\api\types.ts`、`front\src\features\bu\types.ts` 或 `front\src\features\spectra-only\types.ts`。
7. 后端补 API/service 测试；前端补 Playwright route mock 或工具函数测试。

## 13.内部实现边界

route 层可以做：

* 参数校验：例如 `Query(..., ge=1)`、`order` pattern、`ms_level` 范围。
* dataset mode 检查：例如 BU route 通过 `require_bu_dataset`、`require_bu_match`。
* 调用 service 或小型查询层。
* 组装 response schema，抛出 `HTTPException`。

route 层不应做：

* 复杂文件解析。PrSM detail 读取应走 `load_prsm_detail`，不要在 route 里重新解析 JS shell。
* mzML 全量解析。mzML 单谱应走 `get_spectrum_by_scan`，XIC 应走 scan index + indexed reader。
* PFMB 二进制读取。PFMB annotation 应走 `ms2_annotation_svc` 和 `app.pfmb` 模块。
* 导入格式识别。import 格式识别应走 `plan_zip_ingest`。

以下为内部实现，不建议跨模块直接调用：

* `back\app\api\v1\datasets.py::_capabilities_out`、`_dataset_mode`、`_cutoffs_payload`、`_runs_by_dataset`、`_bu_runs_by_dataset`、`_dataset_out`。
* `back\app\api\v1\mzml_spectra.py::_run_row`、`_run_metadata`、`_backfill_detail`、`_downsample`、`_scan_index_summary`。
* `front\src\lib\apiError.ts::responseFrom`、`detailFrom`、`classify` 是 `parseApiError` 的内部 helper。

## 14.不要绕过的层

* 不要绕过 `api_router` 直接把新 route 挂到 `back\app\main.py`。
* 不要绕过 `get_db` 自建 Session。
* 不要绕过 Pydantic schema 直接返回不稳定 dict，除非现有 route 明确使用 `dict[str, Any]` 兼容旧格式。
* 不要绕过前端 API client 在 React 组件里直接拼 axios URL。
* 不要绕过 `parseApiError` 自行解析后端错误。

## 15.相关测试

本节只列开发时应参考或补充的测试入口；运行前需确认不会违反当前任务约束。

* datasets API：`back\tests\test_datasets_api_modes.py`。
* BU route 注册和 mode 检查：`back\tests\test_bu_runtime_api.py`。
* mzML API：`back\tests\test_mzml_spectra_api.py`、`back\tests\test_chromatogram_route_matching.py`。
* BU spectrum/XIC/product XIC：`back\tests\test_bu_spectrum_api.py`、`back\tests\test_bu_product_xic_indexed.py`、`back\tests\test_bu_xic_isotopes.py`。
* BU PFMB annotation：`back\tests\test_bu_ms2_annotation.py`。
* 前端 API 错误解析：`front\tests\api-error.spec.ts`。
* 前端 route mock 示例：`front\tests\bu-match-detail.spec.ts`、`front\tests\bu-pfmb-visuals.spec.ts` 中的 `page.route("**/api/v1/**", ...)`。
