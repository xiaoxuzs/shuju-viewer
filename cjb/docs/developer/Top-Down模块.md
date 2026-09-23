# TopDown

## 1.模块定位

TopDown 模块负责 TopPIC/TopFD HTML 和 PrSM bundle 导入后的 protein、proteoform、PrSM 浏览，以及 TD PrSM 详情页中的序列、fragmentation 和谱图证据。

## 2.核心职责

* 导入 TopPIC HTML 和 PrSM bundle 数据。
* 写入 protein、proteoform、identification_match 和 relation mapping。
* 提供 protein、proteoform、PrSM 列表和详情 API。
* 通过兼容层合成 cutoff。
* 在 PrSM 详情页展示 annotated protein、matched peaks、MS1/MS2 谱图和 fragmentation。
* 在谱图来源上支持 TopFD JS 和 mzML scan 两条路径。

## 3.关键目录和文件

* `back\app\ingest\universal_toppic_adapter.py`：TopPIC HTML 导入 adapter。
* `back\app\ingest\universal_prsm_js_adapter.py`：PrSM bundle 导入 adapter。
* `back\app\api\v1\proteins.py`：TD protein list/detail API。
* `back\app\api\v1\proteoforms.py`：TD proteoform list/detail API。
* `back\app\api\v1\prsms.py`：TD PrSM list/detail API。
* `back\app\api\v1\universal_compat.py`：dataset、cutoff、PrSM detail 读取兼容层。
* `back\app\api\v1\spectra.py`：TopFD JS MS1/MS2 谱图 API。
* `back\app\api\v1\mzml_spectra.py`：mzML scan 谱图 API。
* `front\src\pages\PrsmDetailPage.tsx`：TD PrSM 详情页。
* `front\src\features\prsm`：TD 谱图、sequence、fragmentation 和 parsing 组件。

## 4.核心数据流

1. Import 模块识别 TopPIC HTML 或 PrSM bundle。
2. `ingest_universal_toppic` 或 `ingest_universal_prsm_js` 写入 universal schema。
3. `identification_matches.extra_metadata.source_cutoff` 保存来源 cutoff 信息。
4. TD list API 通过兼容层和 raw SQL 查询 proteins、proteoforms、PrSMs。
5. `get_prsm` 读取 DB row，并通过 `load_prsm_detail` 从磁盘 detail path 读取 PrSM detail。
6. `PrsmDetailPage` 请求 PrSM detail 和 dataset capabilities。
7. 如果 `spectra_source` 是 `mzml_memory`，前端使用 mzML scan API；否则使用 TopFD JS spectra API。
8. 前端渲染 sequence、matched peaks、MS1/MS2 和 fragmentation。

## 5.关键API或关键组件

* `GET /api/v1/datasets/{slug}/cutoffs/{cutoff}/proteins`
* `GET /api/v1/datasets/{slug}/cutoffs/{cutoff}/proteins/{protein_id}`
* `GET /api/v1/datasets/{slug}/cutoffs/{cutoff}/proteoforms`
* `GET /api/v1/datasets/{slug}/cutoffs/{cutoff}/proteoforms/{proteoform_id}`
* `GET /api/v1/datasets/{slug}/cutoffs/{cutoff}/prsms`
* `GET /api/v1/datasets/{slug}/cutoffs/{cutoff}/prsms/{prsm_id}`
* `GET /api/v1/datasets/{slug}/spectra/ms1/{spec_id}`
* `GET /api/v1/datasets/{slug}/spectra/ms2/{spec_id}`
* `PrsmDetailPage`、`SpectrumChart`、`SequenceView`、`FragmentationView`、`MatchedPeaksTable`

## 6.和其他模块的关系

TopDown 依赖 ImportMiddleware 导入 TopPIC/PrSM 数据，依赖 DataModelStorage 存储实体和 matches，依赖 SpectrumDataAccess 读取 mzML 或 TopFD JS 谱图，依赖 Visualization 展示详情页。

TD 查询逻辑当前主要位于 `back\app\api\v1\proteins.py`、`back\app\api\v1\proteoforms.py`、`back\app\api\v1\prsms.py` 和 `back\app\api\v1\universal_compat.py`，当前未形成 BU 那样清晰独立的 service 目录。这是当前源码状态说明，不是架构建议。

当前 TD 查询实现主要是 FastAPI route 加 `universal_compat` 兼容层，查询使用 SQLAlchemy `text`/raw SQL，并大量读取 JSONB `extra_metadata` 字段。PrSM detail 读取通过 `detail_path` 调用 `prsm_files`/`universal_compat.load_prsm_detail`，TopPIC/TopFD JS 数据解析路径包括 `universal_toppic_adapter.py` 和 `back\app\services\js_parser.py`。这些是当前实现状态，不代表推荐把未来 TD 逻辑继续堆在 route 中。

参见：`谱图数据访问.md`、`可视化模块.md`。

## 7.扩展和维护建议

新增 TD 导入能力应优先扩展 adapter 和兼容层。新增 TD 页面字段时需同时检查 API schema、route SQL、前端 DTO 和 `front\src\features\prsm\parse.ts`。新增谱图来源时要明确 capabilities 中的 `spectra_source`，不要直接在页面内猜测文件路径。

## 8.当前限制和注意事项

* cutoff 来自兼容层和 `identification_matches.extra_metadata.source_cutoff`，当前未找到独立 cutoffs 表。
* TD 没有像 BU 那样清晰独立的 service 包，很多逻辑在 route 和 adapter 内。
* PrSM detail 依赖磁盘 `detail_path`，不是全部 detail 都在数据库中。
* TD 谱图有 TopFD JS 和 mzML scan 两条路径，文档应明确区分。
* TD 前端专项测试覆盖看起来弱于 BU，正式调整前应补充验证。

## 9.可复用入口

后端 TD API 入口：

* `back\app\api\v1\proteins.py::list_proteins`：`GET /api/v1/datasets/{slug}/cutoffs/{cutoff}/proteins`，返回 `Page[ProteinListItemOut]`。
* `back\app\api\v1\proteins.py::get_protein`：`GET /api/v1/datasets/{slug}/cutoffs/{cutoff}/proteins/{protein_id}`，返回 `ProteinDetailOut`。
* `back\app\api\v1\proteoforms.py::list_proteoforms`：`GET /api/v1/datasets/{slug}/cutoffs/{cutoff}/proteoforms`，返回 `Page[ProteoformListItemOut]`。
* `back\app\api\v1\proteoforms.py::get_proteoform`：`GET /api/v1/datasets/{slug}/cutoffs/{cutoff}/proteoforms/{proteoform_id}`，返回 `ProteoformDetailOut`。
* `back\app\api\v1\prsms.py::list_prsms`：`GET /api/v1/datasets/{slug}/cutoffs/{cutoff}/prsms`，返回 `Page[PrsmListItemOut]`。
* `back\app\api\v1\prsms.py::get_prsm`：`GET /api/v1/datasets/{slug}/cutoffs/{cutoff}/prsms/{prsm_id}`，返回 `PrsmDetailOut`。
* `back\app\api\v1\spectra.py::ms1_spectrum`：`GET /api/v1/datasets/{slug}/spectra/ms1/{spec_id}`，读取 TopFD JS MS1 spectrum。
* `back\app\api\v1\spectra.py::ms2_spectrum`：`GET /api/v1/datasets/{slug}/spectra/ms2/{spec_id}`，读取 TopFD JS MS2 spectrum。

兼容层和 schema：

* `back\app\api\v1\universal_compat.py::require_dataset`：按 slug 读取 dataset row，route 中不要重复手写 dataset lookup。
* `back\app\api\v1\universal_compat.py::require_cutoff`、`cutoff_id`：规范化 TD cutoff 参数。
* `back\app\api\v1\universal_compat.py::source_cutoff_filter_sql`：生成基于 `identification_matches.extra_metadata.source_cutoff` 的 SQL 条件。
* `back\app\api\v1\universal_compat.py::prsm_list_select_sql`：PrSM 列表和详情关联查询复用的 SQL 片段。
* `back\app\api\v1\universal_compat.py::load_prsm_detail`：从 `detail_path` 读取 PrSM detail、annotated protein 和 matched peaks。
* `back\app\schemas\protein.py::ProteinListItemOut`、`ProteinDetailOut`、`ProteoformListItemOut`、`ProteoformDetailOut`、`PrsmListItemOut`、`PrsmDetailOut`：TD route response schema。

TD 导入和解析入口：

* `back\app\ingest\universal_toppic_adapter.py::ingest_universal_toppic`：TopPIC HTML 导入入口。
* `back\app\ingest\universal_toppic_adapter.py::assign_toppic_runs_from_prsm_headers`：根据 PrSM headers 分配 TopPIC runs。
* `back\app\ingest\universal_prsm_js_adapter.py::ingest_universal_prsm_js`：PrSM bundle 导入入口。
* `back\app\services\prsm_files.py::iter_prsm_files`、`prsm_paths_by_id`、`load_prsm_document`、`get_prsm_root`：PrSM detail 文件发现和读取入口。
* `back\app\services\js_parser.py::load_js_object`、`load_js_object_text`：解析 `.js`/`.json`/`.txt` 形式的 PrSM detail 文档。

前端 TD 入口：

* `front\src\api\client.ts::fetchProteins`、`fetchProtein`、`fetchProteoforms`、`fetchProteoform`、`fetchPrsms`、`fetchPrsm`：TD 列表和详情 API client。
* `front\src\api\client.ts::fetchMs1Spectrum`、`fetchMs2Spectrum`：TopFD JS spectrum client。
* `front\src\api\client.ts::fetchMzmlSpectrum`：mzML scan spectrum client，用于 `spectra_source === "mzml_memory"` 的 TD detail。
* `front\src\pages\PrsmDetailPage.tsx::PrsmDetailPage`：TD PrSM 详情页面组合入口。
* `front\src\pages\PrsmDetailPage.tsx::useModalHeight`：页面内部 hook，只服务 PrSM spectrum modal 布局。
* `front\src\features\prsm\SpectrumChart.tsx::SpectrumChart`、`SequenceView.tsx::SequenceView`、`FragmentationView.tsx::FragmentationView`、`MatchedPeaksTable.tsx::MatchedPeaksTable`、`MatchedPeakSpectrumPanel.tsx::MatchedPeakSpectrumPanel`：TD detail 可视化组件。
* `front\src\features\prsm\parse.ts::parseAnnotatedProtein`、`parseMsPeaks`、`parseRawSpectrum`、`findMatchedEnvelope`、`splitDataForDetail`：PrSM detail 和 spectrum response 的前端解析入口。

## 10.调用链

TD 列表页调用链：

1. `front\src\pages\ProteinsPage.tsx`、`ProteoformsPage.tsx`、`PrsmsPage.tsx` 调用 `front\src\api\client.ts` 中的 `fetchProteins`、`fetchProteoforms`、`fetchPrsms`。
2. 后端进入 `back\app\api\v1\proteins.py::list_proteins`、`proteoforms.py::list_proteoforms` 或 `prsms.py::list_prsms`。
3. route 先通过 `require_dataset` 读取 dataset，通过 `require_cutoff`/`cutoff_id` 处理 cutoff。
4. 当前实现主要在 route 内使用 SQLAlchemy `text` 和 raw SQL 查询 universal tables，并通过 `source_cutoff_filter_sql` 过滤来源 cutoff。
5. response 使用 `Page[...]` 和 `back\app\schemas\protein.py` 中的 TD schema 返回给前端表格页。

PrSM 详情调用链：

1. `front\src\pages\PrsmDetailPage.tsx::PrsmDetailPage` 调用 `front\src\api\client.ts::fetchPrsm`。
2. 后端进入 `back\app\api\v1\prsms.py::get_prsm`，先通过 `require_dataset`、`require_cutoff` 找到合法 dataset/cutoff。
3. `get_prsm` 读取 PrSM DB row，并调用 `back\app\api\v1\universal_compat.py::load_prsm_detail` 读取 `detail_path` 指向的 PrSM detail file。
4. `load_prsm_detail` 依赖 `back\app\services\prsm_files.py::load_prsm_document` 和 `back\app\services\js_parser.py::load_js_object`。
5. 前端 `PrsmDetailPage` 使用 `parseAnnotatedProtein`、`parseMsPeaks`、`parseRawSpectrum` 组装 sequence、fragmentation、matched peaks、MS1/MS2 spectrum。

TD 谱图调用链：

* TopFD JS 路径：`PrsmDetailPage` 根据 `ms1_ids`/`ms2_ids` 调用 `fetchMs1Spectrum` 或 `fetchMs2Spectrum`，后端进入 `back\app\api\v1\spectra.py::ms1_spectrum` 或 `ms2_spectrum`。这条路径读取 TopFD JS spectrum，不应按 mzML scan number 处理。
* mzML scan 路径：当 dataset capabilities 中 `spectra_source === "mzml_memory"` 时，`PrsmDetailPage` 使用 `ms1_scans`/`ms2_scans` 和 `run_id` 调用 `fetchMzmlSpectrum`，进入 mzML scan API。不要把 TopFD JS `spec_id` 和 mzML scan number 混用。

TD 导入调用链：

* TopPIC HTML 导入进入 `back\app\ingest\universal_toppic_adapter.py::ingest_universal_toppic`，PrSM detail 文件通过 `back\app\services\prsm_files.py` 发现和读取，run 归属可由 `assign_toppic_runs_from_prsm_headers` 补齐。
* PrSM bundle 导入进入 `back\app\ingest\universal_prsm_js_adapter.py::ingest_universal_prsm_js`，通过 `prsm_bundle_prsm_directory`、`iter_prsm_files` 和 `load_prsm_document` 读取 bundle 内 PrSM detail。

## 11.新增功能接入方式

新增 TD 列表字段：

* 先确认字段来源：数据库列、`extra_metadata` JSONB，还是 detail file。
* 后端需要同步修改对应 route SQL：`list_proteins`、`list_proteoforms` 或 `list_prsms`。
* schema 需要同步修改 `back\app\schemas\protein.py` 中的 `ProteinListItemOut`、`ProteoformListItemOut` 或 `PrsmListItemOut`。
* 前端 type 需要同步修改 `front\src\api\types.ts`，页面展示修改 `ProteinsPage.tsx`、`ProteoformsPage.tsx` 或 `PrsmsPage.tsx`。

新增 PrSM 详情字段：

* 先判断字段来自 DB row 还是 detail file。DB row 字段通常在 `back\app\api\v1\prsms.py::get_prsm` 的 SQL/select 和 `PrsmDetailOut` 中处理；detail file 字段应通过 `load_prsm_detail` 和 `front\src\features\prsm\parse.ts` 转成前端结构。
* 不要在 `PrsmDetailPage` 内临时遍历原始 JSON 来绕过 `parse.ts`，否则 sequence、fragmentation、matched peaks 的字段语义会分散。

新增 TD 谱图证据：

* 先判断证据属于 TopFD JS spectrum 还是 mzML scan spectrum。
* TopFD JS 证据接 `front\src\api\client.ts::fetchMs1Spectrum` / `fetchMs2Spectrum` 和 `back\app\api\v1\spectra.py`。
* mzML scan 证据接 `front\src\api\client.ts::fetchMzmlSpectrum` 和 mzML scan API，不要把 scan number 当作 TopFD `spec_id`。

新增 TD 后端复杂查询：

* 当前 TD 没有 BU 那样清晰独立的 service 目录，这是源码现状，不是架构建议。
* 若新增逻辑只是列字段映射，可局部扩展 route SQL 和 schema。
* 若新增跨表聚合、复用规则或复杂过滤，建议新增 service 层或小型查询 helper，避免继续把复杂逻辑堆在 `proteins.py`、`proteoforms.py`、`prsms.py` route 中。

## 12.内部实现边界

* `back\app\api\v1\universal_compat.py` 中的 SQL helper 是当前 TD 兼容层复用点，但不要把它当作长期 service 层替代品。
* `back\app\ingest\universal_toppic_adapter.py::_RunRegistry`、`_create_dataset`、`_import_proteins_and_forms`、`_insert_protein`、`_insert_proteoform`、`_insert_relation`、`_import_fast_prsm_summaries`、`_extract_proteoform_mass` 是 adapter 内部实现，不建议跨模块直接调用。
* `back\app\ingest\universal_prsm_js_adapter.py::_json`、`_accession_from_sequence_name` 以及函数内部的 `_get_or_create_run`、`_get_or_create_protein`、`_get_or_create_proteoform` 是 adapter 内部实现，不建议跨模块直接调用。
* `front\src\pages\PrsmDetailPage.tsx::useModalHeight` 是页面内部 UI helper，不建议作为通用 hook 对外复用。
* `front\src\features\prsm\parse.ts` 是前端 PrSM detail 解析边界；页面和组件不要重复实现一套 PrSM detail parser。

## 13.不要绕过的层

* TD route 不要绕过 `require_dataset` 直接按 slug 手写 dataset 查询。
* cutoff 过滤不要绕过 `require_cutoff`、`cutoff_id` 和 `source_cutoff_filter_sql`，否则 TD 列表和详情 cutoff 语义容易不一致。
* PrSM detail 不要绕过 `load_prsm_detail` 直接在 route 中读取任意路径。
* 前端不要绕过 `front\src\api\client.ts` 拼接 TD API URL。
* 前端不要绕过 `front\src\features\prsm\parse.ts` 直接消费原始 `annotated_protein` 或 `ms_peaks`。
* 谱图路径不要混用 TopFD JS `spec_id` 与 mzML `run_id + scan_number`。

## 14.常见修改场景

* 给 proteins 列表增加字段：改 `back\app\api\v1\proteins.py::list_proteins` SQL、`back\app\schemas\protein.py::ProteinListItemOut`、`front\src\api\types.ts` 和 `front\src\pages\ProteinsPage.tsx`。
* 给 proteoform 详情增加 PrSM 摘要字段：改 `back\app\api\v1\proteoforms.py::get_proteoform` 中 PrSM select、`PrsmListItemOut` 或 `ProteoformDetailOut`，再改 `ProteoformDetailPage.tsx`。
* 给 PrSM 详情增加 detail file 字段：改 `load_prsm_detail` 使用的 detail 读取路径、`PrsmDetailOut`、`front\src\features\prsm\parse.ts` 和 `PrsmDetailPage.tsx`。
* 新增 TopPIC 导入字段：先改 `back\app\ingest\universal_toppic_adapter.py::ingest_universal_toppic` 写入，再补对应 TD route SQL/schema/frontend。
* 新增 PrSM bundle 字段：先改 `back\app\ingest\universal_prsm_js_adapter.py::ingest_universal_prsm_js` 和 `back\app\services\prsm_files.py` 相关读取路径，再补 API/schema/frontend。

## 15.相关测试

* `back\tests\test_prsm_files.py`：覆盖 `back\app\services\prsm_files.py` 对 PrSM 文件后缀、路径映射和 wrapper normalize 的处理。
* `back\tests\test_mzml_spectra_api.py`：覆盖 mzML scan API、scan index missing/stale 错误和 backfill command 行为，可作为 TD mzML scan 证据路径的回归参考。
* `front\tests\api-error.spec.ts`：覆盖前端 API error 分类，PrSM detail 中 mzML indexed error 展示依赖同一错误解析层。
* 当前未找到专门覆盖 `back\app\api\v1\proteins.py`、`proteoforms.py`、`prsms.py` 的 TD route 测试；新增 TD route 字段或复杂查询时应补后端 API 测试。
* 当前未找到专门覆盖 `front\src\pages\PrsmDetailPage.tsx` 的 Playwright 测试；新增 PrSM detail 交互或谱图证据时应补前端 route mock 测试。
