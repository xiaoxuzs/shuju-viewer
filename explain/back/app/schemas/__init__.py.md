# `back/app/schemas/__init__.py` 逐行解释

> 来源文件：`back/app/schemas/__init__.py`

## L1（模块定位）

- 该文件把后端对外使用的 Pydantic 响应模型集中导出，供 API 路由与 OpenAPI 引用。

## L3-L12（聚合导入）

- 从各子模块导入：
  - `common.Page`：分页包装
  - `dataset.*`：Dataset/Cutoff/删除返回
  - `protein.*`：Protein/Proteoform/PrSM 的列表与详情输出模型

## L14-L25：`__all__`

- 显式声明对外导出的符号列表：
  - `from app.schemas import ...` 时只暴露这些名字
  - 防止内部实现细节“意外成为公共 API”

