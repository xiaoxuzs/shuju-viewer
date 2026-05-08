## `docs/universal-viewer-deployment.md` 逐行解释

> 这是一份“交付给别人部署”的操作手册：告诉对方应提交什么文件、如何初始化 PostgreSQL、如何配置后端 `.env`、如何用 adapter 导入数据、如何启动前后端与排查常见问题。它更多是运维步骤而非代码，但它定义了项目的“可复现部署路径”。

---

### L1-L6：标题与目的

- **L1**：标题：Universal Viewer 部署说明。
- **L3**：说明本文目的是让其他人能部署数据库结构与导入流程。
- **L5**：分隔线。

---

## 1. Git 中应该提交什么（L7-L26）

### L9-L17：应该提交

- `docs/universal_schema.sql`：建表脚本（数据库真值）。
- `docs/universal-viewer-deployment.md`：部署说明（本文件）。
- `docs/universal-viewer-summary.md`：改造总结（如果存在）。
- `添加数据说明.md`：导入说明。
- `back/app/ingest/universal_toppic_adapter.py`：导入适配器（写模型核心）。
- `back/.env.example`：环境变量模板。

### L18-L25：不应该提交

- `back/.env`：包含密码等敏感信息。
- `shuju/` 以及真实 `spectrum*.js`、`prsm*.js`：体积大且不应进入 Git。
- PostgreSQL 数据目录/二进制文件。

这部分给出“仓库应包含什么、不应包含什么”的边界。

---

## 2. 初始化数据库（L29-L62）

### 2.1 创建数据库（L31-L40）

- 创建名为 `"Universal_Viewer"` 的数据库；已存在则跳过。

### 2.2 导入表结构（L41-L61）

- 在仓库根执行 `psql ... -f docs/universal_schema.sql`。
- 如果 `psql` 不在 PATH，可用 GUI 打开 SQL 并执行。
- 预期看到 7 张表（列名列表），用于确认导入成功。

---

## 3. 配置后端环境变量（L65-L88）

- **L67-L72**：复制 `back/.env.example` → `back/.env`。
- **L74-L82**：给出 `.env` 示例字段：
  - DATABASE_URL：连接串（含用户名密码）
  - DATA_ROOT：数据目录（默认 `../shuju`）
  - CORS origins
  - LOG_LEVEL、SPECTRUM_CACHE_SIZE 等
- **L84-L88**：注意事项：
  - 不要提交真实 `.env`
  - 修改 `.env` 后必须重启后端

---

## 4. 安装后端依赖（L91-L99）

- 在 `back/` 下执行 `uv sync`。
- 这里约定 Python 依赖管理工具为 `uv`（与仓库实际一致）。

---

## 5. 放置数据文件（L101-L127）

- 要求把 TopPIC/TopFD HTML 输出目录放到本机可访问位置，推荐 `viewer/shuju/`。
- 给出标准目录结构示例（topfd + toppic_*_cutoff/data_js）。
- 强调真实数据不要提交 Git。

---

## 6. 导入数据（L130-L159）

- 给出 adapter ingest 的命令示例（PowerShell 多行）。
- 参数说明：
  - root/database-url/slug/name/mode/replace
- 推荐部署使用 `--mode fast`：
  - 因为 fast 只读 proteins.js + 登记 detail_path，速度快。

---

## 7. fast 模式导入内容（L162-L181）

### fast 会写入（L164-L172）

- datasets/runs/proteins/proteoforms/protein_relation_mapping/identification_matches
- identification_matches 在 fast 模式下来自 proteins.js 的 PrSM 摘要

### fast 不会写入（L173-L179）

- 谱图峰列表
- 完整 ms_header/ms_peaks/annotated_protein

### L180-L181：按需读取

- 详情页打开 PrSM 时通过 `identification_matches.detail_path` 按需读取 prsm*.js。

---

## 8. 验证数据库内容（L184-L229）

- 给出 count 查询来检查各表行数。
- 给出按 source_cutoff 分组与按 import_mode 分组的查询，用于确认导入结果与导入模式。
- 给出一个样例数据集的期望行数分布，作为 sanity check。

---

## 9. 启动服务（L233-L251）

- 后端：`uv run uvicorn app.main:app --reload --port 8000`
- 前端：`pnpm install` + `pnpm dev`
- 浏览器打开前端页面后应看到数据集。

---

## 10. 常见问题（L254-L279）

- 后端读旧数据库：检查 `.env` 的 DATABASE_URL，修改后重启。
- 前端打开详情变慢：fast 模式本来就是按需读取 prsm*.js。
- 数据集路径换了谱图打不开：数据库里保存了 source_root/file_path，移动后需重新导入或手工更新。
- 是否能提交真实数据：不建议（体积/维护/隐私）。

