# `back/tests/test_dataset_metadata_fingerprint.py` 逐行解释

> 来源文件：`back/tests/test_dataset_metadata_fingerprint.py`
> 模块职责：验证元数据指纹算法的稳定性、敏感性与排除规则。

## 测试用例

| 测试 | 断言 |
|------|------|
| `test_fingerprint_stable_ordering` | 同目录两次计算 fingerprint 相同；file_count=2 |
| `test_fingerprint_changes_when_content_changes` | 修改文件内容后 fingerprint 变化 |
| `test_excludes_noise_files` | `.DS_Store` 不计入 manifest |
| `test_zero_files_empty_dir` | 空目录 MD5 为 `d41d8cd98f00b204e9800998ecf8427e`（空串 MD5） |

## 与相邻模块的耦合

- 被测模块：`app.fingerprint.dataset_metadata_fingerprint`。
- 性能目标（≤0.5s）由 `cs/指纹性能测验.py` 验收，本文件仅测正确性。
