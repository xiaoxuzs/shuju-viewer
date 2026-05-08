# `back/app/core/db.py` 逐行解释

> 来源文件：`back/app/core/db.py`

## L1（模块定位）

- 定义数据库 engine、session factory、以及 FastAPI 依赖 `get_session`。

## L5-L9（导入）

- `Iterator/contextmanager`：用于依赖注入与脚本用的 session_scope
- `sqlalchemy.create_engine`：创建 engine
- `Session/sessionmaker`：创建 session 工厂
- `DeclarativeBase`：ORM base（虽然读路径用 raw SQL，但工程仍保留 base 以便未来扩展）

## L11

- 从 `settings` 读取 `database_url`

## L14-L21：engine 创建

- `settings.database_url`：连接串
- `pool_pre_ping=True`：每次取连接前 ping，避免长时间空闲连接被服务端断开导致报错
- `pool_size/max_overflow`：连接池容量
- `future=True`：使用 SQLAlchemy 2.0 风格行为

## L23：SessionLocal

- `autocommit=False/autoflush=False`：显式提交、避免隐式 flush
- `expire_on_commit=False`：提交后对象不过期（更适合 API 场景）

## L26-L28：`Base`

- ORM declarative base（当前读模型不依赖 ORM，但保留基础类）

## L30-L37：`get_session()`

- FastAPI dependency：yield 一个 session，并在 finally 里 close
- API 层通常通过 `app/api/deps.py:get_db` 间接使用它

## L39-L51：`session_scope()`

- 脚本/批处理场景的上下文管理器：
  - 成功：commit
  - 异常：rollback 并 re-raise
  - 最后：close

