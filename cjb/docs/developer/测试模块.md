# Testing

## 1.模块定位

Testing 模块说明 Viewer 当前测试分层：后端 pytest、前端 Playwright、`cs` 能力测验和性能验收脚本。它面向开发者选择合适的验证范围，不是用户操作手册。

## 2.核心职责

* 说明后端测试框架和测试目录。
* 说明前端 Playwright 测试目录和 mock 风格。
* 说明 `cs` 与 `back\tests` 的职责差异。
* 列出关键回归测试文件。
* 明确某些 `cs` 脚本依赖真实数据或 DB。

## 3.关键目录和文件

* `back\tests`：后端 pytest 测试目录。
* `front\tests`：前端 Playwright 测试目录。
* `cs`：能力测验、性能验收和与主业务低耦合的说明文档目录。
* `back\pyproject.toml`：后端依赖和 pytest `pythonpath` 配置。
* `front\package.json`：前端测试脚本和 Playwright 依赖。
* `front\playwright.config.ts`：Playwright 配置。
* `cs\目录说明.md`：`cs` 目录定位说明。
* `cs\性能测验约定.md`：指纹性能验收约定。

`back\pyproject.toml` 中的 pytest 配置包含 `pythonpath = ["."]`。`front\playwright.config.ts` 配置了 `testDir: "./tests"`，并通过 webServer 执行 `pnpm dev --host 127.0.0.1 --port 4173` 启动前端测试服务。

## 4.核心数据流

1. 后端单元测试直接 import `app` 下模块，常用 pytest monkeypatch 隔离 DB、文件或外部工具。
2. 前端 Playwright 测试运行页面或工具函数，常用 route mock 模拟 API。
3. `cs` 脚本用于真实数据、性能或人工验收场景。
4. 与导入、RAW、PFMB、mzML 相关改动应优先选择对应后端测试，再补前端回归或 `cs` 验收。

## 5.关键API或关键组件

重要测试文件示例：

* `back\tests\test_import_planner.py`
* `back\tests\test_import_planner_raw.py`
* `back\tests\test_import_jobs_raw_conversion.py`
* `back\tests\test_raw_conversion_thermo.py`
* `back\tests\test_raw_mzml_mapping.py`
* `back\tests\test_mzml_scan_index.py`
* `back\tests\test_mzml_spectra_api.py`
* `back\tests\test_bu_spectrum_api.py`
* `back\tests\test_bu_product_xic_indexed.py`
* `back\tests\test_bu_ms2_annotation.py`
* `back\tests\test_bu_chromatogram_summary.py`
* `back\tests\test_chromatogram_route_matching.py`
* `front\tests\bu-match-detail.spec.ts`
* `front\tests\bu-pfmb-visuals.spec.ts`
* `front\tests\spectra-only-scan-relations.spec.ts`
* `front\tests\api-error.spec.ts`

## 6.和其他模块的关系

Testing 覆盖 Import、RawFile、SpectrumDataAccess、DerivedDataIndex、BottomUp、Visualization 和 BackendAPI。`cs` 还与 AGENTS.md 中的指纹性能、PFMB 语义和能力验收约束相关。

各模块文档只列 2 到 5 个局部测试入口；完整测试分层和补测策略以本文件为准。

## 7.扩展和维护建议

新增后端 service 或 adapter 时应补 `back\tests` 中的 pytest。新增前端交互或错误态时应补 `front\tests` 中的 Playwright。新增真实性能或真实数据验收时放在 `cs`，并优先使用中文文件名。不要把需要真实 DB 或真实大文件的脚本混入普通快速单元测试。

## 8.当前限制和注意事项

* 本轮文档创建不运行测试、构建或导入。
* `cs` 脚本很多依赖真实数据或 DB，不是普通快速单元测试。
* 未找到 Vitest 单元测试配置。
* 后端测试大量使用 monkeypatch，不能把 mock 结果直接等同于真实数据验收。
* 前端 Playwright 测试大量使用 route mock，真实后端集成仍需单独验证。

## 9.测试分层矩阵

| 模块 | 后端测试文件 | 前端测试文件 | cs验收或性能脚本 | 常用mock方式 | 是否依赖真实数据或DB |
|---|---|---|---|---|---|
| Import | `back\tests\test_import_planner.py`、`test_import_jobs_layout.py`、`test_dataset_ingest_root.py`、`test_dataset_metadata_fingerprint.py` | `front\tests\api-error.spec.ts` | `cs\指纹性能测验.py`、`cs\性能测验约定.md` | pytest `tmp_path`、fake session、`monkeypatch` | pytest 通常不依赖真实 DB；`cs` 性能验收依赖真实数据路径 |
| ImportMiddleware | `back\tests\test_import_planner.py`、`test_import_planner_raw.py`、`test_import_jobs_derived_data.py` | 可用 Playwright route mock 覆盖导入 UI 错误态，当前未找到专项 spec | `cs\目录说明.md` | planner fixture、`monkeypatch` | 普通 pytest 不依赖真实数据；`cs` 视脚本而定 |
| RawFile | `back\tests\test_raw_conversion_discovery.py`、`test_raw_converter_discovery.py`、`test_raw_conversion_thermo.py`、`test_import_jobs_raw_conversion.py`、`test_raw_mzml_mapping.py` | 当前未找到 RAW 专项前端 spec | 无专项；可按 `cs` 约定补真实转换验收 | fake converter、fake subprocess、临时 RAW/mzML stub | pytest 不运行真实 converter；真实 RAW 转换验收依赖本机工具和数据 |
| SpectrumDataAccess | `back\tests\test_mzml_scan_reader.py`、`test_mzml_scan_index.py`、`test_mzml_spectra_api.py`、`test_spectrum_memory.py` | `front\tests\spectra-only-peak-annotations.spec.ts`、`front\tests\spectra-only-scan-relations.spec.ts` | 可按 `cs` 增加真实 mzML 验收 | fake reader、stub indexed mzML、`monkeypatch` | 普通测试多用 stub；真实 mzML 性能/兼容需单独验收 |
| DerivedDataIndex | `back\tests\test_backfill_dataset_derived_data.py`、`test_import_jobs_derived_data.py`、`test_mzml_scan_index.py`、`test_bu_chromatogram_summary.py` | `front\tests\api-error.spec.ts`、`front\tests\bu-overview-chart-states.spec.ts`、`front\tests\bu-match-detail.spec.ts` | 可按 `cs` 增加派生数据人工验收 | fake session、fake path resolver、禁止生成 guard | pytest 使用临时文件；真实 backfill 不应混入快速单元测试 |
| BottomUp | `back\tests\test_bu_spectrum_api.py`、`test_bu_product_xic_indexed.py`、`test_bu_ms2_annotation.py`、`test_bu_chromatogram_summary.py`、`test_bu_rt_mz_api.py`、`test_bu_runtime_api.py` | `front\tests\bu-match-detail.spec.ts`、`bu-evidence-summary.spec.ts`、`product-ion-selection.spec.ts` | `cs\PFMB矩阵接口验证.py`、`cs\PFMB接口性能测验.py` | fake API response、Playwright `page.route("**/api/v1/**", ...)`、pytest monkeypatch | pytest/front mock 不等于真实 DB；`cs` PFMB 脚本偏真实数据 |
| TopDown | `back\tests\test_prsm_files.py`、`test_mzml_spectra_api.py` | 当前未找到 PrSM detail 专项 Playwright spec | 可按 `cs` 增加 TopPIC/PrSM bundle 验收 | PrSM temp files、API function monkeypatch | 当前 TD route 专项覆盖不足；新增字段应补 API 测试 |
| Visualization | `back\tests\test_bu_ms2_annotation.py`、`test_bu_chromatogram_summary.py` 提供数据语义回归 | `front\tests\bu-pfmb-visuals.spec.ts`、`bu-spectrum-label-layout.spec.ts`、`spectra-only-peak-annotations.spec.ts` | `cs\LCMS三维验收说明.md` | Playwright route mock、DOM/SVG 断言 | 前端多为 mock；3D/真实数据需人工或专项验收 |
| UI | `back\tests\test_datasets_api_modes.py`、`test_dataset_delete_cancel_import.py` | `front\tests\api-error.spec.ts`、`bu-match-detail.spec.ts`、`bu-overview-chart-states.spec.ts` | 无固定 UI `cs` 脚本 | Playwright route mock、loading/error state mock | 不依赖真实 DB；真实后端集成需另跑 |
| BinaryFormat | `back\tests\test_pfmb_sidecar_prepare.py`、`test_pfmb_v2_reference.py`、`test_bu_ms2_annotation.py` | `front\tests\bu-pfmb-annotation.spec.ts`、`bu-pfmb-visuals.spec.ts`、`bu-pfmb-quality.spec.ts` | `cs\test_pfmb_reader.py`、`cs\test_index_reader.py`、`cs\test_ms2_annotation.py`、`cs\PFMB字段语义验证.py` | fake sidecar、sample header、reference skipif | 部分 reference 测试和 `cs` 脚本依赖交付数据 |
| ConfigAndDeployment | `back\tests\test_raw_converter_discovery.py`、`test_pfmb_sidecar_prepare.py`、`test_import_jobs_raw_conversion.py` | `front\playwright.config.ts` 配置 `front\tests` 运行方式 | `cs\目录说明.md` | monkeypatch Settings 字段、fake executable path | 普通测试不依赖真实工具；实际启动脚本/工具路径需人工确认 |

## 10.后端测试说明

导入和中间件：

* `back\tests\test_import_planner.py`：覆盖 import planner 对不同 dataset layout 的识别。
* `back\tests\test_import_planner_raw.py`：覆盖 RAW/mzML-only planner 分支。
* `back\tests\test_import_jobs_raw_conversion.py`：覆盖 import job 与 RAW conversion service 的编排。
* `back\tests\test_import_jobs_layout.py`、`test_import_jobs_derived_data.py`：覆盖 layout/finalize/派生数据调用边界。

RAW 和 mzML：

* `back\tests\test_raw_conversion_thermo.py`：覆盖 ThermoRawFileParser 命令、gzip/indexListOffset 校验和输出定位。
* `back\tests\test_raw_conversion_discovery.py`、`test_raw_converter_discovery.py`：覆盖 RAW 文件发现、converter discovery 和 same-stem mzML 复用策略。
* `back\tests\test_mzml_scan_index.py`：覆盖 scan index `.npz + .json` 生成、读取和 stale 判断。
* `back\tests\test_mzml_scan_reader.py`：覆盖 indexed mzML reader、native id、缓存和 unsupported 情况。
* `back\tests\test_mzml_spectra_api.py`：覆盖 mzML spectrum API、scan index endpoint 和 derived-data 错误。

BU、PFMB 和派生数据：

* `back\tests\test_bu_spectrum_api.py`：覆盖 BU spectrum API。
* `back\tests\test_bu_product_xic_indexed.py`：覆盖 indexed product XIC。
* `back\tests\test_bu_ms2_annotation.py`：覆盖 PFMB slots、annotation 和 matrix service/API。
* `back\tests\test_bu_chromatogram_summary.py`：覆盖 chromatogram summary 生成、读取和缺失/stale 行为。
* `back\tests\test_backfill_dataset_derived_data.py`：覆盖 derived data backfill service 和 CLI 参数行为。
* `back\tests\test_pfmb_sidecar_prepare.py`：覆盖 PFMB sidecar detection、generation 和 index builder。

TopDown：

* `back\tests\test_prsm_files.py`：覆盖 `back\app\services\prsm_files.py` 的 PrSM 文件发现和读取。
* 当前未找到 `proteins.py`、`proteoforms.py`、`prsms.py` 的专项 route 测试；新增 TD list/detail 字段时应补后端 API 测试。

## 11.前端测试说明

Playwright 配置：

* `front\playwright.config.ts`：`testDir: "./tests"`，webServer 使用 `pnpm dev --host 127.0.0.1 --port 4173`。
* `front\package.json`：`test:e2e` 对应 `playwright test`。

主要前端测试文件：

* `front\tests\bu-match-detail.spec.ts`：BU match detail、product ion、error/local state 和 spectrum 交互。
* `front\tests\bu-pfmb-annotation.spec.ts`：PFMB annotation 行为。
* `front\tests\bu-pfmb-visuals.spec.ts`：PFMB heatmap/visual regression。
* `front\tests\bu-pfmb-quality.spec.ts`：PFMB quality summary。
* `front\tests\product-ion-selection.spec.ts`：product ion 选择状态。
* `front\tests\spectra-only-peak-annotations.spec.ts`：spectra-only peak annotation。
* `front\tests\spectra-only-scan-relations.spec.ts`：spectra-only scan relation。
* `front\tests\api-error.spec.ts`：API error 分类、derived-data error 和 retry 策略。

常用前端 mock：

* 多数页面测试使用 `page.route("**/api/v1/**", ...)` mock API response。
* 新 UI 页面应补 route mock、loading state、empty state、error state。
* Playwright route mock 不能证明真实后端 schema 已正确接通；跨层字段变化仍需后端测试配合。

## 12.cs能力测验说明

`cs` 是能力测验、性能验收和人工验收目录，不替代 `back\tests` 的普通 pytest，也不替代 `front\tests` 的 Playwright。

* `cs\目录说明.md`：说明 `cs` 目录定位和使用边界。
* `cs\性能测验约定.md`：说明指纹性能目标和基准数据约定。
* `cs\指纹性能测验.py`：指纹性能入口，依赖真实基准数据路径或 `VIEWER_BENCH_DATASET_ROOT`。
* `cs\PFMB矩阵接口验证.py`、`PFMB接口性能测验.py`、`PFMB字段语义验证.py`：偏真实 PFMB 数据和接口语义验收。
* `cs\LCMS三维验收说明.md`：LCMS 3D 人工/视觉验收说明。

`cs` 脚本可能访问真实数据、DB 或本地工具路径。执行前应确认数据路径、环境变量和是否会产生输出；本轮文档修订不运行这些脚本。

## 13.新增功能补测试建议

新 API：

* 后端补 `back\tests` 中的 API 或 service 测试，覆盖 success、not found、invalid parameter 和 expected error。
* 前端补 Playwright route mock，覆盖 loading、empty、error 和主要交互。
* 如果新增字段跨前后端，后端 schema 测试和前端 type/UI 测试都要更新。

新导入格式：

* 补 planner 测试，例如 `test_import_planner.py` 或 `test_import_planner_raw.py`。
* 补 adapter 或 root/fingerprint 测试，例如 `test_dataset_ingest_root.py`、`test_dataset_metadata_fingerprint.py`。
* 如果涉及导入 finalize，补 `test_import_jobs_layout.py` 或 `test_import_jobs_derived_data.py`。

新 RAW 能力：

* 补 discovery 测试：`test_raw_conversion_discovery.py` 或 `test_raw_converter_discovery.py`。
* 补 converter 命令、reuse、failure、indexed mzML 校验：`test_raw_conversion_thermo.py`。
* 不在普通测试中运行真实 ThermoRawFileParser；真实转换验收应单独说明。

新谱图访问：

* 补 scan index 或 mzML reader 测试：`test_mzml_scan_index.py`、`test_mzml_scan_reader.py`。
* 补 API 测试：`test_mzml_spectra_api.py` 或 BU service 测试。
* 前端补 spectra-only 或 BU match detail Playwright route mock。

新 PFMB 能力：

* 补 reader/index/sidecar 测试：`test_pfmb_sidecar_prepare.py`、`test_pfmb_v2_reference.py`。
* 补 annotation service/API 测试：`test_bu_ms2_annotation.py`。
* 补前端 visual 测试：`bu-pfmb-annotation.spec.ts`、`bu-pfmb-visuals.spec.ts`、`bu-pfmb-quality.spec.ts`。
* 真实语义或性能验收放 `cs\PFMB字段语义验证.py` 或 `cs\PFMB接口性能测验.py`。

新 UI 页面：

* 优先补 Playwright route mock 测试。
* 覆盖页面入口 route、数据加载、空态、错误态和关键交互。
* 不把 Playwright mock 结果当作真实 DB/API 集成证明。

## 14.内部测试helper边界

* `back\tests` 内 `_Session`、`_Result`、`_run`、`_dataset`、`_install_paths` 等下划线 helper 是测试内部实现，不建议业务代码调用。
* `front\tests` 内 mock data builders 和 `page.route` handler 是测试内部实现，不是前端运行时代码入口。
* `cs` 脚本中的 `check`、`main`、路径常量和真实数据参数只服务能力验收，不应被主业务模块 import。

## 15.不要绕过的层

* 不要用 `cs` 真实数据脚本替代普通单元测试。
* 不要只补前端 route mock，而不补后端 schema/service/API 测试。
* 不要把 monkeypatch/fake session 的通过结果写成真实 DB 已验证。
* 不要在普通 pytest 中调用真实 RAW converter、真实导入或派生数据生成；这类验证应单独标注为人工或能力验收。
* 不要把 Playwright webServer 启动当作生产部署验证。

## 16.常见修改场景

* 新增 `Import` layout：先补 `test_import_planner.py`，再补 adapter/import job 测试，必要时补 `cs` 验收。
* 修改 RAW reuse 规则：补 `test_raw_conversion_discovery.py`、`test_raw_conversion_thermo.py` 和 `test_import_jobs_raw_conversion.py`。
* 修改 scan index 格式：补 `test_mzml_scan_index.py` 和 `test_mzml_spectra_api.py`，前端补 derived-data error mock。
* 修改 BU match detail 证据：补 `test_bu_spectrum_api.py`、`test_bu_product_xic_indexed.py`、`test_bu_ms2_annotation.py` 和 `bu-match-detail.spec.ts`。
* 修改 PFMB sidecar 版本：补 `test_pfmb_sidecar_prepare.py`、`test_bu_ms2_annotation.py`、PFMB Playwright spec 和必要的 `cs` reference 验收。
* 修改配置字段：补 Settings 或 discovery 测试；若当前没有专项配置测试，至少补使用方测试，避免只改 `.env.example`。
