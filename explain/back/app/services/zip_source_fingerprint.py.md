# `back/app/services/zip_source_fingerprint.py` 逐行解释

> 来源文件：`back/app/services/zip_source_fingerprint.py`

## L1-L5（模块定位）

- 该模块只做一件事：**对磁盘上的 ZIP 文件做流式 SHA-256 指纹**。
- “如何解释/持久化 digest”由调用者决定：
  - 本项目中用于：
    - `imports.py` 上传后计算 sha256
    - `import_jobs.py` 写入 `datasets.source_zip_sha256` 并用唯一索引防重复

## L7-L12（导入与默认 chunk）

- `hashlib`：SHA-256
- `Path`：文件路径
- `_DEFAULT_CHUNK = 1 MiB`：
  - 与上传 API 的 1MiB chunk copy 对齐，避免一次性读大文件占内存

## L15-L24：`sha256_hex_of_file(path, chunk_size=...)`

- 创建 `hashlib.sha256()` digest
- `path.open("rb")` 二进制读取
- 循环 `read(chunk_size)`：
  - 读到空 bytes 就 break
  - 每块更新 digest
- 返回 `hexdigest()`（小写 hex 字符串）

