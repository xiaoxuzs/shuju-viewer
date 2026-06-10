# 注意！！！dia-ms2-pipei 少的内容

> 记录 `dia-ms2-pipei/Hela_DIA_v2_for_frontend` 交付包**实际缺失**的文件，
> 以及由此导致的接入阻塞。接入规划见 `dia-ms2-pipei/接入规划总览.html`。

最后核对：2026-06-09

> **更新 2026-06-09（下午）**：数据生成方已补交 `pfm.py`（放在
> `dia-ms2-pipei/Hela_DIA_v2_for_frontend/pfm.py`，已纳入 git，非忽略）。
> **`results.pfmb` 已可读**，`back/app/pfmb/reader.py` 已实现并通过验证
> （`cs/test_pfmb_reader.py`，O(1) 随机读，prsm_index==record_index）。
> 本文下方"缺失/阻塞"内容中关于 `pfm` 包的部分**已解除**，其余仍未交付。

---

## 1. 一句话结论

交付包最初只给了**数据文件**和一层**门面** `pfmb_io.py`，缺真正实现二进制解析的 `pfm` 包。
**现已补交 `pfm.py`，`results.pfmb` 可读、`reader.py` 已完成。** 仍缺：格式文档
`DEVELOPER_PFMB.md`、`prsm.v2.mapping.jsonl`、`pfmb_bridge.exe`（均非阻塞）。

---

## 2. 交付包里**实际有**什么

路径：`e:\viewer\dia-ms2-pipei\Hela_DIA_v2_for_frontend\`

| 文件 | 状态 | 说明 |
|------|------|------|
| `data/index.json` | ✅ 有（~200MB） | 前端主索引，`{"version","items":[...]}`，每条含 `prsm_index/source_row/slot_index/slot_rt/peptide/precursor_charge/apex_slot/...` |
| `data/results.pfmb` | ✅ 有（~282MB） | 峰–碎片匹配主结果（二进制），**但缺解析器，读不了** |
| `data/prsm.cache` | ✅ 有（~252MB） | 随机读偏移缓存 |
| `data/prsm.v2.manifest.json` | ✅ 有 | 生成参数、字段样例（`input_rows=110024`，`expanded_records=834455`） |
| `data/summary_eval.json` | ✅ 有 | 全库评估（覆盖率 ~81%）。注意：README 写的是 `data/eval/summary_eval.json`，实际在 `data/` 根下，无 `eval/` 子目录 |
| `pfmb_io.py` | ⚠️ 有但**只是门面** | 全部内容是 `from pfm import (...)`，自身**无任何算法** |
| `README.md` | ✅ 有 | 接入说明 |

---

## 3. 交付包里**缺失**什么（README 提到但实际不存在）

| 缺失项 | README 里的位置 | 影响 | 严重度 |
|--------|----------------|------|--------|
| ~~**`pfm` 包**~~（已补交 `pfm.py`） | `pfmb_io.py` 第一行 `from pfm import ...` 依赖它 | ✅ 已解除：`reader.py` 经 `pfm.py` 读取 `results.pfmb` | ✅ 已解决 |
| `docs/DEVELOPER_PFMB.md` | README §1「PFMB 二进制格式」 | 没有格式规范文档（但 `pfm.py` 源码已能说明格式，影响降低） | 🟢 低 |
| `data/prsm.v2.mapping.jsonl` | README §1 / §4 | JSONL 流式索引缺失（内容与 `index.json` 同；`index.json` 仍在，可替代） | 🟡 中（有替代） |
| `pfmb_bridge.exe` | README §1 / §3.2 | 单条导出 CSV/JSON 的可选工具缺失（非必需） | 🟢 低 |
| `data/eval/` 子目录 | README §1 路径 | 实际文件在 `data/summary_eval.json`，仅路径不符 | 🟢 低 |

> `pfmb_io.py` 的实际内容（确认它只是 re-export，无算法）：
>
> ```python
> from pfm import (
>     BUNDLE_FORMAT_VERSION, BUNDLE_MAGIC, INDEX_VERSION, MAGIC, MAGIC2,
>     PfmbRecord, PfmbReader, load_pfmb_bundle, read_pfm, summarize_pfmb,
>     export_pfmb_prsm_to_json, write_pfmb_lean_bundle, write_pfm_bundle,
>     encode_pfm_columns, encode_pfm_record, _COLS as MATCH_COLUMNS,
> )
> ```

`manifest.json` / `summary_eval.json` 里的源路径显示 `pfm` 引擎在**数据生成方机器**上
（如 `C:\Users\taipi\Desktop\11\...`、`E:\ABC\bottom up\...`），未随包交付。

---

## 4. 当前状态（Step 2/3/4 完成后）

- ✅ `back/app/pfmb/index_reader.py`：读 `index.json`，`(peptide,charge)→source_row` 映射（RT 消歧）+ `get_slots`。验证 `cs/test_index_reader.py`。
- ✅ `back/app/pfmb/reader.py`：经 `pfm.py` 读 `results.pfmb`，O(1) 按 `prsm_index` 读注释。验证 `cs/test_pfmb_reader.py`。
- ✅ `back/app/pfmb/locator.py` + `bu/services/ms2_annotation_svc.py` + `api/v1/bu/ms2_annotations.py`：2 个 endpoint（ms2-slots / ms2-annotation）。
- ✅ 导入链路（`universal_diann_adapter.py`）：`--pfmb-sidecar-dir` 探测 sidecar，写 `capabilities.has_ms2_pfmb` + `extra.ms2_annotation`，并把每条 match 的 source_row + RT slots **烤进** `extra_metadata.pfmb`（运行时不再加载 200MB index.json）。`bu_pr1_dia` 重灌验证：烤入率 110023/110026。端到端 `cs/test_ms2_annotation.py`。
- ✅ 规划 Step 5 前端接入：`BuMatchDetailPage` 在 `capabilities.has_ms2_pfmb` 为真时，于 mzML MS2 卡片之后**并列**渲染 `BuPfmbAnnotationCard`（RT slot 按钮选择器，默认 apex；`BuPfmbFragmentTable` 支持 b/y/c/z•）。`tsc --noEmit` 通过。
- ⛔ 规划 Step 6 的 `frag.chrom` 热力图需读原始 `pos.pkl`，`pos.pkl` 不在包内（README §5：在 `E:\ABC\bottom up\...`）。该 Step 仍受阻，但属可选项。

`pfm.py` 通过 `VIEWER_PFM_DIR` 环境变量可覆盖位置；`results.pfmb` 路径由数据集
`extra_metadata.ms2_annotation`（Step 4）提供，验证脚本用 `VIEWER_PFMB_RESULTS` 覆盖。

---

## 5. 仍未交付（均非阻塞）

1. `docs/DEVELOPER_PFMB.md` 格式规范（`pfm.py` 源码已能替代说明）。
2. `prsm.v2.mapping.jsonl`（内容同 `index.json`，已有替代）。
3. `pfmb_bridge.exe`（单条导出工具，可选）。
4. 原始 `pos.pkl`（仅 Step 6 热力图需要）。
