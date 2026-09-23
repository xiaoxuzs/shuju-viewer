# mzml-demo

单独的最小化 demo，和 `back/` `front/` 那套主 viewer 完全独立。

做的事：

1. 把一个 `.mzML` 文件一次性读入内存，按 `scan` 建索引。
2. 按 TopPIC HTML 输出的 `prsm*.js`（和 `prsm0.js` 同格式）里写的：
   - `ms.ms_header.scans` → 对应 mzML 里哪张 MS2
   - `ms.ms_header.ms1_scans` → 对应 mzML 里哪张 MS1
   - `ms.peaks.peak[*].matched_ions` → MS2 匹配到的碎片离子
   - `annotated_protein.annotation` → 蛋白序列和切割点标注
3. 在前端同时画 MS1、MS2（叠加匹配离子标签）、序列切割阶梯。

只做展示，不落库，不和主 viewer 打通。

---

## 目录

```text
mzml-demo/
  app.py                    # FastAPI 后端，单文件
  requirements.txt
  README.md
  scripts/
    prsmup.py                 # 从 TopPIC prsm.xml + TopFD msalign 生成 prsm*.js
  static/
    index.html              # 前端单页
    app.js                  # Plotly.js 渲染逻辑
  data/                     # 生成的 prsm*.js 放这里（运行时 app.py 会扫这个目录）
```

---

## 本地运行（Windows / PowerShell）

下面所有命令默认当前目录是 **`mzml-demo/`**（例如 `E:\viewer\mzml-demo`）。路径请按你本机数据位置替换；下文以仓库旁的 `xzx_PXD045330` 为例。

### 流程概览（按顺序）

| 步骤 | 是否必做 | 做什么 |
|------|----------|--------|
| A. 虚拟环境 + 依赖 | **必做**（首次或换机器） | 安装 FastAPI、pyteomics 等，`app.py` 才能跑 |
| B. `data/prsm*.js` | 若 `data/` 里已有可**跳过** | 否则用 `prsmup.py` 从 `prsm.xml` + `msalign` 生成 |
| C. `python app.py --mzml ...` | **必做** | 读入 mzML、挂 HTTP，供浏览器访问 |
| D. 浏览器打开 | **必做** | 选 PrSM、看图 |

**关键约定**：`app.py` 必须用**装过 `requirements.txt` 的那个 Python** 运行。最常见错误是在未激活 venv 时执行了系统自带的 `python`，会得到 `ModuleNotFoundError: No module named 'fastapi'`。

**日常最短命令**（`.venv` 已存在、`data/` 里已有 `prsm*.js`、只需换 mzML 路径时）：

```powershell
cd E:\viewer\mzml-demo
.\.venv\Scripts\Activate.ps1
python app.py --mzml "你的同实验.mzML" --port 8765
```

`--data` 省略时即为当前目录下的 `data/`。

### A. 虚拟环境与依赖（必做）

1. 进入目录：

   ```powershell
   cd E:\viewer\mzml-demo
   ```

2. 若还没有 `.venv`，创建一次（已有则跳过）：

   ```powershell
   python -m venv .venv
   ```

3. **二选一**使用 venv 里的解释器（不要混用系统 `python` 跑 `app.py`）：

   - **推荐**：激活后再敲 `python`：

     ```powershell
     .\.venv\Scripts\Activate.ps1
     pip install -r requirements.txt
     ```

   - **不激活**：全程写全路径（适合脚本或 CI）：

     ```powershell
     .\.venv\Scripts\python.exe -m pip install -r requirements.txt
     ```

4. 若 `Activate.ps1` 报「无法加载，因为在此系统上禁止运行脚本」，仅当前窗口放开执行策略即可：

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\.venv\Scripts\Activate.ps1
   ```

激活成功后，提示符前一般会出现 `(.venv)`；此时后面的 `python` 都指向本项目的 venv。

### B. 准备 `prsm*.js`（无现成文件时必做）

`app.py` 会从 `--data` 目录（默认 `mzml-demo/data`）扫描 `prsm*.js`。若你已有 TopPIC HTML 包里的 `prsms/prsm*.js`，复制到 `data/` 即可，**不必**跑脚本。

若没有 HTML、只有 TopPIC `prsm.xml` 和 TopFD `*_ms2.msalign`，用 `scripts/prsmup.py` 生成（**仅标准库**，可用系统 `python` 或 venv 的 `python`，效果相同）。示例：从 `prsm.xml` 里按 `e_value` 取最优的前 10 条，写出 `prsm*.js`（文件名里的数字是 PrSM ID，不一定连续）：

```powershell
# 若已 Activate.ps1，用 python；否则用 .\.venv\Scripts\python.exe
python scripts\prsmup.py `
  --prsm-xml "E:\viewer\shuju\xzx_PXD045330\xzx_PXD045330\toppic\20191118_rvg262_LT_110516-13_1000-1100_Techrep01_ms2_toppic_prsm.xml" `
  --msalign  "E:\viewer\shuju\xzx_PXD045330\xzx_PXD045330\topfd\20191118_rvg262_LT_110516-13_1000-1100_Techrep01_ms2.msalign" `
  --out-dir  "data" `
  --limit    10
```

常用参数：`--limit` 条数；`--tolerance-ppm` 默认 `10`，控制 b/y 与去卷积峰的 ppm 匹配窗口。

### C. 启动 `app.py`（必做）

**必须用已安装依赖的解释器**（激活 venv 后的 `python`，或 `.\.venv\Scripts\python.exe`）。

| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `--mzml` | 是 | 无 | 与本次 PrSM **同一次实验、同一文件** 的 `.mzML` 路径 |
| `--data` | 否 | `mzml-demo/data` | 含 `prsm*.js` 的目录 |
| `--host` | 否 | `127.0.0.1` | 监听地址 |
| `--port` | 否 | `8765` | 端口被占用时可改成 `8766` 等 |

示例（路径按你本机 mzML 调整）：

```powershell
python app.py `
  --mzml "E:\viewer\shuju\xzx_PXD045330\xzx_PXD045330\20191118_rvg262_LT_110516-13_1000-1100_Techrep01.mzML\20191118_rvg262_LT_110516-13_1000-1100_Techrep01.mzML" `
  --data "data" `
  --port 8765
```

未激活 venv 时的等价写法：

```powershell
.\.venv\Scripts\python.exe app.py --mzml "..." --data "data" --port 8765
```

启动后终端会打印 `[mzml] loading: ...` 和已加载谱图数量。示例数据约 2048 张谱、mzML 约 30MB，加载常在数秒到十余秒量级。

### D. 打开浏览器

在浏览器访问：<http://127.0.0.1:8765/>（若改了 `--port`，请改 URL 端口。）

左上角下拉选一个 `prsm*.js`，下方会出现：

- **Summary**：蛋白、E/P-value、前体质量电荷、MS1/MS2 scan 号
- **Sequence annotation**：整条 proteoform 序列，匹配到 N 端离子 / C 端
  离子的切割位点以蓝/红竖线和背景色标出；如果有 mass shift，会在下方
  列出位置和数值
- **MS1 spectrum**：该 MS2 对应的父 MS1 原始谱，叠加一个前体隔离窗口
  的半透明矩形，并标出前体 m/z 和电荷
- **MS2 spectrum**：mzML 里那张 MS2 的原始峰（灰色），叠加 `prsm.js`
  里匹配到的 b/y 离子（红色柱 + 离子标签 + hover 显示 ppm）

### 启动常见问题

- **`ModuleNotFoundError: No module named 'fastapi'`**  
  当前 `python` 不是 venv 里的。请先 `Activate.ps1`，或改用 `.\.venv\Scripts\python.exe app.py ...`，并在该解释器下执行过一次 `pip install -r requirements.txt`。

- **下拉列表为空**  
  `--data` 指向的目录里没有 `prsm*.js`。完成上文步骤 B，或把已有 `prsm*.js` 放进该目录。

- **谱图对不上或 MS1/MS2 异常**  
  `--mzml` 必须与生成这些 PrSM 的那次运行、那份原始谱一致；换 mzML 需重启 `app.py`。

- **端口已被占用**  
  换一个 `--port`（例如 `8766`），浏览器 URL 同步改端口。

---

## `prsm*.js` 是怎么生成出来的

**重要**：这个 demo 里 `data/prsm*.js` 不是 TopPIC 自己写出来的——手头数据集
（xzx_PXD045330）没带 TopPIC HTML 输出目录。我们是用 `scripts/prsmup.py`
从 **TopPIC 的 `prsm.xml`** + **TopFD 的 `_ms2.msalign`** 这两份源文件拼出来
的，格式严格对齐 TopPIC 官方 `prsm0.js`。

### 数据来源

| 源 | 提供什么 |
|---|---|
| `toppic/..._toppic_prsm.xml` | 鉴定结果：protein accession / 区间 / proteoform 序列 / mass shift / e-value / p-value / MS2 scan 号 |
| `topfd/..._ms2.msalign` | 谱图数据：该 MS2 的去卷积峰（中性单同位素质量+强度+电荷）+ 前体信息 + MS1 父 scan |
| 内建常量 | 20 种氨基酸单同位素质量 + `H2O=18.01056` + `PROTON=1.00728` |

注意：生成 `prsm.js` 的过程**不读 mzML**。mzML 是 `app.py` 启动时在内存里的
那份，只负责给前端画 MS1/MS2 的原始峰；`prsm.js` 里的峰来自 msalign（是去
卷积后的中性单同位素峰）。

### 字段逐项对照（📄=直接从源文件抄, ✏️=脚本算出来）

#### `prsm` 顶层

| 字段 | 来源 |
|---|---|
| `prsm_id`, `p_value`, `e_value`, `fdr` | 📄 `prsm.xml` 里 `<prsm_id>` / `<extreme_value>` 子节点 |
| `matched_fragment_number`, `matched_peak_number` | ✏️ 重新算的命中数（和 TopPIC 官方可能略有差异） |

#### `ms.ms_header` — 全部来自 msalign 头

| 字段 | 来源 |
|---|---|
| `spectrum_file_name`, `ms1_ids`, `ms1_scans`, `ids`, `scans` | 📄 msalign 的 `FILE_NAME` / `MS_ONE_ID` / `MS_ONE_SCAN` / `SPECTRUM_ID` / `SCANS` |
| `precursor_mono_mass`, `precursor_charge`, `precursor_mz`, `feature_inte` | 📄 msalign 的 `PRECURSOR_MASS` / `PRECURSOR_CHARGE` / `PRECURSOR_MZ` / `PRECURSOR_INTENSITY` |

#### `ms.peaks.peak[]` — 一条 peak = msalign 谱块里一行数字

msalign 每个谱块的数字行格式是 `<mass> <intensity> <charge> <score>`：

| 字段 | 来源 |
|---|---|
| `monoisotopic_mass`, `intensity`, `charge` | 📄 msalign 原值 |
| `monoisotopic_mz` | ✏️ `(mass + charge * PROTON) / charge` |
| `peak_id` | ✏️ 数组下标 |
| `spec_id` | 📄 msalign 的 `SPECTRUM_ID` |
| `matched_ions` | ✏️ 如果命中某个理论 b/y，就嵌入（见下） |

#### `matched_ions` — 整段由脚本计算

分三步（见 `scripts/prsmup.py`）：

1. 从 `prsm.xml` 读出 proteoform 序列 `seq` 和 mass shift 列表 `[(l, r, Δ), ...]`；
2. 算理论 b/y 中性质量（`theoretical_by`），对 i = 1..N-1：

   ```text
   b_i = Σ aa_mass[0..i-1]           + Σ Δ （shift 满足 r ≤ i）
   y_i = Σ aa_mass[N-i..N-1]  + H2O  + Σ Δ （shift 满足 l ≥ N-i）
   ```

   语义：mass shift 完全落在 N 端段才加进 b；完全落在 C 端段才加进 y；
   跨切割点的 shift 对这个切割点的离子都不贡献。
3. 匹配（`match_peaks`）：对每条去卷积峰 `m`，遍历 b/y 理论质量，取
   `|ppm| ≤ 10` 且最小的命中；命中的 peak 上挂
   `matched_ions.matched_ion = {ion_type, ion_position, theoretical_mass, mass_error, ppm, ...}`。

#### `annotated_protein`

| 字段 | 来源 |
|---|---|
| `sequence_name`, `sequence_description` | 📄 `prsm.xml` 的 `<fasta_seq>/<seq_name>` / `<seq_desc>` |
| `proteoform_mass` | 📄 msalign 的 `PRECURSOR_MASS` |
| `n_acetylation` | ✏️ `<prot_mod>/<name>` 含 `ACETYLATION` → 1 |
| `unexpected_shift_number` | ✏️ = `<mass_shift_list>` 里 `<mass_shift>` 个数 |

#### `annotated_protein.annotation`

| 字段 | 来源 |
|---|---|
| `protein_length` | ✏️ = `len(proteo_db_seq)`（**是 proteoform 长度，不是原蛋白全长**） |
| `first_residue_position`, `last_residue_position` | 📄 `prsm.xml` 的 `<start_pos>` / `<end_pos>` |
| `annotated_seq` | 📄 `prsm.xml` 的 `<proteo_match_seq>` |
| `residue[]` | ✏️ 把 `proteo_db_seq` 按位拆 `{position, acid}` |
| `cleavage[]` | ✏️ 根据上一步的 matched_ions 反推：对切割位 cp ∈ [0, N]，扫 matched_ions，B 且 `ion_position==cp` 算 N-term 命中、Y 且 `ion_position==N-cp` 算 C-term 命中 |
| `mass_shift` | 📄 `<mass_shift_list>` 第一个条目映射过来 |

### 选谁导出

脚本按 `e_value` 升序（越小越显著）取前 `--limit` 条。命令行里 `--limit 10`
的话，就得到 `prsm0.js ... prsm9.js`（文件名里的数字就是 PrSM ID，不一定连续）。

### 和 TopPIC 官方 `prsm*.js` 的差异

| 项 | TopPIC 官方 | 本脚本 |
|---|---|---|
| 离子类型 | HCD 用 B/Y，ETD/EThcD 用 C/Z_DOT，按 activation 自动选 | 固定 B/Y（我们数据是 HCD，吻合） |
| N 端修饰（NME_ACETYLATION 等）进理论质量 | 是 | 否（demo 简化） |
| ±1 Da 同位素滑移兜底匹配 | 是 | 否 |
| `match_shift` | 按 mass shift 区间与切点关系填 | 固定写 `0.0000000000` |
| `ion_display_position` | 考虑 `start_pos`，按原蛋白全长算 | 等于 `ion_position`（简化） |
| `matched_fragment_number` | 官方原生算 | 重新算，偶尔 ±1 |

**底线**：所有「蛋白 / proteoform / mass shift / 前体 / 谱峰」相关字段都是**直接抄源文件**；所有「哪个峰匹配了哪个理论离子」是**脚本 recompute**（prsm.xml 里本来就没这层明细，只能自己算）。

---

## 核心模块边界

- `app.py`
  - `MzmlStore`：启动时一次性 `pyteomics.mzml.read` 扫全文，按 scan 号
    建 dict。每张谱存 `mz/intensity/ms_level/rt/precursor`。
  - `load_prsm_js(path)`：读 `prsm*.js`，剥掉开头 `prsm_data =` 和结尾
    可选分号，剩下的就是 JSON。
  - `combine_payload(prsm_data, store)`：把 `prsm.js` 里指向的 scan 拿
    到 mzML 里的峰数据，再把 prsm.js 里已有的 `matched_ions` 展开成扁
    平的 `matched_peaks` 列表，打包返回一个固定结构给前端。
  - 三个 HTTP 接口：
    - `GET /api/mzml/status` — mzML 路径、MS1/MS2 张数
    - `GET /api/prsm/list` — 列 `data/` 下的 `prsm*.js`
    - `GET /api/prsm/view?file=xxx.js` — 组装好的 JSON
- `static/` — 纯静态，无构建。

如果你以后想把它塞回主 viewer：

1. 把 `app.py` 里的 `MzmlStore` 搬到 `back/app/services/mzml_store.py`
   作为一个单例，在 `main.py` lifespan 里按路径装载。
2. 把 `combine_payload` 搬到 `back/app/services/prsm_spectrum.py`。
3. 把 `/api/prsm/view` 挂到 `back/app/api/v1/mzml_spectra.py`，路由 URL
   改成 `/api/v1/mzml-viewer/interpret`（或你喜欢的名字），输入参数从
   `file` 改成 `mzml_path + prsm_path`（前端自己传路径，而不是靠 demo
   的 `data/` 目录）。
4. 前端把 `static/app.js` 的渲染逻辑搬成一个 React 组件，塞进
   `front/src/features/` 或者直接嵌进 `PrsmDetailPage.tsx`。`Plotly.js`
   可以用 `react-plotly.js` 或继续用原生 `window.Plotly`（`index.html`
   里加 script 标签即可），也可以用已有的 `d3` 自己画。
5. `prsmup.py` 这种现凑 prsm.js 的脚本在真正集成时就不需要了 —
   主 viewer 直接用 TopPIC HTML 目录里 `toppic_prsm_cutoff/data_js/
   prsms/prsm*.js`（你们 `universal_toppic_adapter.py` 已经在用）。

---

## 已知局限 / 设计取舍

- 启动时才读 mzML，一次只服务一个 mzML。切换文件需要重启进程。
  对 demo 场景够用。
- `prsmup.py` 里 b/y 理论质量用的是标准单同位素 AA 表，忽略了
  isotope shift 1 Da 兜底（TopPIC 实际做的更严谨）。所以 `matched`
  数量可能比 TopPIC 官方 HTML 少一两个。不影响格式正确性。
- N 端修饰（NME / NME_ACETYLATION / M_ACETYLATION）没有专门处理到
  理论质量里，因为现在的数据集里示例 PrSM 大多是 NONE 或 NME（两边
  都用 `proteo_db_seq` 就已经是切除 Met 后的）。需要时在
  `theoretical_by` 里加一个 `n_term_shift` 参数即可。
- MS1 只画一张原始谱，没画 XIC / 同位素包络。那些信息在 TopFD
  `_feature.xml` 里，集成到主 viewer 时再加。
