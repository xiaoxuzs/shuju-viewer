# Backend SQL migrations

本目录存放未引入 Alembic 前的手工 PostgreSQL migration。

应用方式示例：

```powershell
psql -h localhost -U postgres -d "Universal_Viewer" -f "back/migrations/20260522_bu_identification_match_indexes.sql"
```

