# DIA-CLIP 导入验收说明

## 用途

`DIA-CLIP导入验收.py` 只读调用正式的 `prepare_diaclip_source` API，验证：

- v1 TSV 表头与唯一性；
- 唯一 `all_report.parquet` 和单运行限制；
- 候选解析、重复折叠、并列分数 FDR；
- 通过阈值的 target 能无歧义回连 DIA-NN 报告；
- 最终公共 `BottomUpSource` 数量一致。

脚本不复制业务算法、不写数据库，也不在主代码中写死本机盘符。

## 运行

PowerShell：

```powershell
$env:VIEWER_DIACLIP_DATASET_ROOT = 'D:\dia-clip'
back\.venv\Scripts\python.exe 'cs\DIA-CLIP导入验收.py'
```

Linux：

```bash
VIEWER_DIACLIP_DATASET_ROOT=/srv/viewer-data/dia-clip \
back/.venv/bin/python 'cs/DIA-CLIP导入验收.py'
```

如需把固定样例作为 golden dataset，可增加：

```text
VIEWER_DIACLIP_EXPECTED_TOTAL_ROWS
VIEWER_DIACLIP_EXPECTED_UNIQUE_CANDIDATES
VIEWER_DIACLIP_EXPECTED_ACCEPTED_TARGETS
```

当前 `D:\dia-clip` 样例的已验证结果为：

| 指标 | 期望值 |
| --- | ---: |
| TSV 总行数 | 584837 |
| 唯一候选 | 584791 |
| 删除的重复行 | 46 |
| target 候选 | 389866 |
| decoy 候选 | 194925 |
| `q-value < 0.01` 的 target | 199322 |

这些数字只属于该 golden dataset，不应写入生产业务判断。

## 数据库 smoke test

只读验收通过后，在隔离的测试数据库中执行一次真实导入，并检查：

1. dataset 的 `source_software` 为 `DIA-CLIP`；
2. `source_import_kind` 为 `DIA_CLIP`；
3. match 数量为验收脚本输出的 `accepted_targets`；
4. match 的 `search_engine` 为 `DIA-CLIP`；
5. `score`、`q_value`、`intensity` 分别来自 DIA-CLIP score、计算 q-value、quant_result；
6. `extra_metadata.diaclip` 中保留来源证据和 DIA-NN 上下文；
7. XIC、MS2 和可用的 PFMB 与同一 Run 正确关联；
8. 同目录再次按 `DIA_CLIP` 导入被拒绝，按 `DIA_NN` 导入不因复合去重键而被拒绝。

不要对生产数据库直接运行破坏性测试，也不要复用生产 slug。

