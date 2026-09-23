# `back/app/api/deps.py` 逐行解释

> 来源文件：`back/app/api/deps.py`

## L1-L7（模块定位）

- 说明：这个模块只保留共享依赖 `get_db`。
- 历史上可能存在 ORM 版的 `get_dataset/get_cutoff` 之类依赖，但随着迁移到 universal schema（raw SQL）已移除。
- slug/cutoff 的校验与查找统一在 `app.api.v1.universal_compat` 完成。

## L9-L14（导入）

- `Session`：类型标注
- `get_session`：来自 `app.core.db` 的 FastAPI 依赖生成器（yield session）

## L16-L17：`get_db()`

- 这是 v1 路由统一使用的 DB 依赖：
  - `yield from get_session()` 直接复用底层生成器
  - 用注释 `# type: ignore[return-value]` 解决类型检查对生成器 yield 的静态推断问题

