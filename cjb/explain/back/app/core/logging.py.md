# `back/app/core/logging.py` 逐行解释

> 来源文件：`back/app/core/logging.py`

## L1（模块定位）

- 用标准库 logging + `rich` 提供更友好的控制台日志输出（彩色、traceback 更可读）。

## L5-L9（导入）

- `logging`：标准库日志
- `RichHandler`：rich 的日志 handler
- `settings`：读取 `log_level`

## L12-L18：`configure_logging()`

- 调用 `logging.basicConfig(...)` 配置全局日志：
  - `level=settings.log_level`：从 `.env` 控制 INFO/DEBUG 等
  - `format="%(message)s"`：把格式控制交给 RichHandler（更漂亮）
  - `datefmt="%H:%M:%S"`：时间格式
  - `handlers=[RichHandler(...)]`：
    - `rich_tracebacks=True`：traceback 更易读
    - `show_path=False`：隐藏路径（更简洁；需要时可打开）

## L21-L22：`get_logger(name)`

- 返回一个命名 logger（封装一下标准库 API），全项目统一用它取 logger。

