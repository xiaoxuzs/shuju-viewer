## `mzml-demo/scripts/prsmup.py` 逐行解释

> 目标：从 **TopPIC 的 `prsm.xml`** 与 **TopFD 的 `ms2.msalign`** 生成一批 `prsm<id>.js`，使其结构尽量对齐 TopPIC HTML 导出的 `prsm*.js`（根为 `prsm_data = {...}`）。  
> 用途主要在 `mzml-demo`：当你只有 XML + msalign、没有 HTML 包时，也能造出可被 demo/前端读取的明细文件。

---

## L1-L17：文件用途、输入输出与限制

- **L1-L7**：docstring 说明这个脚本会把 XML 鉴定结果与 msalign 去卷积峰合并，并重算匹配到的 b/y 离子。
- **L10-L15**：命令行示例：指定 `--prsm-xml`、`--msalign`、`--out-dir`、`--limit`。
- **L16-L17**：强调生产环境通常直接用 TopPIC 输出的 `prsm*.js`，本脚本是“补齐/演示”用途。

---

## L19-L26：依赖

- **L23**：`xml.etree.ElementTree` 用来解析 `prsm.xml`。
- **L22**：`json` 用来写出 `prsm_data =` 的 JSON 正文。

---

## L28-L46：常量（氨基酸质量、H2O、质子质量）

- **L35-L41**：`AA_MASS`：单同位素质量表（用于计算理论碎片质量）。
- **L43-L45**：
  - `H2O`：y 离子末端水
  - `PROTON`：由中性质量换算 m/z：\((M + z\\cdot p)/z\)

这些常量决定了后续理论质量与 ppm 匹配的数值基准。

---

## L53-L102：`parse_msalign` — 解析 TopFD `_ms2.msalign`

- **L57-L61**：注释解释 msalign 块结构：`BEGIN IONS`…`END IONS`，键值对 + 峰列表（`mass intensity charge ...`）。
- **L62-L64**：`out` 是最终的 `{scan: block}` 映射；`current`/`peaks` 用于构建当前块。
- **L70-L85**：
  - 遇到 `BEGIN IONS` 初始化块
  - 遇到 `END IONS`：把 `peaks` 挂回 `current["peaks"]`，再用 `SCANS` 作为 key 存入 `out`
- **L88-L90**：键值对行：`k=v` 形式存入 `current`。
- **L91-L101**：峰行：解析前三列为 `mass/intensity/charge`，追加到 `peaks`。

输出结构为后续“按 scan 找到去卷积峰”提供 O(1) 访问。

---

## L110-L151：`parse_prsm_xml` — 解析 TopPIC `prsm.xml`

- **L117-L120**：解析 XML 并遍历每个 `<prsm>`。
- **L121-L123**：缺少 `<proteoform>` 的条目跳过（无法构建序列/修饰）。
- **L124-L133**：提取 `mass_shift_list/mass_shift`：
  - `left/right`：区间边界（用于把 shift 加到 b/y 理论质量上）
  - `shift`：质量偏移值
  - `type`：修饰类型名（小写）
- **L134-L149**：收集每条 prsm 关键信息（`prsm_id`、`spectrum_scan`、序列、统计量、位点范围等）。

其中 **`spectrum_scan`** 是后续与 msalign 关联的关键字段（对齐 `SCANS`）。

---

## L158-L190：`theoretical_by` — 计算理论 b/y 中性质量（含 mass shift）

- **L171-L176**：构建前缀质量数组 `prefix` 与总质量 `total`。
- **L179-L188**：对每个切割点 \(i=1..n-1\)：
  - b：`prefix[i]`
  - y：`(total - prefix[i]) + H2O`
  - 再根据 `mass_shifts` 把 Δ 加到对应片段（见函数 docstring 里的区间语义说明）

产物：`b_list` 与 `y_list`（长度均为 `n-1`）。

---

## L192-L227：`match_peaks` — 去卷积峰与理论 b/y 做 ppm 匹配

- **L204-L226**：对每个峰质量 `m`：
  - 遍历所有 `b_list` 与 `y_list`
  - 计算 `ppm = (m - theo) / theo * 1e6`
  - 在 `tolerance_ppm` 内选择 \(|ppm|\) 最小的那一条
- **L225-L226**：命中则记录到 `matches[idx]`：包括 `ion_type`（B/Y）、`ion_position`、`theoretical_mass`、`mass_error`、`ppm`。

这是 demo 级的 \(O(N\\times (n-1))\) 匹配：实现简单，但在大序列/大峰数时会变慢。

---

## L234-L387：`build_prsm_js` — 组装 TopPIC HTML 同形结构（核心输出）

- **L265-L283**：把 msalign 的每个去卷积峰输出为 `peaks_out`：
  - **L270**：将中性质量换算成 m/z：`(mass + charge * PROTON) / charge`
  - **L279-L282**：如果该峰在 `matched` 中：写入 `matched_ions`（按 TopPIC 的子结构/字段名格式化）
- **L286-L329**：把匹配离子按切割位聚类，构建 `cleavage` 列表：
  - B 离子：`cleavage position = pos`
  - Y 离子：通过 `n - pos` 映射到切割位（与注释一致）
  - `exist_n_ion/exist_c_ion` 作为 UI 快速判断
- **L330-L352**：只取第一条 mass shift 作为 `mass_shift`（demo 简化）。
- **L353-L386**：返回整体结构，根键是 `"prsm"`，包含：
  - `ms.ms_header`（FILE_NAME/SCANS/前体信息等）
  - `ms.peaks.peak`
  - `annotated_protein.annotation`（annotated_seq/residue/cleavage/mass_shift）

最终写文件时会再包一层 `prsm_data =`（见 main）。

---

## L389-L394：`_ffmt` — 数值字段统一四位小数

- **L391-L394**：能转 float 就格式化为 `%.4f`，否则返回 `"0"`。

用于把前体等字段变成 TopPIC HTML 类似的字符串表现形式。

---

## L397-L447：命令行入口：选取 Top N 并写 `prsm<id>.js`

- **L398-L409**：解析参数：输入 XML、msalign、输出目录、ppm 容差、导出条数。
- **L411-L413**：解析两份输入。
- **L423-L424**：按 `e_value` 升序排序（越小越好）。
- **L425-L440**：逐条导出：
  - 用 `spectrum_scan` 找到 msalign 块；找不到就 skip
  - 计算 `b/y` → 匹配 → `build_prsm_js`
  - **L436-L438**：写出内容为：
    - 头：`prsm_data =`
    - body：`json.dumps(..., indent=4, ensure_ascii=False)`
- **L442**：打印导出统计。

