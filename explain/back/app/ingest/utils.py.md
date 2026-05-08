# `back/app/ingest/utils.py` 逐行解释

> 来源文件：`back/app/ingest/utils.py`

## L1（模块定位）

- 该模块提供 ingest 流程的通用小工具：
  - 把 TopPIC 导出的“字符串数字”安全转为 int/float
  - 兼容 TopPIC JSON 中“数组长度为 1 时被压扁成对象”的情况
  - 在一组 PrSM 摘要里选出 best（最小 e-value）

## L8-L15：`to_int`

- 对输入做容错：
  - None/空字符串 → 返回 default
  - 否则尝试 `int(float(value))`：
    - 允许 `"3.0"` 这种字符串
    - 允许 `"3"` 或 `3` 或 `3.2`（会截断）
  - 解析失败（TypeError/ValueError）→ 返回 default

## L18-L25：`to_float`

- None/空字符串 → default
- 否则尝试 `float(value)`
- 失败 → default

## L28-L34：`ensure_list`

- TopPIC 有时会把单元素数组输出为单个对象（不是 list）
- 该函数把：
  - None → []
  - list → 原样
  - 其它 → [value]

## L37-L49：`best_prsm(prsms)`

- 遍历 prsms（每个元素是 dict）：
  - 从中提取 `prsm_id` 与 `e_value`
  - 跳过无法解析 id 的项
  - 用“最小 e_value”为 best
- 返回 `(best_id, best_e_value)`；若没有合法 id 则 `(None, None)`

