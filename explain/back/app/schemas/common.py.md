# `back/app/schemas/common.py` 逐行解释

> 来源文件：`back/app/schemas/common.py`

## L1（模块定位）

- 定义通用响应模型（目前主要是分页 `Page[T]`）。

## L3-L9（导入）

- `Generic/TypeVar`：让 `Page` 支持泛型（例如 `Page[ProteinListItemOut]`）
- `BaseModel/Field`：Pydantic 模型与字段约束

## L9：`T = TypeVar("T")`

- 泛型参数，用来表达“items 里装什么类型”

## L12-L18：`class Page(BaseModel, Generic[T])`

- `items: list[T]`：当前页数据
- `total: int`：符合筛选条件的总行数（不是仅本页）
- `page/page_size`：分页参数（带默认值与范围约束）

