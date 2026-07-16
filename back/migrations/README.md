# Backend SQL migrations

本目录包含 Viewer 的显式、版本化 PostgreSQL Schema 迁移链。运行器只自动发现名称严格匹配
`^[0-9]{4}_[a-z][a-z0-9_]*\.sql$` 的文件，版本必须从 `0001` 连续递增。迁移文件一旦应用，
文件名、名称和内容均不得修改；运行器使用 LF 规范化后的完整文件 SHA-256 校验历史。

`20260522_bu_identification_match_indexes.sql` 是唯一保留的历史人工迁移。其两个 BU 索引已经吸收进
`legacy_baseline_v1.json`，该文件不会被版本化运行器重新执行，也不是忽略其他未知 SQL 的通配规则。

当前迁移链：

```text
0001_schema_migrations.sql
```

空数据库仍使用 `docs/universal_schema.sql` 初始化 8 张业务表；P2-2B1 不负责从空数据库创建业务
Schema。已有、尚未版本化的数据库只有在完整 `public` Catalog 与 `legacy_baseline_v1.json` 逐项一致
时，才允许由 `0001` 安全认领。

从 `back/` 运行只读命令：

```powershell
python -m app.schema_migrations status --database-url "<postgresql-url>"
python -m app.schema_migrations check --database-url "<postgresql-url>"
python -m app.schema_migrations plan --database-url "<postgresql-url>"
```

显式升级命令要求操作人身份：

```powershell
python -m app.schema_migrations upgrade `
  --database-url "<postgresql-url>" `
  --applied-by "<operator>"
```

也可使用专用环境变量 `VIEWER_SCHEMA_DATABASE_URL` 和 `VIEWER_SCHEMA_APPLIED_BY`。迁移 CLI 不读取
普通 `DATABASE_URL`、`back/.env` 或应用全局 Engine。

P2-2B1 是不可部署中间态：应用启动仍保留旧 `ensure_*` DDL，API 尚未切换到 Schema 版本门禁，
`docs/universal_schema.sql` 也尚未包含 `schema_migrations`。必须等待 P2-2B1-S 的 PostgreSQL 16 测试
与正式库只读 `status/plan` 验证；本阶段不得在正式库执行 `upgrade`。API 启动切换将在 P2-2B2 完成。
