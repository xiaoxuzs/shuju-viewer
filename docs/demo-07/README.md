# Sequence Coverage 业内参考截图

> 收集时间：2026-06-05  
> 用途：对比 Viewer 当前 `SequenceCoverage` 组件与业内常见实现，供 UI 改版参考。

---

## 如何查看

在资源管理器中打开本目录，或直接双击各 PNG/JPG。  
建议对照阅读顺序：**01（现状）→ 10/11（验收目标）→ 02/05/06（业内主流）**。

---

## 截图索引

| 文件 | 来源 | 说明 |
|---|---|---|
| `01_Viewer当前实现.png` | 本项目 BU 蛋白详情页 | 当前实现：序列文本 + 浅蓝高亮/下划线，右上角 coverage 百分比 |
| `02_ProteomicsDB_蛋白摘要_肽段条带.jpg` | [ProteomicsDB 论文 Fig.2B](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5753189/) | 经典 Web 库：**横向位置轴 + 黑色肽段条 + 结构域图形 + PTM 色块**，右侧统计卡片 |
| `04_AlphaMap_总览.png` | [MannLabs/alphamap](https://github.com/MannLabs/alphamap) | 上传/配置页（非 coverage 本体，但支持 DIA-NN 等输入） |
| `05_AlphaMap_细节.png` | MannLabs/alphamap | **多轨道线性图**：UniProt 注释、酶切位点、修饰、实验 coverage 分层；底部对齐氨基酸序列；可悬停 tooltip |
| `06_pepMAP_DIA-NN交互图.png` | [npinter/pepMAP](https://github.com/npinter/pepMAP) | **DIA-NN 专用** Web 工具：样本为行、位置为列的肽段条带；下方 domain/topology/修饰轨道；悬停显示肽段详情 |
| `07_PepMapViz_示例.png` | [Genentech/PepMapViz](https://github.com/Genentech/PepMapViz) | R/Shiny：**多样本矩阵**（D1–D8 × HC/LC），灰度密度表示 PSM 覆盖，CDR 区域标注，PTM 图例 |
| `08_SCV_3D覆盖示意.jpg` | [SCV 论文](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10232130/) | 3D 结构上的覆盖着色（偏专题方向，Web BU 详情页通常不做） |
| `10_demo_P62805_验收布局.png` | `D:\dia-shuju\demo_07` 生成 | **本项目验收参考布局**：序列按 50 aa 分行着色 + **底部线性 coverage 条** + 肽段色块图例 |
| `11_demo_P60709_验收布局.png` | 同上（Actin beta） | 长蛋白（375 aa）示例，同样双层结构 |

### 未能下载（文档有图、外链防盗链）

- **Proteome Discoverer 3.x Sequence 页**：顶部彩色 coverage bar + 10 列序列矩阵 + PTM 概率色块。见 [PD 3.3 User Guide — Sequence Page](https://docs.thermofisher.com/r/Proteome-Discoverer-3.3-User-Guide/1311505931v1en-US1613998219)。
- **MaxQuant Viewer 蛋白序列区**：右下角 protein sequence view，肽段按 unique/shared 着色，可叠 Pfam/PTM 轨道。见 [Proteomics 2015 论文 Fig.1](https://analyticalsciencejournals.onlinelibrary.wiley.com/doi/10.1002/pmic.201400449)（Wiley 站点有 Cloudflare，自动抓取失败）。

---

## 业内共性（值得借鉴的模式）

### 1. 双层结构：「轨道图 + 序列」

几乎不把高亮只放在字符上，而是：

```
[━━━━ 肽段条带 / coverage bar ━━━━]  ← 一眼看覆盖空洞
M A S P P R H G P ...                  ← 需要时再读氨基酸
```

代表：`10_demo_P62805`、`Proteome Discoverer`、`AlphaMap`。

### 2. 横向位置轴（0 → length）

- X 轴是氨基酸位置，不是「每行 70 字换行」。
- 长蛋白（1000+ aa）用**横向滚动/缩放**，而不是纵向堆很多行文本。

代表：`02_ProteomicsDB`、`05_AlphaMap`、`06_pepMAP`。

### 3. 多轨道（tracks）叠加上下文

常见轨道（自上而下）：

| 轨道 | 内容 |
|---|---|
| 实验肽段 | 每条肽一段色条，可按样本/置信度分色 |
| 结构域 | Pfam / UniProt domain 框 |
| 拓扑 | Extracellular / Transmembrane / Cytoplasmic |
| PTM | 磷酸化、乙酰化等位点标记 |
| 理论酶切 | Trypsin 等预测肽段（可选） |

代表：`02_ProteomicsDB`、`06_pepMAP`、`05_AlphaMap`。

### 4. 颜色语义

- **按肽段分色**（10_demo）：每条 unique 肽一种颜色，图例列出序列。
- **按置信度分色**（Proteome Discoverer）：高/中/低鉴定可信度。
- **按样本分色**（pepMAP / PepMapViz）：比较不同 run/条件。
- **按覆盖密度**（PepMapViz 灰度）：PSM 次数越多越深。

### 5. 交互

- 悬停肽段条 → 显示 sequence、位置、q-value、强度（pepMAP、AlphaMap）。
- 点击图例 → 高亮对应区域。
- 缩放/平移长序列（Plotly 系工具）。

### 6. 统计信息位置

- 页眉：`Coverage 75% · 12 peptides`（demo）。
- 侧栏卡片：unique/shared peptides、spectra 数（ProteomicsDB）。

---

## 与 Viewer 现状的差距

对照 `01_Viewer当前实现.png`：

| 维度 | 现状 | 业内常见 |
|---|---|---|
| 布局 | 纯文本块，70 字换行 | 位置轴 + 轨道图为主，序列为辅 |
| 覆盖表达 | 字符背景色 + 下划线 | 独立色条 / 密度条 |
| 长蛋白 | 纵向很长，难扫空洞 | 横向一条线，滚动即可 |
| 肽段区分 | 蓝/黄两色（mapped/ambiguous） | 多肽多色 + 图例列序列 |
| 上下文 | 无 domain/PTM | 常叠 UniProt 轨道 |
| 交互 | 无 tooltip | 悬停看肽段元数据 |
| 多样本 | 单数据集聚合 | pepMAP 按 run 分行对比 |

---

## 改版建议（按投入产出排序）

### P0 — 接近 demo 验收、改动可控

1. **增加顶部/底部线性 coverage bar**（合并所有 segment 的并集，未覆盖区灰色）。
2. **肽段分色 + 底部图例**（参考 `10_demo_P62805`）。
3. **序列行宽改为 50 aa**，与 demo 对齐。
4. **悬停 segment → tooltip**（sequence、start–end、peptide_id）。

### P1 — 接近 AlphaMap / pepMAP

5. 改为 **横向位置轴 + 可缩放**（可用 SVG 或轻量 canvas，不必上 Plotly）。
6. 增加 **UniProt domain 轨道**（可从 FASTA/UniProt 元数据懒加载）。

### P2 — 进阶

7. 按 **run 分行** 显示肽段（需 API 返回 run 维度 segment）。
8. PTM 位点轨道（依赖 `modified_sequence` 解析）。

---

## 参考链接

| 工具 / 文献 | URL |
|---|---|
| ProteomicsDB | https://www.proteomicsdb.org/ |
| AlphaMap | https://github.com/MannLabs/alphamap |
| pepMAP（支持 DIA-NN） | https://github.com/npinter/pepMAP |
| PepMapViz | https://github.com/Genentech/PepMapViz |
| Proteome Discoverer Sequence 页 | https://docs.thermofisher.com/r/Proteome-Discoverer-3.3-User-Guide/1311505931v1en-US1613998219 |
| MaxQuant Viewer 论文 | https://analyticalsciencejournals.onlinelibrary.wiley.com/doi/10.1002/pmic.201400449 |
| SCV（3D） | http://scv.lab.gy/ |
| 本项目数据方案 | `budocs/Sequence-Coverage数据方案.md` |
| 本项目 demo 脚本 | `D:\dia-shuju\demo\demo_07_sequence_coverage_p62805.py` |

---

## 文件清单（10 张有效截图）

```
01_Viewer当前实现.png
02_ProteomicsDB_蛋白摘要_肽段条带.jpg
04_AlphaMap_总览.png
05_AlphaMap_细节.png
06_pepMAP_DIA-NN交互图.png
07_PepMapViz_示例.png
08_SCV_3D覆盖示意.jpg
10_demo_P62805_验收布局.png
11_demo_P60709_验收布局.png
README.md（本文件）
```
