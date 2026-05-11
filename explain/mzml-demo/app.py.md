# `mzml-demo/app.py` 逐行解释

> 来源文件：`mzml-demo/app.py`  
> 独立演示：mzML 全内存索引 + `prsm*.js` 合并，FastAPI 提供浏览器查看；不集成主 `back/`/`front/`。

---

## L1-L9：模块说明与用法

- **L1-L9**：docstring 说明这是 standalone demo，并给出启动命令：`python app.py --mzml ... --data ...`，浏览器打开 `http://127.0.0.1:8765/`。

---

## L11-L24：依赖

- **L13-L18**：`argparse` / `json` / `re` / `sys`、`Path`、`typing.Any`。
- **L20-L23**：FastAPI、CORS、中间件、静态文件与 JSON 响应。
- **L24**：`pyteomics.mzml`：mzML 解析器（逐谱读取）。

---

## L31-L126：常量、`MzmlStore` 与解析辅助函数

### L31-L32：scan 号正则

- **L31**：`_SCAN_RE = re.compile(r"scan=(\d+)")`：从 mzML native id 文本中抽取 `scan=` 后的整数。

### L34-L63：`MzmlStore`（按 scan 索引的全内存谱图）

- **L37-L39**：`path`、`spectra: dict[int, dict]` 初始状态。
- **L41-L55**：`load(path)`：`path.resolve()`、清空 `spectra`、`mzml.read` 循环；`_parse_scan(spec.get("id", ""))` 为 `None` 则跳过；否则 `_extract_spectrum` 写入；每 500 条打印进度。
- **L57-L63**：`status()`：返回 path 字符串、`loaded_scans`、MS1/MS2 计数（遍历 `spectra` 的 `ms_level`）。

### L66-L68：`_parse_scan`

- 对 `native_id` 做 `_SCAN_RE.search`，匹配则 `int(m.group(1))`，否则 `None`。

### L71-L79：`_rt_seconds`

- 从 `scanList.scan` 里找 `scan start time`；`unit_info` 含 `minute` 时把数值乘 60，否则按秒；找不到则 `0.0`。

### L82-L114：`_extract_precursor`

- 只取第一个 precursor；组装 isolation window、selected ion、`parent_scan`（从 `spectrumRef` 再 `_parse_scan`）；内嵌 `_f`/`_i` 做数值转换。

### L116-L126：`_extract_spectrum`

- 输出 `scan`、`ms_level`、`rt_seconds`、mz/intensity 的 list、`precursor`。

---

## L129-L151：`prsm*.js` 解析（TopPIC HTML 形态）

- **L133-L134**：模块级 `_PRSM_HEAD = re.compile(r"^\s*prsm_data\s*=\s*")`。
- **L136-L144**：`load_prsm_js(path)`：读文本；`_PRSM_HEAD.match` 失败则 `ValueError`；剥前缀、去尾部分号、`json.loads`。
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

- **L300-L307**：`parse_args`：必需 `--mzml`；可选 `--data/--host/--port`。
- **L310-L324**：`main`：校验 mzML；`global DATA_DIR` 后设为 `resolve()` 的 data 目录并 `mkdir`；`STORE.load`；`uvicorn.run(app, host=..., port=..., log_level="info")`。
- **L327-L328**：`if __name__ == "__main__": main()`。

---

## 附录：源码顶层符号索引（与 `mzml-demo/app.py` 全文检索对齐）

- `_parse_scan`、`_rt_seconds`、`_extract_precursor`、`_extract_spectrum`
- `load_prsm_js`、`_as_list`、`combine_payload`
- `mzml_status`、`prsm_list`、`prsm_view`、`index`
- `parse_args`、`main`

