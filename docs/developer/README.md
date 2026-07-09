# Developer Documentation

本目录保存 Viewer 当前源码状态下的开发者文档。文档面向后续开发者，用于理解项目结构、模块职责、关键文件、数据流、扩展点和限制，不是用户操作手册，也不是产品功能承诺。

## 推荐阅读顺序

1. `ProjectOverview.md`
2. `DataModelStorage.md`
3. `BackendAPI.md`
4. `Import.md` 和 `ImportMiddleware.md`
5. `SpectrumDataAccess.md` 和 `DerivedDataIndex.md`
6. `BottomUp.md` 或 `TopDown.md`
7. `Visualization.md`
8. `RawFile.md`、`BinaryFormat.md`、`ConfigAndDeployment.md`、`Testing.md`

## 技术栈速览

* 前端：React 18、Vite、TypeScript、React Router、TanStack Query 和 axios。
* 前端 UI 和样式：Tailwind CSS、Radix 相关组件、lucide-react、class-variance-authority、clsx 和 tailwind-merge。
* 可视化：D3、SVG、Three.js 和 WebGL。
* 后端：FastAPI、Pydantic、SQLAlchemy、PostgreSQL 和 psycopg。
* 配置：`pydantic-settings` 管理后端 `Settings`。
* 谱图和派生数据：pyteomics、NumPy、`.npz`、`.json` 和 `.viewer-derived`。
* 导入格式：DIA-NN parquet、TopPIC、PrSM bundle、mzML 和 Thermo RAW。
* 测试：pytest、Playwright 和 `cs` 能力测验。

## 模块索引

* `ProjectOverview.md`：先读它了解 Viewer 的整体架构、核心对象和三类 dataset mode。
* `UI.md`：需要改前端入口、路由、页面组织、请求封装或通用状态组件时阅读。
* `Visualization.md`：需要改谱图、XIC、chromatogram、PFMB heatmap、sequence coverage 或 LCMS 3D 时阅读。
* `Import.md`：需要改导入 API、导入任务状态、fingerprint 或导入后派生数据触发时阅读。
* `ImportMiddleware.md`：需要新增外部格式、调整 planner、detector 或 ingest adapter 时阅读。
* `BottomUp.md`：需要改 DIA-NN、BU match、PFMB、XIC、product ion XIC 或 BU 证据页时阅读。
* `TopDown.md`：需要改 TopPIC、PrSM、proteoform、TD cutoff 或 PrSM 详情页时阅读。
* `RawFile.md`：需要改 Thermo RAW 发现、转换、same-stem mzML 复用或 RAW-only 导入时阅读。
* `BackendAPI.md`：需要新增或调整 HTTP API、分页、错误处理或 router 注册时阅读。
* `DataModelStorage.md`：需要理解数据库表、JSONB metadata、文件路径和磁盘文件关系时阅读。
* `SpectrumDataAccess.md`：需要改 mzML 读取、scan 查询、MS1/MS2 选择或谱图缓存路径时阅读。
* `DerivedDataIndex.md`：需要改 scan index、chromatogram summary、backfill 或 stale 判断时阅读。
* `BinaryFormat.md`：需要改 PFMB、`index.json`、DB baked metadata 或 `.npz` 派生索引格式时阅读。
* `ConfigAndDeployment.md`：需要确认环境变量、启动脚本、Vite proxy、RAW/PFMB 工具路径时阅读。
* `Testing.md`：需要选择或新增 pytest、Playwright 或 `cs` 能力测验时阅读。

模块文档之间包含简短“参见”关系，用于从当前模块跳到相邻的数据模型、导入、谱图访问、可视化或测试说明。

## 实现状态警戒表

| 能力或主题 | 当前文档状态 | 说明 |
| --- | --- | --- |
| ZIP上传入口 | 当前未找到实现 | 旧说明文档中有历史描述，当前主路径是 `source_path` folder ingest。 |
| MGF导入 | 当前未找到实现 | 未在当前源码或测试中找到 MGF adapter。 |
| 所有厂商RAW | 当前仅确认 Thermo RAW 转换路径 | 新厂商需要单独 converter adapter 和 planner/detector 扩展。 |
| RAW直接读取 | 当前不直接读取 | RAW 先转换为 uncompressed indexed mzML，再由 mzML reader 读取。 |
| gzip mzML indexed random access | 当前不支持 | indexed reader 和 scan index 都拒绝 gzip mzML。 |
| 通用Viewer专属二进制格式 | 当前未找到实现 | 当前重点是 PFMB sidecar 和 `.npz + .json` 派生索引。 |
| Docker部署 | 当前未找到说明 | 不应编造 Docker 流程。 |
| 生产部署方案 | 当前未找到说明 | `ConfigAndDeployment.md` 仅说明本地开发相关配置。 |
| 统一错误码注册表 | 当前未找到实现 | `HTTPException.detail` 仍存在多种格式。 |

## 术语速查

* `source_path`：前端提交给导入 API 的服务器本机目录路径。
* `source_root`：后端解析出的唯一 ingest root，写入 `datasets.source_root`。
* `runs.file_path`：run 记录中的原始文件或标准化文件磁盘路径。
* `runs.run_metadata.mzml_file_path`：run metadata 中用于定位 converted 或 mapped mzML 的路径。
* `mzml_memory`：历史/兼容命名，不代表当前所有 mzML 读取都走整文件内存池。
* PFMB：BottomUp 使用的预计算 fragment match binary sidecar。
* live mzML MS2：从 mzML scan 实时读取并匹配的 MS2 证据。
* TopFD JS spectra：TopDown/TopFD bundle 中的 JS 谱图数据路径。
* `.viewer-derived`：磁盘派生目录，保存 scan index、chromatogram summary 或 RAW converted mzML 等文件。

## 使用注意

* 这些文档反映当前仓库源码、测试、配置和已有说明文档能确认的状态。
* 当前未找到实现的能力会明确写为“当前未找到实现”或“当前未找到说明”。
* 不要把旧 ZIP 上传流程、MGF、所有厂商 RAW、通用 Viewer 二进制格式或 Docker/生产部署写成已支持，除非源码后续明确实现。
* `.viewer-derived` 是磁盘派生目录，不是数据库表。
* PFMB annotation 和 live mzML MS2 是不同证据来源。
