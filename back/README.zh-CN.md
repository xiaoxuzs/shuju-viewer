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

# 2. 创建表结构
uv run alembic upgrade head

# 3. 导入数据集
uv run python -m app.ingest.cli ingest `
    --root ..\shuju\MZ20160222DS_histone48_html `
    --slug mz20160222ds_histone48 `
    --name "MZ20160222DS_histone48"

# 4. 启动 API
uv run uvicorn app.main:app --reload --port 8000
```

浏览器打开 http://localhost:8000/docs 可查看 OpenAPI 文档界面。

## 项目结构

```
app/
  core/        配置、数据库会话、日志
  models/      SQLAlchemy ORM 实体
  schemas/     Pydantic 请求/响应模型
  services/    业务逻辑、谱图缓存
  ingest/      数据集导入流水线（JS -> 数据库）
  api/v1/      REST 路由
alembic/       数据库迁移
```
