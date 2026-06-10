# PFMB 与 mzML 字段语义说明（数据与语义确认）

> 目的：在前端/图表使用 PFMB 标注前，确认字段含义及其与 mzML 的关联，避免画出
> "看起来合理、实际含义错误"的图。
>
> 验证脚本：`cs/PFMB字段语义验证.py`（DB 在线 + mzML 可访问时可重跑）。
> 基准数据：`results.pfmb`（Hela_DIA_v2_for_frontend）+ 数据集 `bu_pr1_dia`
> （run_id=39，`20200110_Hela_500ng_DIA_25cm_120min_R1.mzML`，1.4GB，103,988 个 MS2 scan）。
> 结论由上述脚本实测，下方括注为实测数值。

---

## 1. 质量字段：是 **中性单同位素质量（neutral monoisotopic mass）**，不是 m/z

- `observed_neutral_mass` / `theoretical_neutral_mass` 均为**中性质量**（与电荷无关）。
- 实测：把 PFMB 的 `theoretical_neutral_mass` 与按肽段计算的中性 b/y 质量比较，
  `max|Δ| = 2.7e-5 Da`；而与单电荷 m/z 相差恰好约 `1.00725 Da`（一个质子）。
- **画 m/z 谱必须换算**：`m/z = (neutral_mass + z · 1.007276) / z`，其中 `z` 用离子自身的
  `charge` 字段（去卷积电荷），**不要**用前体 `precursor_charge`。
- 对照：实时通路 `theoretical_fragments.match_by_ions` 用 `pyteomics.fast_mass(..., charge=z)`
  得到的是 **m/z**；二者口径不同，混用会整体偏移约 1 个质子。

## 2. intensity：**去卷积后的原始峰强度，未归一化**

- 来源：去卷积峰强度（`pfm.py` 写入时取 `all_peak_intensity[peak]`）。
- 未做任何归一化：实测 `max intensity ≈ 251354`（非 0–1、非百分比、非 max=1）。
- **★ 重要坑**：相当比例的匹配离子 `intensity == 0`（样本实测 **37.9%**，33/87）。
  - 做强度棒图时，这些离子会显示为 0 高度（谱看起来"很稀疏"属正常）。
  - "总离子强度"若直接对 `matched_ions` 求和，会把 0 强度项算进去，
    且**只覆盖匹配峰**，并非该 scan 的真实 TIC（见第 4 节）。
  - 建议：强度可视化前过滤 `intensity > 0`，或明确标注"含 0 强度匹配项"。

## 3. obs / theo / ppm / da：**ppm、da 是已做同位素校正的真实误差**

实测关系（扫描 57,198 个离子）：

```
observed_neutral_mass = theoretical_neutral_mass + mass_error_da + k · 1.003355
mass_error_ppm        = mass_error_da / theoretical_neutral_mass · 1e6   (max|Δ|≈0)
```

- `k ∈ {-1, 0, +1}` 为**同位素偏移**；去掉整数中子后残差 `max = 1.09e-4 Da`（float32 精度）。
- **★ 同位素峰占比 ≈ 1.75%**（1000/57198，`k=±1`，即去卷积选中了 M±1 同位素）。
- **★ 绝对不要用 `(observed - theoretical)` 反算 ppm**：对那 ~1.75% 的同位素峰会得到
  ±900 ppm 的"假大误差"。展示质量误差请**直接用 `mass_error_ppm` / `mass_error_da`**。

## 4. 总峰数 / 未匹配峰 / 总离子强度：**单条记录取不到，只有匹配峰**

- 单条 PFMB 记录只含 `matched_ions`（匹配上的碎片），**没有**该谱的总峰数、未匹配峰列表。
- `matched_peak_count` = 不重复 `peak_id` 数（实测一致）。
- 全局统计只在 `summary_eval.json`：`total_peaks = 9,870,998`，`total_matched_peaks = 7,999,493`
  （整库汇总，**非逐谱**）。
- "总离子强度"只能对匹配离子求和（且含 0 强度项），**不是真实 TIC**。
- **★ 不要把 mzML scan 的峰数当作 PFMB 的总峰数**：mzML 是原始质心峰，PFMB 是 TopPIC
  去卷积后的峰，两套峰集不可直接相减得"未匹配峰"。
- 若确需"未匹配/总峰"：应回到去卷积输出（`*.pos.pkl` / frag 数据），不在本 PFMB 内。

## 5. slot_rt 与 mzML RT：**单位都是秒，DIA-NN RT 是分钟**

- `index.json` 的 `slot_rt`：**秒**（实测 apex=5699.6s，落在 mzML `rt_seconds` 0.4–9000.1 内）。
- mzML 谱图 RT：`rt_seconds`（秒）；前端 `rt_minutes = rt_seconds / 60`。
- DIA-NN 的 `RT`：**分钟**（导入时已 `×60` 转秒后与 index 比对，见 `universal_diann_adapter`）。
- **★ apex slot 恰好落在某个 mzML MS2 scan 上**：`|apex_slot − mzML 最近扫描| = 0.00s`
  （中位 0、最大 0），说明 slot 的 RT 栅格就是 mzML MS2 scan 的时间栅格，二者一一对应。

## 6. 抽取 match 比较 apex slot 与 mzML 最近扫描（实测 12 条）

| 偏差 | 中位 | 最大 |
|------|------|------|
| \|apex_slot − mzML 最近扫描\| | 0.00 s | 0.00 s |
| \|apex_slot − DIA-NN RT\|     | 0.00 s | 13.95 s |
| \|DIA-NN RT − mzML 最近扫描\| | 0.00 s | 13.95 s |

- apex slot 与 mzML 扫描**完全对齐**（0 偏差）→ 用 apex slot 去定位 mzML scan 安全。
- apex slot 与 DIA-NN RT 多数相同，偶有 ~14s（几个 scan）的差：DIA-NN 报告的色谱
  apex 与 PFMB 选定的 apex slot 可能差几个扫描，属正常，**不影响**碎片标注的正确性。

---

## 画图前的硬性提醒（speak before you plot）

1. PFMB 质量是**中性质量**；画 m/z 用 `(neutral + z·proton)/z`，`z` 取离子 `charge`。
2. 质量误差用 **`mass_error_ppm`**，不要用 `(obs−theo)` 反算（同位素峰会假大）。
3. intensity **未归一化**且**约 38% 为 0**；总强度仅为匹配峰之和，非真实 TIC。
4. 单谱**没有**总峰数/未匹配峰；不要拿 mzML 峰数与 PFMB 相减。
5. RT 三套口径：PFMB slot/mzML = 秒，DIA-NN = 分钟；apex slot ↔ mzML scan 0 偏差。
