# `back/app/services/js_parser.py` 逐行解释

> 来源文件：`back/app/services/js_parser.py`

## L1-L6（模块定位）

- 用于解析 TopPIC/TopFD HTML viewer 输出的“JS 数据文件”：
  - 典型形态：`some_var = {...};`
  - 其中 `{...}` 本身是标准 JSON（因此只需去掉赋值壳）
- 该模块只负责“剥壳 + JSON parse”，不做业务字段解释。

## L8-L19（导入与 orjson 优化）

- `json/re/Path/Any`：基础依赖
- 尝试导入 `orjson`：
  - 若存在：优先用 `orjson.loads`（通常更快）
  - 若不存在：fallback 到标准库 `json.loads`

## L21：`_ASSIGNMENT_RE`

- 正则匹配 JS 赋值前缀：
  - 允许变量名：字母/下划线开头，后续字母数字下划线
  - 允许前后空白、`=` 两侧空白
- `re.DOTALL`：让 `.` 匹配换行（这里主要是鲁棒性）

## L24-L30：`strip_js_shell(text)`

- 用 `_ASSIGNMENT_RE` 去掉最前面的 `var =` 壳（只替换一次）
- `strip()` 去掉首尾空白
- 若末尾是 `;`：去掉（兼容 `xxx = {...};`）
- 返回结果应是纯 JSON 文本

## L33-L40：`load_js_object(path)`

- 读文件文本（utf-8）
- 剥壳得到 JSON body
- 用 `orjson.loads` 或 `json.loads` 解析为 Python dict 并返回

## L42-L46：`load_js_object_text(text)`

- 与 `load_js_object` 相同，但输入直接是文本（便于测试或上层已读入内容时复用）

