# explain 文件夹说明（主目录）

本目录存放与源码**一一对应**的逐行/分段解释文档：路径与仓库里的 `back/`、`front/src/` **镜像一致**，仅在末尾多一层 `.md` 后缀。例如：

| 源码文件 | 解释文件 |
|----------|----------|
| `back/app/main.py` | `explain/back/app/main.py.md` |
| `front/src/pages/PrsmDetailPage.tsx` | `explain/front/src/pages/PrsmDetailPage.tsx.md` |

更完整的文件列表与导航请见仓库根目录的 **`逐行解释索引.md`**。

## 与源码对照的约定

- 各 **`explain/.../*.md`**（本 README 除外）在标题下写明 **`来源文件:`**，路径与仓库内 `back/`、`front/src/` 源码相对路径一致。
- 正文中的 **`Lx–Ly`** 以当前 checkout 的文本行号为准；合并或重构后若行号漂移，应以源码为真，再回头更新解释中的行号段。
- **只解释代码**：不维护 `docs/`、`.html` 文档或 `cs/` 测验脚本的 explain。

---

## 顶层子文件夹

### `explain/back/` — 后端（Python / FastAPI）

对应 **`back/`**：HTTP 服务、数据库访问、路径导入、指纹去重、谱图与 mzML 等业务逻辑。

- **`api/`** — Web API 层：路由注册、依赖注入、版本化接口。
  - **`api/v1/`** — REST API v1：数据集、路径导入任务、蛋白质、proteoform、PrSM、谱图（TopFD JS / mzML）、通用兼容接口等。
- **`core/`** — 基础设施：配置、数据库引擎/会话、日志。
- **`schemas/`** — Pydantic 请求/响应模型。
- **`services/`** — 领域服务：导入任务（`import_jobs`）、导入规划（`import_planner`）、路径搬迁、原生文件夹选择、谱图缓存、mzML 存储与映射、PrSM 明细文件发现、JS 解析、spectrum_memory 接线等。
- **`fingerprint/`** — 数据集元数据 manifest MD5 指纹（路径导入去重）。
- **`dataset_ingest_root/`** — 用户选择路径解析为 TopPIC ingest 根目录。
- **`spectrum_memory/`** — mzML 进程内内存缓存、LRU/MRU 驱逐与大小核算。
- **`ingest/`** — 数据导入适配器：TopPIC HTML 树或 `prsm*.js` bundle 写入 universal schema。
- **`main.py.md`** — 应用入口：挂载路由、中间件、生命周期。

### `explain/back/tests/` — 后端单元测试

对应 **`back/tests/`**：导入规划、指纹、根路径解析、spectrum_memory、prsm_files 等 pytest。

### `explain/front/` — 前端（TypeScript / React）

对应 **`front/src/`**：浏览器 UI、路由页面、调用后端的客户端。

- **`api/`** — HTTP 客户端与类型（`client.ts`、`types.ts`）。
- **`pages/`** — 按路由划分的页面。
- **`features/prsm/`** — PrSM 解析、谱图绘制、匹配峰表、碎裂/序列视图。
- **`features/lcms3d/`** — LC-MS 三维可视化面板（Three.js）。
- **`components/`** — 跨页面复用 UI 组件。
- **`lib/`** — 工具函数与路径导入辅助。

---

## 阅读建议

1. 从 **`逐行解释索引.md`** 找到你关心的源码路径，再打开对应的 `explain/.../*.md`。
2. 想理解「路径导入从选文件夹到落库」可结合 **`explain/back/app/api/v1/imports.py.md`**、**`explain/back/app/services/import_jobs.py.md`**、**`explain/back/app/fingerprint/`** 与 **`explain/back/app/dataset_ingest_root/`**。
3. 想理解「页面如何请求 PrSM / 谱图」可从 **`explain/front/src/pages/PrsmDetailPage.tsx.md`** 与 **`explain/front/src/api/client.ts.md`** 入手。
