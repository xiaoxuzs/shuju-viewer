# PFMB 模块验收（viewer-TD/test）

对齐交付说明：

- **主程序**：`../PFMB/pfmb_bridge.exe`
- **必验流程**：`ingest` → `run` → 二进制 `results.pfmb`（见 [`PFMB_BRIDGE_EXE.md`](../PFMB/PFMB_BRIDGE_EXE.md) §2.2、§3）
- **可选联调**：`egress` 导出 JSON/CSV（§4）
- **Python 读二进制**：[`pfmb_io.py`](../PFMB/pfmb_io.py) + [`DEVELOPER_PFMB.md`](../PFMB/DEVELOPER_PFMB.md)（需同目录 **`pfm.py`**）

测试数据：`test/xzx_PXD045330/`（330 类：xml + msalign + mzML）

---

## 一键验收

```powershell
cd e:\viewer\viewer-TD\test
python pfmb_验收.py
```

| 模式 | 命令 | 验什么 |
|------|------|--------|
| **完整**（默认） | `python pfmb_验收.py` | ingest + run + egress + 尝试 pfmb_io |
| **仅主链路** | `python pfmb_验收.py --skip-egress` | 只验 ingest → run → `.pfmb` |
| **跳过 Python 读** | `python pfmb_验收.py --skip-pfmb-io` | 不尝试 pfmb_io |

产物：`test/pfmb_work/`（已 gitignore）

---

## 与 PFMB_BRIDGE_EXE.md 的对应关系

### 必验：ingest（§2.2 TopPIC XML + MSALIGN）

```powershell
pfmb_bridge.exe ingest `
  --source xml_msalign `
  --prsm-xml "...\toppic\..._toppic_prsm.xml" `
  --ms2-msalign "...\topfd\..._ms2.msalign" `
  --cache ".\pfmb_work\prsm.cache" `
  --manifest ".\pfmb_work\cache_build.manifest.json"
```

### 必验：run（§3）

```powershell
pfmb_bridge.exe run `
  --cache ".\pfmb_work\prsm.cache" `
  --output ".\pfmb_work\engine_out" `
  --preset native_coverage `
  --rebuild-frag-cache
```

检查：

- `engine_out/results.pfmb` 存在，文件头魔数 **`PFMB`**（`DEVELOPER_PFMB.md` §3）
- `engine_out/summary.json` 中 `processed_ok` = ingest 的 `records`

### 可选：egress（§4 联调）

```powershell
pfmb_bridge.exe egress --cache "...\prsm.cache" --pfmb "...\results.pfmb" `
  --all --format json --out-dir ".\pfmb_work\egress"
```

---

## pfmb_io.py（Python 联调）

```python
from pfmb_io import PfmbReader

with PfmbReader("pfmb_work/engine_out/results.pfmb") as r:
    rec = r.read_record(0)
```

**当前交付缺口**：`viewer-TD/PFMB/` 仅有 `pfmb_io.py`，**缺少 `pfm.py`**，`import pfmb_io` 会 `ModuleNotFoundError: pfm`。验收脚本对此会 **WARN 并 SKIP**，不影响 ingest/run 主链路通过。

请补齐 `pfm.py`（或完整 PFMB 交付包）后再验 Python 直读路径。

---

## egress JSON 实测形状（联调用）

- `prsm{N}_peaks.json`：顶层 `rows[]`（每峰一行，`matched` 布尔）
- `_index.json`：顶层 `items[]`、`total_prsm`

这与统一适配层文档 §6 草案不同，**以 bridge egress 输出为准**。

---

## 2026-05-28 实测（xzx_PXD045330）

| 步骤 | 结果 |
|------|------|
| ingest | 44 records → `prsm.cache` |
| run | `results.pfmb`，~3.7s，11.8 PRSM/s |
| egress | 44 × `prsm*_peaks.json`，matched_peak_ratio ≈ 0.29 |
| pfmb_io | **SKIP**（缺 `pfm.py`） |
