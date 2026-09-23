# ProjectOverview

## 1.模块定位

Viewer 是一个蛋白质组学数据浏览项目，当前源码支持 TopDown、BottomUp 和 spectra-only 三类数据浏览。前端负责页面、路由和可视化，后端负责 API、导入编排、数据库访问、谱图读取和派生索引读取。数据库保存业务 metadata、路径和关系，RAW、mzML、PFMB 以及 `.viewer-derived` 派生文件仍在磁盘上。

## 2.技术栈速览

* 前端：React 18、Vite、TypeScript、React Router、TanStack Query 和 axios。
* 后端：FastAPI、Pydantic、SQLAlchemy、PostgreSQL 和 `postgresql+psycopg`。
* 谱图访问：pyteomics 读取 indexed mzML，当前主路径偏向 indexed single-spectrum reader。
* 派生数据：NumPy 写读 `.npz`，`.json` 保存 metadata，文件位于 `.viewer-derived` 磁盘目录。
* BU 导入：`pyarrow.parquet` 读取 DIA-NN parquet。
* RAW 转换：ThermoRawFileParser 是外部转换工具，RAW 不直接读取。
* PFMB：PFMB/PFM 侧车格式为 BottomUp 预计算 fragment match evidence 服务。

## 3.核心职责

* 说明项目的前端、后端、数据库和文件存储边界。
* 说明 dataset、run、spectrum、chromatogram、protein、peptide、proteoform、identification_match、PrSM、PFMB slot 等核心对象。
* 说明 TopDown、BottomUp、spectra-only 三种 dataset mode 的入口差异。
* 说明前端页面到后端 API、PostgreSQL、源文件和 `.viewer-derived` 派生文件的主链路。

## 4.关键目录和文件

* `front\src\main.tsx`：前端应用入口，挂载 React、BrowserRouter 和 TanStack Query。
* `front\src\App.tsx`：前端路由入口，注册 dataset、BU、TD 页面路径。
* `back\app\main.py`：FastAPI 后端入口，创建应用、注册 CORS、生命周期和 `/health`。
* `back\app\api\v1\__init__.py`：API v1 router 注册入口，统一挂载到 `/api/v1`。
* `docs\universal_schema.sql`：数据库结构真源，定义 datasets、runs、proteins、proteoforms、peptides、identification_matches、protein_relation_mapping、import_jobs 等表。
* `back\app\core\db.py`：数据库连接和 Session 入口。
* `back\app\services\import_jobs.py`：路径导入任务编排层。
* `back\app\services\mzml_scan_reader.py`：mzML 单谱读取入口。
* `back\app\services\mzml_scan_index.py`：mzML scan index 派生索引入口。

## 5.核心数据流

1. 用户在 `front\src\pages\DatasetsPage.tsx` 或业务页面触发请求。
2. `front\src\api\client.ts` 通过 axios 访问 `/api/v1`。
3. FastAPI route 在 `back\app\api\v1` 下接收请求。
4. route 或 service 通过 `back\app\core\db.py` 访问 PostgreSQL。
5. 对谱图、chromatogram、PFMB annotation 等数据，后端再根据 DB metadata 读取磁盘源文件或 `.viewer-derived` 派生文件。
6. 前端页面把 API DTO 交给表格、谱图、XIC、heatmap 或 3D 组件展示。

## 6.关键API或关键组件

以下是代表性 API 和组件，不是全量 API 目录；完整路由以 `back\app\api\v1` 及其子目录为准。

* `GET /health`：后端健康检查。
* `GET /api/v1/datasets`、`GET /api/v1/datasets/{slug}`：dataset 列表和详情。
* `POST /api/v1/imports`、`GET /api/v1/imports/{job_id}`：导入任务创建和轮询。
* `GET /api/v1/datasets/{slug}/cutoffs/{cutoff}/proteins|proteoforms|prsms`：TopDown 列表。
* `GET /api/v1/datasets/{slug}/overview|proteins|peptides|matches`：BottomUp 列表和概览。
* `GET /api/v1/datasets/{dataset_id}/runs/{run_id}/spectra/{scan_number}`：mzML scan 谱图读取。
* `App`、`DatasetModeGate`、`TdCutoffModeGate`：前端 mode 分流核心组件。

## 7.和其他模块的关系

ProjectOverview 是总入口。UI、BackendAPI、DataModelStorage、Import、SpectrumDataAccess、DerivedDataIndex、BottomUp、TopDown、RawFile、BinaryFormat 都是它的细分模块。

## 8.扩展和维护建议

新增功能时先判断属于 UI、导入、数据模型、谱图访问还是业务模块。不要把新格式解析、DB 写入、路由展示和派生文件生成混在一个大文件内。与导入相关的功能应继续遵守 `AGENTS.md` 的低耦合要求：指纹、根路径解析、planner、adapter 和编排层各自保持窄接口。

## 9.当前限制和注意事项

* 文件本体不进入数据库；数据库保存 metadata、路径和关系。
* `.viewer-derived` 是磁盘派生目录，不是数据库表。
* 旧说明文档中存在 ZIP 上传和 `source_zip_sha256` 描述；当前源码主路径是 `source_path` 文件夹导入和 `source_dataset_fingerprint`。
* 当前未找到 MGF 导入支持。
* 当前未找到 Docker 或生产部署说明。
* `mzml_memory` 名称仍出现在代码中，但许多当前路径实际使用 indexed single-spectrum reader。
