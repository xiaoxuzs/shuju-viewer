# `mzml-demo/scripts/prsmup.py` 逐行解释

> 来源文件：`mzml-demo/scripts/prsmup.py`  
> 从 **`prsm.xml` + `ms2.msalign`** 生成 `prsm<id>.js`（`prsm_data = {...}`），对齐 TopPIC HTML 形态；供 `mzml-demo` 在无完整 HTML 包时使用。

---

## L1-L17：文件用途、输入输出与限制

- **L1-L7**：docstring 说明这个脚本会把 XML 鉴定结果与 msalign 去卷积峰合并，并重算匹配到的 b/y 离子。
- **L10-L15**：命令行示例：指定 `--prsm-xml`、`--msalign`、`--out-dir`、`--limit`。
- **L16-L17**：强调生产环境通常直接用 TopPIC 输出的 `prsm*.js`，本脚本是“补齐/演示”用途。

---

## L19-L25：依赖

- **L21**：`argparse`（CLI）。
- **L22**：`json`（写出 `prsm_data =` 的 JSON 正文）。
- **L23**：`xml.etree.ElementTree`（解析 `prsm.xml`）。
- **L24-L25**：`Path`、`typing.Any`。

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

## L110-L150：`parse_prsm_xml` — 解析 TopPIC `prsm.xml`

- **L117-L120**：解析 XML 并遍历每个 `<prsm>`。
- **L121-L123**：缺少 `<proteoform>` 的条目跳过（无法构建序列/修饰）。
- **L124-L133**：提取 `mass_shift_list/mass_shift`：
  - `left/right`：区间边界（用于把 shift 加到 b/y 理论质量上）
  - `shift`：质量偏移值
  - `type`：修饰类型名（小写）
- **L134-L149**：收集每条 prsm 关键信息（`prsm_id`、`spectrum_scan`、序列、统计量、位点范围等）。

其中 **`spectrum_scan`** 是后续与 msalign 关联的关键字段（对齐 `SCANS`）。

---

## L158-L189：`theoretical_by`

- **L161-L170**：docstring（mass shift 区间语义；N 端修饰未实现）。
- **L171-L175**：前缀和 `prefix`、总质量 `total`。
- **L179-L188**：对每个切割位算 b/y 并按 `mass_shifts` 加 Δ。
- **L189**：返回两个长度为 `n-1` 的列表。

---

## L192-L226：`match_peaks`

- **L203-L226**：对每个峰在容差内选 `|ppm|` 最小的 B/Y 匹配写入字典。

---

## L234-L248：`_fmt_matched_ion`

- 将内部匹配结果格式化为与 TopPIC `matched_ion` 接近的字符串字段。

---

## L250-L386：`build_prsm_js`

- 合并 XML 条目、msalign 块与 `matched`：构造 `prsm` 根对象（`ms_header`、`peaks`、注释/cleavage 等）。写盘外包见 `main` **L436**。

---

## L389-L394：`_ffmt`

- 四位小数字符串或 `"0"`。

---

## L397-L446：`main`

- **L397-L409**：CLI 参数。
- **L411-L412**：解析输入。
- **L423-L440**：排序、循环、`theoretical_by` → `match_peaks` → `build_prsm_js`、写 `prsm_data =` + JSON。
- **L442**：完成统计。
- **L445-L446**：脚本入口。

---

## 附录：源码顶层符号索引（与 `prsmup.py` 全文检索对齐）

- `parse_msalign`、`parse_prsm_xml`、`theoretical_by`、`match_peaks`
- `_fmt_matched_ion`、`build_prsm_js`、`_ffmt`、`main`

