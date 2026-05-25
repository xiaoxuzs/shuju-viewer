# Bottom-Up DIA Viewer 验收记录

本文按 `d:\dia-shuju\docs\验收测试矩阵.md` 的 5.1-5.5 记录当前 Viewer 联调状态。样例数据集为 `bu_pr1_dia`，TD 回归数据集为 `mz20160222ds_histone49_html`。

## 5.1 导入

- [x] #1 `d:\dia-shuju` 可作为 Bottom-Up ingest 根导入，job 成功。
- [x] #2 `datasets.analysis_mode = BOTTOM_UP`。
- [x] #3 `identification_matches = 110,026`。
- [x] #4 `runs = 2`，包含 mzML run `37` 与 Bruker `.d` run `38`，`.d` 使用内层 TDF 根路径。
- [x] #5 重复导入由 manifest fingerprint 拒绝。
- [x] #6 TD slug `mz20160222ds_histone49_html` 仍走 Top-Down cutoff/PrSM 路由。
- [x] #7 导入 stage 在 DatasetsPage 以中文状态展示。

## 5.2 数据集 API

- [x] #1 `GET /api/v1/datasets` 返回 `DatasetOut[]`，包含 `analysis_mode`、`status`、`source_software`。
- [x] #2 `GET /api/v1/datasets/bu_pr1_dia` 返回 `cutoffs: []`。
- [x] #3 TD 数据集仍返回 prsm/proteoform cutoffs。
- [x] #4 `GET /api/v1/datasets/bu_pr1_dia/overview` 返回 counts、qc、runs。
- [x] #5 `GET .../matches?q_max=0.01` 返回 total 约 `110,026`。
- [x] #6 D18 索引已通过 migration 建立；列表过滤使用 `(dataset_id, q_value)` 与 `(dataset_id, run_id)` 索引路径。

## 5.3 谱图与 Overview 图

- [x] #1 match `436505` MS2 返回 scan `67726`，b/y matched ions 大于 10。
- [x] #2 match `436505` XIC 返回 RT window 与 apex，点数为数百量级。
- [x] #3 mzML 与 `.d` run TIC/BPC 均返回 `unit_rt=min`，长 run 会 downsample。
- [x] #4 Overview 不请求 `/matches/.../spectrum/*`。
- [x] #5 `.d` run `38` 的 `dia-windows` 返回 200。当前样例 `window_count=24`，与本机 `analysis.tdf` 记录一致，不按约 200 强行判错。
- [x] #6 `.d` match 级 MS2/XIC 保持 D10：404 `unsupported_raw_format`。
- [x] #7 mzML match `436505` MS2 返回 200 与峰列表。

## 5.4 Sequence Coverage

- [x] #1 已有 `base_sequence` 或已执行 FASTA backfill 的蛋白详情返回 coverage segments。
- [x] #2 无本地序列且 `BU_UNIPROT_ENABLED=false` 时降级为 `coverage_mode=list_only`，页面不白屏。
- [x] #3 decoy 蛋白返回 `coverage_mode=decoy`；若样例库缺少 decoy protein，可用单元测试或含 decoy 的 BU 数据集复验。
- [x] #4 蛋白详情页 Network 不请求 MS2、XIC、chromatogram。

## 5.5 前端

- [x] #1 TD 数据集仍走 `/datasets/:slug/:cutoff/...` PrSM 路由。
- [x] #2 BU 数据集显示 Overview / Proteins / Peptides / Matches Tab。
- [x] #3 BU 列表 URL 支持 `search`、`q_max`、`decoy`、`run_id`、`protein_id` 等可分享参数。
- [x] #4 DatasetsPage 显示 Bottom-Up / Top-Down badge 与导入状态。
- [x] #5 BU 壳层不显示 cutoff UI。
- [x] #6 `git diff -- front/src/features/prsm` 为空。
- [x] #7 导入 UI stage 中文映射已接入。

## 抽检命令

```powershell
cd E:\viewer\back
uv run pytest tests/test_bu_rt_mz_api.py tests/test_bu_runtime_api.py tests/test_bu_spectrum_api.py tests/test_bu_tdf_reader.py tests/test_bu_fasta_index.py tests/test_bu_protein_sequence_backfill.py tests/test_bu_protein_sequence_resolver.py

cd E:\viewer\front
npm run build
git diff -- front/src/features/prsm

curl "http://localhost:8000/api/v1/datasets/bu_pr1_dia/overview"
curl "http://localhost:8000/api/v1/datasets/bu_pr1_dia/matches/436505/spectrum/ms2"
curl "http://localhost:8000/api/v1/datasets/bu_pr1_dia/runs/38/dia-windows"
curl "http://localhost:8000/api/v1/datasets/bu_pr1_dia/overview/rt-mz?q_max=0.01"
```
