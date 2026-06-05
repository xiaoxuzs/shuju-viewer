# Hela DIA v2 交付包 — 前端接入说明

**版本**：v2（按 `frag.RT` 每个时间点一条记录）  
**生成日期**：2026-05  

---

## 1. 包内文件

| 文件 | 说明 |
|------|------|
| `data/index.json` | **前端主索引（JSON）**：`items[]` 含 `source_row` / `slot_index` / `slot_rt` / `prsm_index` / `peptide` |
| `data/results.pfmb` | 峰–碎片匹配主结果（约 83.4 万条，二进制，按 `prsm_index` 读） |
| `data/prsm.v2.mapping.jsonl` | 与 `index.json` 同内容（JSONL，便于流式读） |
| `data/prsm.v2.manifest.json` | 元信息、字段样例 |
| `data/eval/summary_eval.json` | 全库覆盖率 ~81.0% |
| `pfmb_io.py` | Python 读 PFMB |
| `docs/DEVELOPER_PFMB.md` | PFMB 二进制格式 |
| `pfmb_bridge.exe` | 可选：单条导出 CSV/JSON |

**矩阵热力图**：仍从原始 `pos.pkl` 读 `frag.chrom`（12 行 × N 列），用 `source_row` + `slot_index` 与注释对齐。

---

## 2. 记录粒度

- **1 条 pkl 行**（一个 precursor）→ **N 条** PFMB（N = 该行 `frag.RT` 列数，常见 6～10）
- `prsm_index`：PFMB 主键（0 … 834454）
- `source_row`：与 `pos.pkl` 列表下标一致
- `slot_index`：`frag.chrom` / `frag.RT` 的列下标（0 起）
- `slot_rt`：该列保留时间（秒）

---

## 3. 读取示例

### 3.1 列表 / 分组（JSON）

```javascript
// index.json
const { items, eval: evalMetrics } = await fetch('index.json').then(r => r.json());
// 按 precursor 分组
const byPrecursor = new Map();
for (const row of items) {
  const k = row.source_row;
  if (!byPrecursor.has(k)) byPrecursor.set(k, []);
  byPrecursor.get(k).push(row);
}
```

单条 `items[i]` 字段：`prsm_index`, `source_row`, `slot_index`, `slot_rt`, `peptide`, `precursor_charge`, `matrix_rows`, `matrix_cols`。

### 3.2 某时间点的峰注释（JSON，按 prsm_index 拉一条）

全库不宜导出 83 万个 JSON 文件。请 **按 `prsm_index` 按需** 从 PFMB 读，或用 bridge 导出单条：

```powershell
.\pfmb_bridge.exe egress --cache data\prsm.cache --pfmb data\results.pfmb `
  --prsm 12345 --format json --out prsm12345.json
```

Python：

```python
from pfmb_io import PfmbReader
with PfmbReader("data/results.pfmb") as r:
    rec = r.read_by_prsm_index(12345)
    peaks = rec.matches  # 列表，可 json.dumps 给前端
```

单条 JSON 结构示例：`{ "prsm_index", "peak_count", "matched_peak_count", "rows": [{ "peak_id", "mz", "matched", "fragment_annotation", ... }] }`。

---

## 4. 与 v1 区别

| | v1 | v2（本包） |
|---|----|----|
| 条数 | 110,024 | 834,455 |
| 时间维 | chrom 取 max，单点 | 每个 RT 列各一条 |
| 索引 | 仅 `_index.csv` | **mapping.jsonl** + `_index.csv` |

---

## 5. 数据路径（原始 pkl，不在本 zip）

`e:\ABC\bottom up\DIANN_2.0\DIANN_2.0\20200110_Hela_500ng_DIA_25cm_120min_R1.mzML.pos.pkl`
