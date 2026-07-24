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

## 前端展示验收

DIA-CLIP 前端以 `source_software=DIA-CLIP` 为唯一展示分流条件。验收时检查：

1. dataset badge、默认说明、QC 标题和 run 信息都显示 DIA-CLIP；已有描述中的 DIA-NN 在展示层改为 reference；
2. match 列表显示 `DIA-CLIP score`、`DIA-CLIP q-value` 和 `DIA-CLIP quantity`；
3. match 详情显示 `DIA-CLIP evidence`，内部上下文值显示为 `Reference`，不出现 DIA-NN 来源名称；
4. DIA-CLIP 上传说明把 `all_report.parquet` 显示为 context report；
5. 普通 DIA-NN dataset 仍显示 `DIA-NN QC`、`Q.Value` 和 `Intensity`，且不出现 DIA-CLIP score。

定向自动化测试：

```powershell
Set-Location front
pnpm exec playwright test tests/bu-source-presentation.spec.ts tests/bu-evidence-summary.spec.ts tests/import-upload-page.spec.ts
```

自动化测试只能验证稳定的显示契约；发布前还应使用一个真实 DIA-CLIP dataset
人工检查 overview、matches 和任意一个 match 详情页。

## 2026-07-24 本机全链路验收记录

使用 `D:\dia-clip`、显式 `DIA_CLIP` 类型和已转换的 6.677 GB mzML
执行了一次真实路径导入。验收结果：

| 检查项 | 结果 |
| --- | --- |
| ImportJob | `success`，100% |
| RAW 转换复用 | `skipped=1`、`converted=0`、`failed=0` |
| dataset | `READY`，`source_software=DIA-CLIP` |
| run | 1 个 mzML run |
| proteins | 14983 |
| peptides | 169818 |
| matches | 199322 |
| match 来源 | `search_engine=DIA-CLIP`，含 `extra_metadata.diaclip` |
| mzML 扫描索引 | 已生成 |
| TIC 色谱摘要 | 已生成 |
| precursor XIC | 可读取；抽样返回 1188 点 |
| product XIC | 可读取；抽样返回 362 点 |
| MS1 / MS2 | 均可按抽样 match 读取 |

仓库测试结果为 `439 passed, 11 skipped`；另有 37 个 DIA-CLIP、导入路由和
RAW 转换定向测试全部通过。`cs/DIA-CLIP导入验收.py` 使用 golden 计数再次
只读验收通过。

本次样例没有 PFMB sidecar，因此 Fragment Match 按设计跳过；这不影响基础
DIA-CLIP 导入、precursor/product XIC 和 mzML MS1/MS2。样例也没有唯一 FASTA，
所以蛋白序列回填状态为 `skipped/no_unique_fasta`。这两项都属于可选能力，
不能把它们的缺失误报为 DIA-CLIP 主流程失败。

dataset id、run id、match id 和任务 id 都是当前数据库生成的环境值，不得写入
业务判断或自动化测试常量。
