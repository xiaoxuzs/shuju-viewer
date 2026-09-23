# UI

## 1.模块定位

UI 模块是 Viewer 的浏览器端应用，负责路由、页面布局、状态管理、API 请求封装和业务可视化组件装配。它不直接访问数据库或磁盘文件，所有业务数据通过 `/api/v1` 后端接口获得。

## 2.核心职责

* 提供 React 18、Vite、TypeScript 前端入口。
* 通过 React Router 管理 dataset、BottomUp、TopDown 和 spectra-only 页面。
* 通过 TanStack Query 管理请求状态和缓存。
* 通过 axios client 封装后端 API。
* 提供 loading、error、empty 等通用状态组件。
* 根据 dataset mode 将页面分流到 BU、TD 或 spectra-only。

## 3.关键目录和文件

* `front\package.json`：前端依赖来源，包含 React、Vite、React Router、TanStack Query、axios、d3、three、lucide-react 等。
* `front\src\main.tsx`：创建 QueryClient，挂载 BrowserRouter 和 App。
* `front\src\App.tsx`：注册应用路由。
* `front\src\components\layout\app-shell.tsx`：应用布局外壳。
* `front\src\components\common\data-state.tsx`：通用错误态和空状态组件。
* `front\src\components\common\page-loading.tsx`：通用页面 loading。
* `front\src\components\common\plot-status.tsx`：图表 loading、empty、error 状态。
* `front\tailwind.config.ts`：Tailwind CSS 配置。
* `front\src\components\ui\button.tsx`：使用 Radix Slot 和 class-variance-authority 定义按钮变体。
* `front\src\components\ui\badge.tsx`：使用 class-variance-authority 定义 badge 变体。
* `front\src\lib\utils.ts`：`cn()` 工具基于 `clsx` 和 `tailwind-merge` 合并 className。
* `front\src\api\client.ts`：axios 实例和 API 方法。
* `front\src\api\types.ts`：前端 DTO 类型。
* `front\src\features\bu\routes\DatasetModeGate.tsx`：dataset mode 分流入口。
* `front\src\features\bu\routes\TdCutoffModeGate.tsx`：TD cutoff 路由保护。
* `front\src\features\bu\routes\BuModeOnly.tsx`：BU 页面路由保护。

## 4.核心数据流

1. `front\src\main.tsx` 创建 React 应用和 QueryClient。
2. `front\src\App.tsx` 根据 URL 选择页面组件。
3. 页面组件使用 `useQuery` 调用 `front\src\api\client.ts` 中的 client 方法。
4. axios 使用 `baseURL: "/api/v1"` 访问后端。
5. TanStack Query 将 loading、error、data 状态交给页面。
6. 页面把数据传给业务组件、表格组件和可视化组件。

UI 样式主路径来自 Tailwind CSS utility class。项目内基础 UI 组件使用 `cn()` 合并样式，`button` 和 `badge` 等组件用 class-variance-authority 表达样式变体，图标主要来自 lucide-react。Radix 当前在源码中明确确认的使用点是 `@radix-ui/react-slot`，其他 Radix 包在依赖中存在但不应直接写成所有组件的主实现。

## 5.关键API或关键组件

* `fetchDatasets`、`fetchDataset`、`deleteDataset`：dataset API client。
* `enqueueImport`、`pickImportFolder`、`fetchImportJob`：导入 API client。
* `fetchPrsm`、`fetchMs1Spectrum`、`fetchMs2Spectrum`、`fetchMzmlSpectrum`：TD 和 mzML 谱图 API client。
* `DatasetModeGate`：根据 `analysis_mode` 和 spectra-only capabilities 分流。
* `BuDatasetLayout`：BU dataset 下的布局和导航。
* `SpectraOnlyPage`：spectra-only 数据集首页。
* `DatasetPage`、`ProteinsPage`、`ProteoformsPage`、`PrsmsPage`、`PrsmDetailPage`：TD 页面。

## 6.和其他模块的关系

UI 依赖 BackendAPI 的路由和 DTO，依赖 Visualization 组件展示谱图与图表，依赖 BottomUp、TopDown、SpectrumDataAccess 返回的数据结构。UI 不应直接处理数据库、文件系统、RAW 转换或派生索引生成。

## 7.扩展和维护建议

新增页面时先在 `front\src\App.tsx` 挂路由，再在对应 feature 目录内放页面和组件。新增后端请求应优先扩展 `front\src\api\client.ts` 或 feature 内 client，而不是在组件中散写 axios URL。跨页面通用 loading/error/empty 状态应复用 `front\src\components\common`。

## 8.当前限制和注意事项

* `front\src\features\bu-viewer` 在仓库中存在，但当前 `front\src\App.tsx` 引用的是 `front\src\features\bu`；文档应将 `features\bu` 写作当前主路径。
* `zustand`、`@tanstack/react-table` 和 `@tanstack/react-virtual` 在 `front\package.json` 依赖中存在，但当前 `front\src` 未确认作为主路径使用。
* 未找到独立 UI 规范文档；当前显示文案多为英文，但不是由单独规则文件统一约束。
* 前端删除对话框中有磁盘删除文案，而后端 `delete_dataset` 当前是 DB only；正式修改 UI 前需要人工确认产品语义。
* UI 不应把 `.viewer-derived`、mzML、PFMB 当作可直接浏览的前端静态文件路径。
## 9.可复用入口

应用入口和路由：

* `front\src\main.tsx`：创建 `QueryClient`，用 `QueryClientProvider`、`BrowserRouter` 包裹 `App`。
* `front\src\App.tsx::App`：声明主 route tree。
* `front\src\components\layout\app-shell.tsx::AppShell`：全局布局和 header 链接容器。
* `front\src\features\bu\routes\DatasetModeGate.tsx::DatasetModeGate`：按 dataset mode 分流 BU、spectra-only 或重定向。
* `front\src\features\bu\routes\BuModeOnly.tsx::BuModeOnly`：限制 BU 子页面只服务 BU dataset。
* `front\src\features\bu\routes\TdCutoffModeGate.tsx::TdCutoffModeGate`：限制 TD cutoff 页面。

通用 API client：

* `front\src\api\client.ts::fetchDatasets`
* `front\src\api\client.ts::fetchDataset`
* `front\src\api\client.ts::deleteDataset`
* `front\src\api\client.ts::enqueueImport`
* `front\src\api\client.ts::pickImportFolder`
* `front\src\api\client.ts::fetchImportJob`
* `front\src\api\client.ts::fetchPrsm`
* `front\src\api\client.ts::fetchMzmlSpectrum`
* `front\src\features\bu\api\buClient.ts`：BU feature client，例如 `fetchBuOverview`、`fetchBuMatchMs2`、`fetchBuRunChromatogram`。
* `front\src\features\spectra-only\api\spectraClient.ts`：spectra-only client，例如 `fetchSpectraFullScanIndex`、`fetchSpectraSpectrum`。
* `front\src\lib\apiError.ts::parseApiError`
* `front\src\lib\apiError.ts::chartQueryRetry`

通用组件：

* `front\src\components\common\data-state.tsx::DataLoadError`
* `front\src\components\common\data-state.tsx::DataEmptyState`
* `front\src\components\common\page-loading.tsx::PageLoading`
* `front\src\components\common\plot-status.tsx::PlotStatus`
* `front\src\components\ui\button.tsx::Button`
* `front\src\components\ui\card.tsx::Card`
* `front\src\components\ui\badge.tsx::Badge`
* `front\src\components\ui\input.tsx::Input`
* `front\src\components\ui\table.tsx::Table`
* `front\src\components\ui\skeleton.tsx::Skeleton`

## 10.调用链

页面挂载链路：

1. `front\src\main.tsx` 创建 `QueryClient`。
2. `QueryClientProvider` 提供 TanStack Query client。
3. `BrowserRouter` 提供前端 route 上下文。
4. `front\src\App.tsx::App` 渲染 `Routes`。
5. `Route element={<AppShell />}` 提供全局页面框架。

dataset mode 分流链路：

1. `/datasets/:slug` 命中 `DatasetModeGate`。
2. `DatasetModeGate` 通过 `front\src\api\client.ts::fetchDataset` 读取 dataset。
3. BU dataset 进入 `Outlet`，其子页面由 `BuModeOnly` 包裹。
4. spectra-only dataset 直接渲染 `front\src\features\spectra-only\pages\SpectraOnlyPage.tsx::SpectraOnlyPage`。
5. TD cutoff 页面走 `TdCutoffModeGate`，再进入 `ProteinsPage`、`PrsmDetailPage` 等页面。

当前源码未见独立 LCMS3D route。LCMS3D 入口在 `front\src\pages\PrsmDetailPage.tsx` 内使用 `front\src\features\lcms3d\Lcms3DPanel.tsx::Lcms3DPanel`。

## 11.新增功能接入方式

新增页面：

1. 在 `front\src\App.tsx::App` 增加 route，先判断是否需要 `DatasetModeGate`、`BuModeOnly` 或 `TdCutoffModeGate`。
2. 页面组件优先放在对应 feature 目录，例如 BU 放 `front\src\features\bu\pages`，spectra-only 放 `front\src\features\spectra-only\pages`。
3. 新 API 调用先补 client 函数和 DTO：通用接口放 `front\src\api\client.ts`、`front\src\api\types.ts`；BU 放 `front\src\features\bu\api\buClient.ts`、`front\src\features\bu\types.ts`。
4. 页面中用 `useQuery` 调 client 函数，不在 React 组件里直接拼 axios URL。
5. 按页面行为补 `front\tests` 下 Playwright 入口，例如 BU detail 行为参考 `front\tests\bu-match-detail.spec.ts`。

新增错误态或加载态：

* 页面级加载优先复用 `PageLoading`。
* 页面级失败优先复用 `DataLoadError`。
* 空数据优先复用 `DataEmptyState`。
* 图表或局部 panel 状态优先复用 `PlotStatus`。
* 后端错误解析优先通过 `parseApiError`，图表 query retry 优先使用 `chartQueryRetry`。

新增业务 feature：

* 优先放入 `front\src\features\...` 对应目录，不要塞进 `front\src\components\common` 或 `front\src\components\ui`。
* BU 新能力优先接入 `front\src\features\bu\api\buClient.ts`。
* spectra-only 新能力优先接入 `front\src\features\spectra-only\api\spectraClient.ts`。

## 12.内部实现边界

以下为内部实现或低层封装，不建议跨模块直接调用：

* `front\src\components\layout\app-shell.tsx::HeaderLink` 是 `AppShell` 内部 header link helper。
* `front\src\api\client.ts::api` 是 axios 实例，页面组件不应直接使用它拼 URL；应通过 `fetch*` client 函数。
* `front\src\components\ui\button.tsx::buttonVariants`、`front\src\components\ui\badge.tsx::badgeVariants` 是 UI variant 内部实现。
* `front\src\lib\apiError.ts::responseFrom`、`detailFrom`、`errorFields`、`classify` 是 `parseApiError` 的内部解析 helper。

目录边界：

* `front\src\components\ui` 是基础 UI，不放业务数据读取和 BU/TD 判断。
* `front\src\components\common` 可放跨模块状态组件，不依赖 BU、TD、spectra-only 业务对象。
* `front\src\features\bu`、`front\src\features\spectra-only`、`front\src\features\lcms3d` 是业务 feature 边界。

## 13.不要绕过的层

* 不要绕过 `front\src\api\client.ts`、`front\src\features\bu\api\buClient.ts` 或 `front\src\features\spectra-only\api\spectraClient.ts`，在页面里直接拼 axios 请求。
* 不要绕过 `DatasetModeGate`、`BuModeOnly` 或 `TdCutoffModeGate`，把 BU 页面暴露给非 BU dataset。
* 不要把 BU feature 组件反向放进 `front\src\components\common`。
* 不要把 `.viewer-derived`、PFMB、mzML 磁盘路径当作前端静态 URL。
* 不要绕过 `parseApiError` 自己解析 FastAPI error detail。

## 14.常见修改场景

新增 BU 页面：

1. 后端先确认 route 和 response schema。
2. 在 `front\src\features\bu\api\buClient.ts` 增加 client 函数。
3. 在 `front\src\features\bu\types.ts` 增加 DTO。
4. 在 `front\src\features\bu\pages` 增加页面。
5. 在 `front\src\App.tsx::App` 的 `/datasets/:slug` 子 route 下接入，并按需包 `BuModeOnly`。

新增 spectra-only panel：

1. client 放 `front\src\features\spectra-only\api\spectraClient.ts`。
2. 类型放 `front\src\features\spectra-only\types.ts`。
3. panel 放 `front\src\features\spectra-only\components`。
4. 由 `SpectraOnlyPage` 组织状态和数据流，展示组件不要重复请求同一份 API。

新增全局状态组件：

1. 判断是否不依赖业务对象。
2. 业务无关才放 `front\src\components\common`。
3. 只是样式原语才放 `front\src\components\ui`。

## 15.相关测试

本节列出开发时应参考或补充的测试入口；当前任务不运行这些测试。

* API error：`front\tests\api-error.spec.ts`。
* BU detail 页面：`front\tests\bu-match-detail.spec.ts`。
* BU PFMB：`front\tests\bu-pfmb-annotation.spec.ts`、`front\tests\bu-pfmb-visuals.spec.ts`、`front\tests\bu-pfmb-quality.spec.ts`。
* BU product ion：`front\tests\product-ion-selection.spec.ts`。
* spectra-only：`front\tests\spectra-only-scan-relations.spec.ts`、`front\tests\spectra-only-peak-annotations.spec.ts`。
