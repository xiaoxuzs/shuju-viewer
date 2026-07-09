# BottomUp

## 1.模块定位

BottomUp 模块负责 DIA-NN Bottom-Up 数据导入、protein/peptide/match 浏览、BU 证据页、live mzML MS1/MS2、precursor XIC、product ion XIC、PFMB annotation 和相关可视化。

## 2.核心职责

* 从 DIA-NN parquet 导入 BottomUp dataset。
* 写入 proteins、peptides、identification_matches 和 protein_relation_mapping。
* 提供 BU overview、protein、peptide、match 列表和详情 API。
* 基于 mzML scan index 和 indexed reader 提供 MS1/MS2、XIC 和 product XIC。
* 通过 PFMB sidecar 提供预计算 fragment match annotation。
* 提供 BU 前端页面和证据可视化。

## 3.关键目录和文件

* `back\app\api\v1\bu`：BottomUp API route 目录。
* `back\app\bu`：BottomUp service、schema 辅助、TDF reader 等后端业务目录。
* `back\app\ingest\bu`：DIA-NN 导入 adapter 和 parquet/run discovery。
* `back\app\pfmb`：PFMB sidecar 读取、索引、准备和引用 sidecar 处理。
* `front\src\features\bu`：当前 BU 前端主路径。
* `back\app\ingest\bu\universal_diann_adapter.py`：DIA-NN parquet 导入 adapter。
* `back\app\bu\services\lists_service.py`：BU proteins、peptides、matches 列表和详情查询。
* `back\app\bu\services\spectrum_facade.py`：BU MS1/MS2 证据服务。
* `back\app\bu\services\xic_service.py`：precursor XIC 服务。
* `back\app\bu\services\product_xic_service.py`：product ion XIC 服务。
* `back\app\bu\services\ms2_annotation_svc.py`：PFMB MS2 annotation 服务。

## 4.核心数据流

1. Import 模块识别 DIA-NN 布局后调用 `ingest_universal_diann`。
2. adapter 读取 parquet、统计文件、run 文件和可选 PFMB sidecar。
3. adapter 写入 `datasets`、`runs`、`proteins`、`peptides`、`identification_matches`、`protein_relation_mapping`。
4. BU 页面通过 `front\src\features\bu\api\buClient.ts` 请求后端 API。
5. match detail 先从 DB 读取 match、peptide、run metadata。
6. live MS1/MS2 和 XIC 通过 scan index 找候选 scan，再由 mzML indexed reader 读取谱峰。
7. PFMB evidence 通过 DB baked metadata 找 slot，再读取 `results.pfmb` 中指定 record。
8. 前端用 `BuSpectrumChart`、`BuXicChart`、`BuProductIonXicChart`、`BuPfmbHeatmap` 等组件展示。

BU parquet 读取由 `pyarrow.parquet.ParquetFile.iter_batches` 流式完成，避免一次性加载完整 DIA-NN report。BU service 查询 PostgreSQL 时主要通过 SQLAlchemy Session 和 raw SQL/`text`。live evidence 依赖 mzML、scan index 和 indexed reader；前端证据图是 React 组件加 D3/SVG 交互。PFMB 是预计算 fragment match sidecar，不是 live mzML MS2。

## 5.关键API或关键组件

* `GET /api/v1/datasets/{slug}/overview`
* `GET /api/v1/datasets/{slug}/overview/rt-mz`
* `GET /api/v1/datasets/{slug}/proteins`
* `GET /api/v1/datasets/{slug}/peptides`
* `GET /api/v1/datasets/{slug}/matches`
* `GET /api/v1/datasets/{slug}/matches/{match_id}`
* `GET /api/v1/datasets/{slug}/matches/{match_id}/xic`
* `GET /api/v1/datasets/{slug}/matches/{match_id}/spectrum/ms1`
* `GET /api/v1/datasets/{slug}/matches/{match_id}/spectrum/ms2`
* `GET /api/v1/datasets/{slug}/matches/{match_id}/product-xic`
* `POST /api/v1/datasets/{slug}/matches/{match_id}/product-xics`
* `GET /api/v1/datasets/{slug}/matches/{match_id}/ms2-slots`
* `GET /api/v1/datasets/{slug}/matches/{match_id}/ms2-annotation/{prsm_index}`
* `GET /api/v1/datasets/{slug}/matches/{match_id}/ms2-annotation-matrix`
* `BuOverviewPage`、`BuProteinsPage`、`BuPeptidesPage`、`BuMatchesPage`、`BuMatchDetailPage`

## 6.和其他模块的关系

BottomUp 依赖 ImportMiddleware 写入数据，依赖 DataModelStorage 存储关系，依赖 SpectrumDataAccess 读取 mzML，依赖 DerivedDataIndex 查询 scan index 和 chromatogram summary，依赖 BinaryFormat 读取 PFMB，依赖 Visualization 展示证据。

参见：`Visualization.md`、`BinaryFormat.md`、`SpectrumDataAccess.md`。

## 7.扩展和维护建议

新增 BU 数据源时优先新增 ingest adapter 和 field mapping，不要把解析逻辑写进 route。新增 match 证据时先判断数据来自 live mzML、scan index、chromatogram summary 还是 PFMB sidecar，再选择 service 层扩展。前端新增 BU 页应放在 `front\src\features\bu`，不要默认使用 `front\src\features\bu-viewer`。

相关测试入口以 `Testing.md` 的完整分层为准；本模块重点参考 `back\tests\test_bu_spectrum_api.py`、`back\tests\test_bu_product_xic_indexed.py`、`back\tests\test_bu_ms2_annotation.py`、`back\tests\test_bu_chromatogram_summary.py`。

## 8.当前限制和注意事项

* 当前未找到 MGF 支持。
* Bruker 相关路径存在，包括 TDF reader、DIA windows、chromatogram、mobility slice 等；但 live MS1 和 MS2 证据主要面向 mzML 路径。
* PFMB annotation 和 live mzML MS2 是两类证据来源，不能混写成同一数据。
* PFMB sidecar 缺失或生成失败时，BU 导入可以降级为没有 Fragment Match。
* `front\src\features\bu-viewer` 可能是历史重复目录，当前路由主路径是 `front\src\features\bu`。
## 9.可复用入口

后端 route：

* `back\app\api\v1\bu\overview.py::overview`：`GET /datasets/{slug}/overview`。
* `back\app\api\v1\bu\overview.py::rt_mz`：`GET /datasets/{slug}/overview/rt-mz`。
* `back\app\api\v1\bu\lists.py::proteins`：`GET /datasets/{slug}/proteins`。
* `back\app\api\v1\bu\proteins.py::protein_detail`：`GET /datasets/{slug}/proteins/{protein_id}`。
* `back\app\api\v1\bu\lists.py::peptides`：`GET /datasets/{slug}/peptides`。
* `back\app\api\v1\bu\lists.py::peptide_detail`：`GET /datasets/{slug}/peptides/{peptide_id}`。
* `back\app\api\v1\bu\lists.py::matches`：`GET /datasets/{slug}/matches`。
* `back\app\api\v1\bu\matches.py::match_detail`：`GET /datasets/{slug}/matches/{match_id}`。
* `back\app\api\v1\bu\matches.py::match_ms2`：`GET /datasets/{slug}/matches/{match_id}/spectrum/ms2`。
* `back\app\api\v1\bu\matches.py::match_ms1`：`GET /datasets/{slug}/matches/{match_id}/spectrum/ms1`。
* `back\app\api\v1\bu\matches.py::match_xic`：`GET /datasets/{slug}/matches/{match_id}/xic`。
* `back\app\api\v1\bu\matches.py::match_product_xic`：`GET /datasets/{slug}/matches/{match_id}/product-xic`。
* `back\app\api\v1\bu\matches.py::match_product_xics`：`POST /datasets/{slug}/matches/{match_id}/product-xics`。
* `back\app\api\v1\bu\matches.py::match_mobility_slice`：`GET /datasets/{slug}/matches/{match_id}/mobility-slice`。
* `back\app\api\v1\bu\ms2_annotations.py::match_ms2_slots`：`GET /datasets/{slug}/matches/{match_id}/ms2-slots`。
* `back\app\api\v1\bu\ms2_annotations.py::match_ms2_annotation`：PFMB 单 slot annotation route。
* `back\app\api\v1\bu\ms2_annotations.py::match_ms2_annotation_matrix`：PFMB matrix route。
* `back\app\api\v1\bu\chromatogram.py::chromatogram`：`GET /datasets/{slug}/runs/{run_id}/chromatogram`。
* `back\app\api\v1\bu\chromatogram.py::dia_windows`：`GET /datasets/{slug}/runs/{run_id}/dia-windows`。

后端 service：

* `back\app\bu\services\overview_service.py::get_overview`
* `back\app\bu\services\overview_service.py::get_rt_mz_heatmap`
* `back\app\bu\services\lists_service.py::list_proteins`
* `back\app\bu\services\lists_service.py::list_peptides`
* `back\app\bu\services\lists_service.py::list_matches`
* `back\app\bu\services\lists_service.py::get_match_detail`
* `back\app\bu\services\lists_service.py::get_peptide_detail`
* `back\app\bu\services\protein_detail_service.py::get_protein_detail`
* `back\app\bu\services\spectrum_facade.py::get_match_ms2`
* `back\app\bu\services\spectrum_facade.py::get_match_ms1`
* `back\app\bu\services\xic_service.py::get_match_xic`
* `back\app\bu\services\product_xic_service.py::get_match_product_xic`
* `back\app\bu\services\product_xic_service.py::get_match_product_xics`
* `back\app\bu\services\ms2_annotation_svc.py::get_slots`
* `back\app\bu\services\ms2_annotation_svc.py::get_annotation`
* `back\app\bu\services\ms2_annotation_svc.py::get_annotation_matrix`
* `back\app\bu\services\chromatogram_service.py::get_chromatogram`
* `back\app\bu\services\chromatogram_service.py::get_dia_windows`
* `back\app\bu\services\mobility_service.py::get_match_mobility_slice`

前端入口：

* `front\src\features\bu\api\buClient.ts`
* `front\src\features\bu\types.ts`
* `front\src\features\bu\pages\BuOverviewPage.tsx::BuOverviewPage`
* `front\src\features\bu\pages\BuProteinsPage.tsx::BuProteinsPage`
* `front\src\features\bu\pages\BuPeptidesPage.tsx::BuPeptidesPage`
* `front\src\features\bu\pages\BuMatchesPage.tsx::BuMatchesPage`
* `front\src\features\bu\pages\BuMatchDetailPage.tsx::BuMatchDetailPage`
* `front\src\features\bu\components\match-detail\useBuPfmbEvidence.ts::useBuPfmbEvidence`
* `front\src\features\bu\components\match-detail\BuEvidenceSummary.tsx::BuEvidenceSummary`
* `front\src\features\bu\components\match-detail\BuPfmbHeatmap.tsx::BuPfmbHeatmap`
* `front\src\features\bu\components\match-detail\BuProductIonXicCard.tsx::BuProductIonXicCard`
* `front\src\features\bu\components\match-detail\SelectedEvidenceBar.tsx::SelectedEvidenceBar`

## 10.调用链

BU route 注册链：

1. `back\app\api\v1\bu\__init__.py` 创建 `router`。
2. `router.include_router(overview.router)`、`lists.router`、`matches.router`、`ms2_annotations.router`、`proteins.router`、`chromatogram.router` 接入 BU routes。
3. 上层 `back\app\api\v1\__init__.py` 再接入 v1 API。

列表页链路：

1. `front\src\features\bu\pages\BuProteinsPage.tsx` 调 `fetchBuProteins`。
2. `fetchBuProteins` 请求 `back\app\api\v1\bu\lists.py::proteins`。
3. route 调 `back\app\bu\services\lists_service.py::list_proteins`。
4. service 查询 universal schema 中的 `proteins`、`identification_matches` 等表并返回 `Page[BuProteinListItemOut]`。

match evidence 链路：

1. `BuMatchDetailPage` 调 `fetchBuMatch`、`fetchBuMatchMs2`、`fetchBuMatchMs1`、`fetchBuMatchXic`、`fetchBuMatchProductXics`。
2. `match_ms2` 和 `match_ms1` 进入 `spectrum_facade.get_match_ms2`、`get_match_ms1`。
3. `match_xic` 进入 `xic_service.get_match_xic`。
4. `match_product_xic` 和 `match_product_xics` 进入 `product_xic_service`。
5. PFMB 证据由 `useBuPfmbEvidence` 调 `fetchBuMatchMs2Slots`、`fetchBuMatchMs2Annotation`、`fetchBuMatchMs2AnnotationMatrix`。

chromatogram 链路：

1. `BuOverviewPage` 调 `fetchBuRunChromatogram`。
2. route `chromatogram.py::chromatogram` 调 `chromatogram_service.get_chromatogram`。
3. mzML run 读取 `chromatogram_summary.load_summary`；Bruker run 走 TDF reader 路径。

## 11.新增功能接入方式

新增 BU 列表页：

1. 后端新增或扩展 route，优先放 `back\app\api\v1\bu\lists.py` 或业务对应 route 文件。
2. 查询逻辑放 `back\app\bu\services\lists_service.py` 或独立 service，不在 route 中堆复杂 SQL。
3. response schema 放 BU schema/types 对应位置，保持 `Page[...]` 分页契约。
4. 前端在 `front\src\features\bu\api\buClient.ts` 增加 client 函数。
5. DTO 放 `front\src\features\bu\types.ts`。
6. 页面放 `front\src\features\bu\pages`，在 `front\src\App.tsx::App` 的 BU route 下接入。
7. 按页面行为补 `front\tests` 下 Playwright 入口。

新增证据卡片：

1. 先判断数据来源：DB、mzML scan index、PFMB sidecar，还是 derived summary。
2. DB 列表/详情字段走 `lists_service` 或 detail service。
3. mzML 谱图和 XIC 走 `spectrum_facade`、`xic_service` 或 `product_xic_service`。
4. PFMB 证据走 `ms2_annotation_svc` 和 `useBuPfmbEvidence`。
5. chromatogram 走 `chromatogram_service` 和 derived summary，不在请求时临时生成。

新增 XIC：

* precursor XIC 优先扩展 `back\app\bu\services\xic_service.py::get_match_xic`。
* product ion XIC 优先扩展 `back\app\bu\services\product_xic_service.py::get_match_product_xic` 或 `get_match_product_xics`。
* 不重新扫描 mzML；候选 scan 由 scan index service 提供。

## 12.内部实现边界

以下为内部实现或模块局部 helper，不建议跨模块直接调用：

* `back\app\bu\services\spectrum_facade.py::_json_object`、`_raw_format`、`_explicit_ms2_scan`、`_get_indexed_spectrum`、`_get_indexed_ms2`、`_scan_index_error`。
* `back\app\bu\services\xic_service.py::_rt_window`、`_best_intensities`、`_scan_index_http_error`、`_indexed_ms1_spectrum`。
* `back\app\bu\services\product_xic_service.py::_rt_window`、`_best_intensities`、`_scan_index_http_error`、`_indexed_ms2_spectrum`、`_extract_product_xics`。
* `back\app\bu\services\lists_service.py::_json_object`、`_pagination`、`_q_value_cutoff`。
* `back\app\bu\services\ms2_annotation_svc.py::_has_pfmb`、`_pfmb_block`、`_reader`。
* `back\app\pfmb\reader.py::PfmbAnnotationReader` 属于 PFMB binary reader 边界；BU route 不应直接读取 PFMB 二进制。

## 13.不要绕过的层

* 不要绕过 `spectrum_facade`、`xic_service`、`product_xic_service` 在 route 中直接读 mzML。
* 不要绕过 scan index 和 indexed reader 去全量扫描 mzML 计算 XIC。
* 不要绕过 `ms2_annotation_svc` 让 BU route 直接读 PFMB sidecar。
* 不要把 PFMB annotation 和 live mzML MS2 合并成同一种 evidence。
* 不要在前端页面中直接 `fetch` BU API；优先用 `front\src\features\bu\api\buClient.ts`。
* 不要把 `front\src\features\bu-viewer` 当当前主路径；当前 `App.tsx` 使用 `front\src\features\bu`。

## 14.常见修改场景

新增 BU overview 指标：

1. 后端优先扩展 `overview_service.py::get_overview` 或 `get_rt_mz_heatmap`。
2. route 保持薄层参数和 mode 检查。
3. 前端补 `BuOverviewOut` 或相关 DTO。
4. `BuOverviewPage` 负责页面状态和调用。

新增 match 证据图：

1. 确认数据是 MS1、MS2、XIC、product XIC、PFMB 还是 mobility。
2. 选择对应 service：`spectrum_facade`、`xic_service`、`product_xic_service`、`ms2_annotation_svc`、`mobility_service`。
3. 前端接入 `BuMatchDetailPage` 和对应组件。

新增 PFMB 页面行为：

1. 后端优先走 `ms2_annotation_svc`。
2. 前端优先走 `useBuPfmbEvidence`。
3. 可视化优先改 `BuPfmbHeatmap`、`BuPfmbAnnotationCard`、`BuEvidenceSummary`。

## 15.相关测试

本节列出开发时应参考或补充的测试入口；当前任务不运行这些测试。

* 后端 BU route/mode：`back\tests\test_bu_runtime_api.py`。
* BU lists/detail：`back\tests\test_bu_match_detail_display_fields.py`、`back\tests\test_bu_protein_sequence_resolver.py`。
* BU spectrum/XIC：`back\tests\test_bu_spectrum_api.py`、`back\tests\test_bu_product_xic_indexed.py`、`back\tests\test_bu_xic_isotopes.py`。
* BU PFMB：`back\tests\test_bu_ms2_annotation.py`、`front\tests\bu-pfmb-annotation.spec.ts`、`front\tests\bu-pfmb-visuals.spec.ts`、`front\tests\bu-pfmb-quality.spec.ts`。
* BU chromatogram/RT-mz：`back\tests\test_bu_chromatogram_summary.py`、`back\tests\test_chromatogram_route_matching.py`、`back\tests\test_bu_rt_mz_api.py`、`front\tests\bu-overview-chart-states.spec.ts`。
* BU product ion frontend：`front\tests\product-ion-selection.spec.ts`。
