# `back/app/fingerprint/__init__.py` 逐行解释

> 来源文件：`back/app/fingerprint/__init__.py`
> 模块职责：导出数据集元数据指纹的公开 API，供路径导入去重使用。

## 结构概览

- 包级 docstring 说明：通过快速元数据指纹检测重复，**不读文件内容**。
- 从 `dataset_metadata_fingerprint` 再导出 `MetadataFingerprintResult` 与 `compute_dataset_metadata_fingerprint`。
- `__all__` 限定对外符号，避免内部实现细节泄漏。

## L1-L11

- **L1-L5**：模块定位与语义（与 `MD5-demo/fast_metadata_hash.py` 一致）。
- **L3-L6**：从子模块导入两个公开符号。
- **L8-L11**：`__all__` 列表，供 `from app.fingerprint import ...` 使用。

## 与相邻模块的耦合

- **调用方**：`import_jobs.py` 在导入前计算指纹并写入 `datasets.source_dataset_fingerprint`。
- **实现**：`dataset_metadata_fingerprint.py` 负责递归 scandir 与 MD5 计算。
- **测试**：`back/tests/test_dataset_metadata_fingerprint.py`；性能验收见 `cs/指纹性能测验.py`。
