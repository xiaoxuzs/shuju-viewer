## `mzml-demo/app.py` 逐行解释

> 这是一个**独立演示程序**：把一个 mzML 文件全部读入内存（按 scan 号索引），再读取 TopPIC 的 `prsm*.js`（`prsm_data = {...}`）并与 mzML 谱图合并，提供 FastAPI 接口给浏览器查看。
>
> 注意：它不直接集成到主项目的 `back/` / `front/`，更像是用来验证 mzML-memory + prsm.js 结构的 “可运行样机”。

---

## L1-L9：模块说明与用法

- **L1-L9**：docstring 说明这是 standalone demo，并给出启动命令：`python app.py --mzml ... --data ...`，浏览器打开 `http://127.0.0.1:8765/`。

---

## L11-L25：依赖

- **L20-L23**：FastAPI、CORS、中间件、静态文件与 JSON 响应。
- **L24**：`pyteomics.mzml`：mzML 解析器（逐谱读取）。

---

## L27-L126：`MzmlStore` — mzML 全量读入内存（按 scan 索引）

### L31-L68：scan 号解析

- **L31**：`_SCAN_RE = re.compile(r"scan=(\\d+)")`：从 mzML 的 native id 文本中抽取 scan 号。
- **L66-L68**：`_parse_scan(native_id)`：正则匹配到就转 int，否则返回 `None`。

### L34-L63：存储结构与加载

- **L34-L40**：`MzmlStore` 保存：
  - `path`：当前加载的 mzML 路径
  - `spectra`：`{scan: spectrum_dict}` 字典
- **L41-L55**：`load(path)`：
  - **L42-L43**：重置状态
  - **L46-L55**：`mzml.read(...)` 逐条读取 spectrum：
    - 用 `_parse_scan(spec["id"])` 抽 scan
    - 用 `_extract_spectrum(spec, scan)` 抽取需要的字段并存入内存
    - 每 500 条打印一次进度

### L71-L79：保留时间（RT）统一为秒

- **L72-L78**：从 `scanList.scan[*]["scan start time"]` 读取，若单位是 minute 则乘 60，统一返回秒数。

### L82-L114：前体（precursor）信息抽取

- **L83-L86**：只取第一个 precursor（demo 简化）。
- **L87-L113**：抽取 isolation window 与 selected ion 的关键字段，并尝试解析 `spectrumRef` 里的 parent scan。
- **L93-L105**：`_f/_i`：把可能是字符串/数值的字段稳健转成 float/int。

### L116-L126：谱图抽取结构

- **L117-L124**：把 `m/z array`、`intensity array` 转成 Python list（便于 JSON 输出）。
- **L125**：附上 `_extract_precursor` 的结果。

---

## L129-L150：`prsm*.js` 解析（TopPIC HTML 形态）

- **L133-L145**：`load_prsm_js(path)`：
  - 用正则 `_PRSM_HEAD` 验证并剥掉前缀 `prsm_data =`
  - 去掉末尾 `;`
  - `json.loads(...)` 得到 `dict`
- **L147-L150**：`_as_list`：把 “可能是单对象/列表/None” 统一成 list，方便后续遍历。

---

## L153-L244：`combine_payload` — 把 prsm.js 与 mzML 谱图合并成前端可用 payload

- **L154-L156**：定位到 `prsm` 与 `ms_header`。
- **L157-L160**：解析 MS2 scan（必需）与 MS1 scan（可缺省）。
- **L161-L168**：从 `MzmlStore` 查找 MS2、推断 MS1（若 prsm 缺失且 mzML precursor 提供了 parent scan）。
- **L169-L196**：遍历 prsm.js 的去卷积峰（`peaks.peak`），输出：
  - `deconv_out`：每个峰的基础信息
  - `matched_flat`：把 `matched_ions.matched_ion` 展平成“每个峰×每条匹配离子”的列表（便于表格展示）
- **L200-L243**：最终返回一个 dict，包含：
  - `summary`：PrSM 统计量 + 扫描号等摘要
  - `ms1` / `ms2`：原始 mzML 谱图点阵 + 去卷积峰/匹配峰
  - `annotation`：注释序列与切割位点信息（来自 prsm.js）

---

## L246-L294：FastAPI 路由与静态页面

- **L250-L260**：创建全局 `STORE`、`DATA_DIR`，并启用 CORS（允许任意来源，demo 便利性）。
- **L262-L265**：`/api/mzml/status`：返回加载状态与 MS1/MS2 数量。
- **L267-L272**：`/api/prsm/list`：列出 `data/` 下 `prsm*.js` 文件名。
- **L274-L285**：`/api/prsm/view`：
  - **L276**：`Path(file).name` 防止路径穿越
  - 读取并解析 prsm.js，合并 mzML 后返回 JSON
- **L287-L293**：挂载 `/static` 并用 `/` 返回 `static/index.html`。

---

## L300-L329：命令行入口与启动

- **L300-L307**：`parse_args`：必需参数 `--mzml`；可选 `--data/--host/--port`。
- **L310-L325**：`main`：
  - 校验 mzML 路径存在
  - 创建/设置 `DATA_DIR`
  - `STORE.load(mzml_path)` 全量加载
  - `uvicorn.run(...)` 启动服务

