# DIA-CLIP FDR 导入验收说明

`DIA-CLIP_FDR导入验收.py` 只读调用正式的 DIA-CLIP FDR parquet reader 和导入 planner，用于验证服务器上传目录是否满足新契约：

- 恰好一个支持的 `*.diaclip.fdr.parquet`；
- FDR parquet 中恰好一个 `Run`；
- 目录中存在可匹配该 `Run` 的 `.mzML`；
- planner 会把目录识别为 Bottom-Up DIA；
- reader 会按 `Decoy == 0`、`DIAClip.Passed == true`、`DIAClip.Q.Value < 0.01` 计算可导入 target 数。

运行示例：

```powershell
$env:VIEWER_DIACLIP_FDR_DATASET_ROOT = 'D:\dia-clip-upload'
back\.venv\Scripts\python.exe 'cs\DIA-CLIP_FDR导入验收.py'
```

可选固定计数：

```powershell
$env:VIEWER_DIACLIP_FDR_EXPECTED_TOTAL_ROWS = '54988'
$env:VIEWER_DIACLIP_FDR_EXPECTED_ACCEPTED_TARGETS = '54983'
$env:VIEWER_DIACLIP_FDR_EXPECTED_DECOY_ROWS = '5'
```

该脚本不写数据库、不生成派生文件，也不依赖本机固定盘符。真实导入完成后，Viewer 的 post-import derived data 会为 mzML run 生成 scan index 和 chromatogram summary；如果服务器磁盘或权限导致派生数据失败，导入记录仍会保留，但页面会提示重新运行 `scripts/backfill_dataset_derived_data.py`。
