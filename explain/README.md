# explain 文件夹说明（主目录）

本目录存放与源码**一一对应**的逐行/分段解释文档：路径与仓库里的 `back/`、`front/`、`docs/`、`shuju/` 等**镜像一致**，仅在末尾多一层 `.md` 后缀。例如：

| 源码文件 | 解释文件 |
|----------|----------|
| `back/app/main.py` | `explain/back/app/main.py.md` |
| `front/src/pages/PrsmDetailPage.tsx` | `explain/front/src/pages/PrsmDetailPage.tsx.md` |

更完整的文件列表与导航请见仓库根目录的 **`逐行解释索引.md`**。

---

## 顶层子文件夹分别是什么

### `explain/back/` — 后端（Python / FastAPI）

对应 **`back/`**：HTTP 服务、数据库访问、导入任务、谱图与 mzML 等业务逻辑。

- **`explain/back/app/`** — 应用主包（`back/app/`），与 `main.py`、子包同层级。
  - **`api/`** — Web API 层：路由注册、依赖注入、版本化接口。
    - **`api/v1/`** — **REST API v1**：数据集、导入任务、蛋白质、proteoform、PrSM、谱图（TopFD JS / mzML）、通用兼容接口等；每个 `*.py` 通常对应一组 HTTP 路径与请求/响应模型。
  - **`core/`** — **基础设施**：配置（环境变量、数据根路径）、数据库引擎/会话、日志等；被 `api`、`services`、`ingest` 共用。
  - **`schemas/`** — **Pydantic / 序列化模型**：请求体、响应体、与 OpenAPI 文档对应的类型定义；与 `api/v1` 路由配合使用。
  - **`services/`** — **领域服务**：ZIP 导入与任务状态（`import_jobs`）、谱图缓存、mzML 存储与路径映射、JS 解析、ZIP 指纹等；**不**直接绑定 URL，供 API 与后台任务调用。
  - **`ingest/`** — **数据导入适配器**：把 TopPIC 输出树或 `prsm*.js` 包等形态写入通用库表；与 `services/import_jobs` 编排在一起完成一次导入。
  - 根下的 **`main.py.md`** 解释应用入口：挂载路由、中间件、生命周期等。

### `explain/front/` — 前端（TypeScript / React）

对应 **`front/src/`**：浏览器中的 UI、路由页面、调用后端的客户端。

- **`explain/front/src/api/`** — **HTTP 客户端与类型**：`client.ts`（请求封装）、`types.ts`（与后端约定一致的数据形状）。
- **`explain/front/src/pages/`** — **按路由划分的页面**：数据集列表/详情、蛋白质、proteoform、PrSM 列表与详情等；负责拉数、组合子组件。
- **`explain/front/src/features/prsm/`** — **PrSM 专用功能模块**：解析 `prsm*.js` 片段、谱图绘制、匹配峰表、碎裂视图、序列视图、弹窗等；与 `pages/PrsmDetailPage` 紧密配合。
- **`explain/front/src/components/`**（若后续补充解释）— 跨页面复用的 UI 组件；当前索引中可能仍指向源码路径，解释文件可按需逐步增加。

入口层（`main.tsx`、`App.tsx`）的解释也在 `explain/front/src/` 下。

### `explain/docs/` — 项目文档（Markdown / SQL）

对应 **`docs/`**：架构说明、部署、数据格式、SQL  schema、懒加载与导入流程等**设计/运维文档**的逐段说明；**不是**可执行后端代码，但描述与 `back/` 行为一致。

### `explain/shuju/` — 脚本与样本数据侧（若有）

对应 **`shuju/`**：例如解压/处理样本数据的脚本等；解释文件按同样规则放在 `explain/shuju/` 下。数据体量大的原始谱图 JS、ZIP 等一般**不做**逐文件解释，见 **`逐行解释索引.md`** 中的说明与边界。

---

## 阅读建议

1. 从 **`逐行解释索引.md`** 找到你关心的源码路径，再打开对应的 `explain/.../*.md`。
2. 想理解「一次 ZIP 导入从上传到落库」可结合 **`explain/docs/mzml-spectra-import-flow.md.md`** 与 **`explain/back/app/services/import_jobs.py.md`**。
3. 想理解「页面如何请求 PrSM / 谱图」可从 **`explain/front/src/pages/PrsmDetailPage.tsx.md`** 与 **`explain/front/src/api/client.ts.md`** 入手。

若你希望本 README 再增加「与 `back/pyproject.toml` / `front/package.json` 的对应关系」或「环境变量一览」，可以说明要偏运维还是偏开发，再在后续补一小节。
