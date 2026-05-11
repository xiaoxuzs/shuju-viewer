# `back/app/services/prsm_files.py` 逐行解释

> 来源文件：`back/app/services/prsm_files.py`  
> TopPIC PrSM 明细（`prsm*.js/.json/.txt`）的**发现、排序、定位与读取**，供 API / `import_planner` / ingest 复用。

---

## L1-L10：模块定位、依赖与支持的后缀

- **L1**：文件级 docstring：说明该模块负责 “discovering and reading TopPIC PrSM detail files”，并指出目前支持 `.js/.json/.txt` 三类后缀。
- **L3-L6**：基础导入。
- **L8**：依赖 `app.services.js_parser.load_js_object`：统一处理 “JS 赋值包裹的 JSON”（例如 `prsm_data = {...};`）以及纯 JSON。
- **L10**：`SUPPORTED_PRSM_SUFFIXES`：约定支持的后缀顺序为 `(".js", ".json", ".txt")`，后续用于“优先选哪个文件”。

---

## L13-L16：`is_prsm_file` — 判断一个路径是不是支持的 PrSM 明细

- **L13-L15**：判定条件：
  - 必须是文件（`path.is_file()`）
  - 文件名 stem 必须以 `prsm` 开头（例如 `prsm0`、`prsm123`）
  - 后缀必须在 `suffixes` 允许集合里（统一转小写比较）

该函数是 `iter_prsm_files` 的过滤器，避免把其他辅助文件（如 `index.html`）误认为 PrSM 明细。

---

## L18-L24：`prsm_sort_key` — 让 `prsm123.ext` 按数字排序

- **L20-L23**：尝试把 `path.stem.removeprefix("prsm")` 转 int，返回 `(数字, 文件名)`。
- **L22-L23**：若不是纯数字（例如 `prsmA.js`），给一个很大的数字做兜底 `(1<<30, 文件名)`，确保排序稳定且可复现。

用途：前端分页/列表展示时，按 PrSM id 顺序更符合预期。

---

## L26-L39：`iter_prsm_files` — 列出目录下直接子级的 `prsm*` 文件

- **L33-L34**：目录不存在或不是目录时直接返回 `[]`，调用侧无需 try/except。
- **L36**：`suffixes` 统一小写化，避免 `.JS` / `.Json` 等大小写差异导致漏识别。
- **L37**：仅遍历 `directory.iterdir()` 的**直接子项**，不做递归；用 `is_prsm_file` 过滤。
- **L38**：排序：若调用者提供 `key` 则用调用者的，否则默认按文件名排序（`path.name`）。

注意：如果你想按 `prsm_sort_key` 数字排序，需要在调用处传 `key=prsm_sort_key`。

---

## L41-L43：`has_prsm_files` — 快速判断目录里是否存在至少一个 PrSM 明细

- **L43**：复用 `iter_prsm_files`，用 `bool(...)` 转成 True/False。

---

## L46-L57：`ingest_root_has_supported_prsm_files` — 解压根下是否“某处”有 PrSM 明细

- **L46-L51**：docstring：ZIP 导入在 **TopPIC HTML 树** 场景下要求磁盘上存在可读的 PrSM 明细，以便 mzML 多 run 分配与详情 API 读 `detail_path`。
- **L52-L53**：若 `ingest_root/data/` 下已有支持的 `prsm*` 文件 → 直接 `True`（与 prsm-only bundle 共用 `data/` 的情况也满足）。
- **L54-L56**：否则遍历 `toppic_prsm_cutoff`、`toppic_proteoform_cutoff` 下的 `data_js/prsms/`，任一路径下 `has_prsm_files` 为真即 `True`。
- **L57**：都不满足则 `False`。

该函数被 `import_planner.plan_zip_ingest` 用于：**仅有 `proteins.js` 但没有 PrSM 明细的 HTML 包一律拒绝**，避免导入后无法做 header 级 run 分配或读详情。

---

## L60-L68：`prsm_detail_path` — 给定 `prsm_id`，按后缀优先级选出实际文件

- **L62**：目标 stem：`prsm{id}`。
- **L63**：先用 `iter_prsm_files(directory)` 找出所有 `prsm*` 文件，再筛出 `stem==目标` 的候选，并建立 `{suffix: path}` 映射（suffix 小写）。
- **L64-L67**：按照 `SUPPORTED_PRSM_SUFFIXES` 的顺序依次选取：
  - 先 `.js`
  - 再 `.json`
  - 再 `.txt`
- **L68**：全都没有则返回 `None`。

这个函数把“同一个 prsm id 有多种序列化格式”的兼容处理集中到一处，避免 API 层散落 if/else。

---

## L71-L73：`load_prsm_document` — 读取 PrSM 明细，返回 JSON-like dict

- **L73**：直接委托 `load_js_object(path)`：
  - 对 `.js`：通常会剥掉形如 `prsm_data =` 的包裹并 JSON 解析
  - 对 `.json`：直接 JSON 解析
  - 对 `.txt`：如果仍是 JSON 或 JS 包裹的 JSON，也能同样解析（具体取决于 `js_parser` 的实现）

---

## L76-L88：`get_prsm_root` — 统一 TopPIC 的不同 wrapper

TopPIC 的 PrSM 明细可能出现 3 种形态：

- **L78-L80**：`{"prsm": {...}}`
- **L82-L86**：`{"prsm_data": {"prsm": {...}}}`
- **L88**：否则就把整份 doc 当作 prsm 对象返回（兜底）

该函数的目的：后续字段访问统一从同一个 root 出发，避免到处写 `doc["prsm_data"]["prsm"]`。

---

## L91-L103：`extract_spectrum_file_name` — 从 PrSM 明细提取谱图源文件名

- **L93-L94**：读取文档并标准化 root。
- **L95-L97**：读取路径：`prsm_root["ms"]["ms_header"]["spectrum_file_name"]`（缺失时给 `{}` 兜底）。
- **L98-L102**：做严格校验：
  - 缺字段 → `ValueError(missing ...)`
  - 字符串空白 → `ValueError(empty ...)`
- **L103**：返回去空白后的文件名文本。

典型用途：在 “mzML-memory” 模式下，用该文件名去做 run ↔ mzML 文件的严格映射（保证每个 run 对应的 mzML 可定位）。

---

## 附录：源码顶层符号索引（与 `prsm_files.py` 全文检索对齐）

- `SUPPORTED_PRSM_SUFFIXES`
- `is_prsm_file`、`prsm_sort_key`、`iter_prsm_files`、`has_prsm_files`
- `ingest_root_has_supported_prsm_files`、`prsm_detail_path`
- `load_prsm_document`、`get_prsm_root`、`extract_spectrum_file_name`

