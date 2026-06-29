# PFMB / PFM 二进制交付说明（给开发同事）

本文说明峰–碎片匹配结果的**二进制输出**格式、如何在本仓库内读写、以及如何抽检与调试。字节序均为 **Little-Endian**。

---

## 1. 名词与扩展名

| 扩展名 | 含义 |
|--------|------|
| **`.pfm`** | **P**eak **F**ragment **M**atch：单条 PRSM 的匹配结果（一条记录 = 一个 `PFM1` 块）。 |
| **`.pfmb`** | **P**eak **F**ragment **M**atch **B**undle：把多条 PRSM 的 `PFM1` 记录**顺序打包**进一个文件，便于一次分发、一次拷贝。 |

二者都是**自定义二进制格式**（不是通用「二进制」的缩写），不适合用文本编辑器当 UTF-8 打开；应用代码按下面布局解析。

---

## 2. 单条记录：`PFM1`（`.pfm` 或与 bundle 内子块相同）

| 偏移 | 长度 | 类型 | 说明 |
|------|------|------|------|
| 0 | 4 | `bytes` | 魔数：ASCII **`PFM1`** |
| 4 | 4 | `uint32` | `hdr_len`：后续 JSON 头长度（字节） |
| 8 | `hdr_len` | UTF-8 JSON | 元数据 + 可选 `summary`、`series_table`、`timing` 等 |
| 8+hdr_len | 4 | `uint32` | `N`：匹配条数 |
| 之后 | 连续列 | 见下表 | 共 `N` 行，列式存储；**每条匹配固定 29 字节**（列顺序固定） |

### 2.1 列定义（每条匹配 29 字节，顺序不可变）

| 列名 | dtype | 字节 |
|------|--------|------|
| `peak_id` | int32 | 4 |
| `fragment_ordinal` | int16 | 2 |
| `series_idx` | uint8 | 1 |
| `observed_neutral_mass` | float32 | 4 |
| `theoretical_neutral_mass` | float32 | 4 |
| `mass_error_ppm` | float32 | 4 |
| `mass_error_da` | float32 | 4 |
| `intensity` | float32 | 4 |
| `charge` | int16 | 2 |

**`series_idx`**：在 JSON 头的 `series_table`（字符串数组）里按下标取值，得到 `fragment_series`（如 `c`、`y`、`z_dot`、`b`）。  

**Turbo / lean 写入的 bundle**：每条子记录的头里可能只有精简字段（如 `i`、`pep`、`scan`、`spec`、`n`），**离子系列全局表**在 bundle 总头的 `series_table_global`（见下文）；解析时用  

`per_record_series = record_header["series_table"] ?? bundle_header["series_table_global"]`。

---

## 3. 打包文件：`PFMB`（`.pfmb`）

| 偏移 | 长度 | 类型 | 说明 |
|------|------|------|------|
| 0 | 4 | `bytes` | 魔数：ASCII **`PFMB`** |
| 4 | 4 | `uint32` | `bundle_hdr_len` |
| 8 | `bundle_hdr_len` | 见 §3.1 / §3.2 | **v3（当前写入）**：二进制 bundle 头；**v2（旧包）**：UTF-8 JSON |
| 8+hdr_len | `record_count × 8` | `uint64[]` | **偏移表**（`index_version >= 1`）：第 *i* 项指向该条 `uint64 record_len` |
| 之后 | 重复直到 EOF | | 每条：**`uint64` `record_len`** + **`record_len` 字节的 `PFM2`（v3）或 `PFM1`（v2）** |

### 3.1 Bundle 头 v3（二进制，`version=3`）

| 字段 | 类型 |
|------|------|
| `version` | uint32 = 3 |
| `index_version` | uint32 = 1 |
| `record_count` | uint32 |
| `series_count` | uint16 |
| 每个离子系列名 | uint8 `len` + UTF-8 `len` 字节 |

`PfmbReader` 解析后仍暴露 `bundle_header` 字典（含 `header_encoding: "binary"`），与旧代码兼容。

### 3.2 子记录 `PFM2`（v3 默认）

| 字段 | 类型 |
|------|------|
| 魔数 | **`PFM2`** (4B) |
| `prsm_index`, `scan`, `spec_id` | int32 ×3 |
| `peptide_len` | uint16 |
| `peptide` | UTF-8 |
| `N` | uint32 匹配条数 |
| 列数据 | `N` × 29 字节（§2.1，与 `PFM1` 相同） |

### 3.3 旧版 v2（仍可读）

- Bundle 头：JSON（`version=2`，首字节 `{`）。  
- 子记录：**`PFM1`** = 魔数 + JSON 头 + `N` + 列数据。  
- 无偏移表的老包：`index_version` 缺失时首次打开顺序扫描建表。

- **`record_count`**：包内子记录条数。  
- **随机读**：`offset[i]` → O(1) 跳转；`read_by_prsm_index` 先扫二进制/JSON 头建映射。  
- **新包**：`run_batch_fast` → `write_pfmb_lean_bundle` 写出 **v3 + PFM2**。

---

## 4. 本仓库提供的参考实现（推荐直接复用）

| 文件 | 用途 |
|------|------|
| `pfm.py` | 格式常量、写入、`PfmbReader` / `PfmbRecord`、`read_pfm()`、CLI。 |
| **`pfmb_io.py`** | **对外稳定入口**（前端/服务 `from pfmb_io import PfmbReader, load_pfmb_bundle`）。 |
| `evaluate_peak_level.py` | 通过 `load_pfmb_bundle` 读预测结果。 |

### 4.0 Python API（推荐）

```python
from pfmb_io import PfmbReader, load_pfmb_bundle

# 随机读一条 PRSM（有偏移表时 O(1) 定位）
with PfmbReader("results.pfmb") as r:
    rec = r.read_by_prsm_index(123)   # TopPIC 的 prsm 编号
    # rec.peptide, rec.matches, rec.scan, rec.spec_id

# 全量 dict（评估）
pred = load_pfmb_bundle("results.pfmb")  # {prsm_index: [match, ...]}
```

### 4.1 命令行快速抽检（无需自己写解析）

在项目根目录执行（路径按实际修改）：

```bash
# 查看 bundle 头 + 前几条记录的 prsm / match 条数 / 肽段摘要
python pfm.py bundle-show path/to/results.pfmb --head 8

# 将某一 prsm_index 导出为可读 JSON（调试用）
python pfm.py bundle-export path/to/results.pfmb --prsm 0 --out prsm0_preview.json
```

单文件 `.pfm`：

```bash
python pfm.py show path/to/prsm0.pfm
python pfm.py to-json path/to/prsm0.pfm --out prsm0.json
```

---

## 5. 与其它语言 / 服务对接的注意点

1. **不要用文本编辑器「当 UTF-8 全文打开」** `.pfmb`；会提示二进制或乱码。应使用十六进制查看器或按上表解析。  
2. **JSON 头**是 UTF-8，可能含中文肽段序列；**列数据**为定长二进制。  
3. **`series_table_global`** 在 bundle 头时，子记录里可能没有 `series_table`，必须用全局表 + `series_idx` 还原离子系列名。  
4. 版本：当前 bundle 头里常见 `"version": 1`。若将来升级格式，应递增 `version` 并在本文档与代码中同步说明。

---

## 6. 与生成端参数的对应关系（便于对照实验）

平衡版批跑示例参数（与业务约定一致时）：

- 容限：`tol=12` ppm（匹配阶段）  
- 同位素位移层数：`iso_n=1`  
- 每峰保留条数：`top_n=3`  
- 离子系列：`c,z_dot,b,y` → 即 `series_table_global` 中顺序  

具体生成命令见仓库内 `run_balanced.ps1` 或 `run_batch_fast.py` 的 CLI 说明。

---

## 7. 问题反馈

格式或字段含义以仓库内 **`pfm.py` 文档字符串与 `read_pfm` / `load_pfm_bundle` 实现为准**；若发现与本文不一致，以代码为准并建议更新本文档。

---

*文档版本：1 — 与当前仓库 `pfm.py`（PFM1 / PFMB）一致。*
