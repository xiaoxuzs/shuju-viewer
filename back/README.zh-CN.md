# proteo-viewer 后端

用于在浏览器中浏览组蛋白蛋白质组学结果包（TopPIC / TopFD 输出）的 FastAPI + SQLAlchemy + PostgreSQL 后端。

**英文说明：** [README.md](README.md)

## 快速开始

需要已安装 `uv`，以及正在运行的 PostgreSQL 14+。

```powershell
# 在仓库根目录 viewer/ 下
cd back
uv sync

# 1. 配置数据库连接（若与默认不同，请编辑 .env）
Copy-Item .env.example .env -ErrorAction SilentlyContinue

# 2. 创建表结构（universal 七表）
psql -h localhost -U postgres -d Universal_Viewer -f ..\docs\universal_schema.sql

# 3. 导入数据集
uv run python -m app.ingest.universal_toppic_adapter ingest `
    --root ..\shuju\MZ20160222DS_histone48_html `
    --database-url "postgresql+psycopg://postgres:postgres@localhost:5432/Universal_Viewer" `
    --slug mz20160222ds_histone48 `
    --name "MZ20160222DS_histone48" `
    --mode full --replace

# 4. 启动 API
uv run uvicorn app.main:app --reload --port 8000
```

浏览器打开 http://localhost:8000/docs 可查看 OpenAPI 文档界面。

## 项目结构

```
app/
  core/        配置、数据库会话、日志
  schemas/     Pydantic 请求/响应模型
  services/    后台导入任务、谱图缓存
  ingest/      universal schema 的 TopPIC/TopFD 导入器（CLI + 库）
  api/v1/      REST 路由（直接读 universal 七表）
```

数据库表结构以 `docs/universal_schema.sql` 为唯一真值。读模型在
`app/api/v1/*.py` + `app/api/v1/universal_compat.py`；写模型（前端 ZIP 上传
`POST /api/v1/imports` 和上面的 CLI）都走
`app/ingest/universal_toppic_adapter.py`。已经不再保留 SQLAlchemy ORM 与
Alembic 迁移这一条平行链路。
