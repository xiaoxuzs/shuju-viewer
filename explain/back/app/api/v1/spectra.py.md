## `back/app/api/v1/spectra.py` 逐行解释

> 目标：在 **TopFD JS 光谱模式**（`datasets.capabilities.spectra_source == "topfd_js"`）下，提供 MS1/MS2 原始谱 JSON 的读取 API。数据来源是磁盘上的 `topfd/ms1_json` 与 `topfd/ms2_json` 目录中的 `spectrum*.js` 文件（由 `SpectrumCache` 解析与缓存）。

---

### L1：模块 docstring

- **L1**：说明这是 MS1/MS2 原始谱 JSON API，从 universal dataset root 读取 TopFD spectrum files。

---

### L3-L16：依赖

- **L3**：future annotations。
- **L5**：`Any`：FastAPI response_model 里用 `dict[str,Any]`。
- **L7**：FastAPI 组件。
- **L8**：SQLAlchemy Session。
- **L10**：`get_db`：注入 session。
- **L11**：`require_dataset`：通过 slug 找 dataset 行（拿到 `source_root`）。
- **L12-L16**：从 `spectrum_cache` 导入：
  - `get_ms1_spectrum` / `get_ms2_spectrum`：读取并解析 `spectrum{spec_id}.js`
  - `SpectrumNotFoundError`：当 spec 文件不存在或解析失败时抛出，用于映射成 404。

---

### L18：Router

- **L18**：tag 为 `"spectra"`。

---

## MS1：`GET /datasets/{slug}/spectra/ms1/{spec_id}`

### L21-L28：路由与错误映射

- **L21**：定义路由与 response_model 为 `dict[str, Any]`（原始 JSON）。
- **L22**：参数：
  - slug：dataset slug
  - spec_id：谱文件编号（对应 `spectrum{spec_id}.js`）
  - session：DB session
- **L23-L24**：docstring 指出解析路径优先级：
  - 优先 `datasets.source_root`
  - 若缺失则回退到服务端的 `DATA_ROOT/slug`（该逻辑在 `spectrum_cache._candidate_roots`）
- **L24**：`require_dataset` 验证 slug 并取 dataset 信息。
- **L25-L27**：调用 `get_ms1_spectrum(dataset["slug"], dataset["source_root"], spec_id)`：
  - 若抛 SpectrumNotFoundError，则转成 HTTP 404。

---

## MS2：`GET /datasets/{slug}/spectra/ms2/{spec_id}`

### L31-L38：逻辑同 MS1

- **L33-L34**：docstring 提到 MS2 子路径为 `topfd/ms2_json`。
- **L34**：require_dataset。
- **L35-L38**：调用 `get_ms2_spectrum(...)`，并把 SpectrumNotFoundError 映射成 404。

---

### 与其它模块的耦合点

- **与 `back/app/services/spectrum_cache.py`**：本模块只做路由与错误码；路径解析、js 解析、LRU 缓存都在 spectrum_cache。
- **与 `datasets.capabilities`**：前端会基于 capabilities 决定是否走这个 API 还是走 mzML dynamic API（`mzml_spectra.py`）。

# `back/app/api/v1/spectra.py` 逐行解释

> 来源文件：`back/app/api/v1/spectra.py`

## L1-L2（模块定位）

- 提供 MS1/MS2 原始谱 JSON API，读取 TopFD 导出的 `spectrum*.js` 文件。
- 文件位置由 dataset 的 `source_root`（DB）或 `DATA_ROOT/<slug>`（fallback）推导。

## L3-L16（导入）

- `Any`：谱图 JSON 直接透传（不强制 schema），所以 response_model 使用 `dict[str, Any]`
- FastAPI：
  - `APIRouter` 创建路由
  - `Depends` 注入 DB session
  - `HTTPException/status` 转换 FileNotFound 为 404
- `get_db`：DB session
- `require_dataset`：按 slug 查 dataset（拿 `source_root`）
- `spectrum_cache`：
  - `get_ms1_spectrum/get_ms2_spectrum`：解析磁盘路径并读取 `.js` 对象（带 LRU cache）
  - `SpectrumNotFoundError`：找不到文件时抛出

## L18

- 创建 `router = APIRouter(tags=["spectra"])`

## L21-L29：`GET /datasets/{slug}/spectra/ms1/{spec_id}`

- 先用 `require_dataset(session, slug)` 拿 dataset 元信息
- 调用 `get_ms1_spectrum(dataset["slug"], dataset["source_root"], spec_id)`
  - `slug` 用于 fallback 目录名
  - `source_root` 优先定位（导入时写入的绝对路径）
- 捕获 `SpectrumNotFoundError`：
  - 转成 HTTP 404，并把缺失路径信息写进错误消息（便于排查数据目录问题）

## L31-L39：`GET /datasets/{slug}/spectra/ms2/{spec_id}`

- 同 MS1，只是子目录为 `topfd/ms2_json`
- 同样走 `spectrum_cache` 的统一解析与 LRU 读缓存

