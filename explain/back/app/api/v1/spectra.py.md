# `back/app/api/v1/spectra.py` 逐行解释

> 来源文件：`back/app/api/v1/spectra.py`  
> 目标：在 **`spectra_source == "topfd_js"`** 时提供 MS1/MS2 原始谱 JSON；数据来自 `topfd/ms1_json`、`topfd/ms2_json` 下的 `spectrum*.js`（由 `spectrum_cache` 解析与 LRU 缓存）。

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
