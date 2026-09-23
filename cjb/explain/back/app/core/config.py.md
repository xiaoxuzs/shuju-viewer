# `back/app/core/config.py` 逐行解释

> 来源文件：`back/app/core/config.py`

## L1（模块定位）

- 该模块定义后端配置 `Settings`，从环境变量与 `back/.env` 加载。

## L3-L8（导入）

- `Path`：处理路径（尤其 `DATA_ROOT`/`.env`）
- `pydantic_settings.BaseSettings`：从 env/.env 自动解析字段
- `SettingsConfigDict`：配置 settings 行为
- `Field`：为字段提供默认值/描述等

## L11：`BACKEND_ROOT`

- 定位后端根目录：`back/app/core/config.py` 的 `parents[2]` 即 `back/`
- 用于：
  - 找 `.env`（`back/.env`）
  - 计算默认 `data_root`（`<repo>/shuju`）

## L14-L29：`Settings` 字段与加载规则

### L15-L20：`model_config`

- `env_file=BACKEND_ROOT / ".env"`：默认读取 `back/.env`
- `env_file_encoding="utf-8"`
- `case_sensitive=False`：环境变量大小写不敏感（Windows 常见）
- `extra="ignore"`：`.env` 里出现未声明字段时忽略（便于扩展不破坏旧版本）

### L22-L28：核心配置项

- `database_url`：SQLAlchemy 数据库连接串（默认给了一个开发示例）
- `data_root`：数据根目录（默认 `<repo>/shuju`）
- `api_cors_origins`：逗号分隔的允许跨域 origin 列表（默认 `http://localhost:5173`）
- `log_level`：日志等级
- `spectrum_cache_size`：谱图缓存大小（注意：目前 `spectrum_cache.py` 的 lru_cache maxsize 写死 256，这个字段更多是“配置意图”，后续可接入）

## L30-L33：`cors_origin_list`

- 把 `api_cors_origins` 按逗号切分并 strip，过滤空值，供 CORS 中间件使用。

## L34-L39：`resolved_data_root`

- 确保 `data_root` 是绝对路径：
  - 若 `.env` 给相对路径，则相对 `BACKEND_ROOT`（即 back/）解析并 resolve
- 该属性在日志与导入服务中被大量使用，保证路径语义稳定。

## L42：`settings = Settings()`

- 创建全局单例 settings 对象，供全后端 import 使用。

