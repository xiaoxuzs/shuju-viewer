# 数据库入库标准与数据准入模块设计 v0.3

**状态**：草案  
**版本**：`0.3.0`  
**最后更新**：2026-04-28  
**目标**：定义数据库允许接收什么数据，以及外部数据如何经过“准入模块”变成可入库、可展示、可画谱的数据。

---

## 1. 核心结论

本项目未来会接收多种格式的质谱数据，但前端和后端不应该直接适配所有原始格式。

正确流程是：

```text
外部数据
  ↓
数据准入模块
  ↓
是否符合数据库入库标准？
  ├─ 是：直接入库
  └─ 否：进入 Adapter / Normalizer 转换
          ↓
       再次校验
          ├─ 符合：入库
          └─ 不符合：拒绝导入或降级入库
```

所以本规范真正约定的是：

> **数据库里允许存什么样的数据。**

Adapter 的职责是把不同来源的数据转换成这个标准，而不是让数据库和前端去适配所有格式。

---

## 2. 当前数据库定位

当前项目的数据库核心表仍然保留：

- `datasets`
- `cutoffs`
- `proteins`
- `proteoforms`
- `prsms`

这些表已经支撑当前前端后端运行，不建议一开始推翻重建。

但为了支持未来多格式导入，需要补充两类内容：

1. **入库标准**：明确每张表必须有哪些字段。
2. **导入管理能力**：记录数据来源、导入过程、原始文件和错误。

---

## 3. 数据准入模块

### 3.1 模块职责

建议新增一个逻辑模块，暂名：

```text
Data Admission / Import Gateway
```

它负责：

1. 识别数据来源格式。
2. 检查数据是否已经符合数据库入库标准。
3. 若不符合，调用对应 Adapter 转换。
4. 转换后再次校验。
5. 合格后写入 PostgreSQL。
6. 记录导入日志、错误、来源文件和能力信息。

### 3.2 内部流程

```text
detect_format
  ↓
validate_raw_package
  ↓
if already_standard:
    validate_database_payload
else:
    adapter.normalize()
    validate_database_payload
  ↓
import_to_database
  ↓
verify_visibility
```

### 3.3 关键原则

- **数据库是标准**。
- **Adapter 负责适配外部格式**。
- **前端只消费数据库/API 提供的统一结构**。
- **不合格数据不能静默入库**。
- **可降级入库的数据必须明确标记能力缺失**。

---

## 4. 数据库入库标准：Dataset

### 4.1 现有字段

当前 `datasets` 表已有：

- `id`
- `slug`
- `name`
- `description`
- `source_path`
- `created_at`
- `updated_at`

### 4.2 必须满足

入库时必须保证：

- `slug` 全局唯一。
- `name` 非空。
- `source_path` 指向存在的数据根目录，或指向可被后端解析的数据位置。
- 如果该数据集需要画谱，`source_path` 必须能最终定位谱图文件。

### 4.3 建议新增字段

为了支持多格式导入，建议在 `datasets` 增加：

- `source_software`：来源软件，例如 `toppic_topfd`、`vendor_x`。
- `profile`：数据集类型，例如 `topdown_prsm`、`spectrum_only`。
- `raw_data_path`：原始数据归档路径。
- `standard_data_path`：标准化后文件根目录，可空。
- `capabilities`：JSONB，记录支持哪些功能。
- `extra_metadata`：JSONB，兜底存储额外来源信息。

示例：

```json
{
  "source_software": "toppic_topfd",
  "profile": "topdown_prsm",
  "capabilities": {
    "has_ms1": true,
    "has_ms2": true,
    "has_envelopes": true,
    "has_prsms": true,
    "has_matched_peaks": true,
    "has_annotated_sequence": true,
    "has_multi_scan": true
  }
}
```

---

## 5. 数据库入库标准：Cutoff / ResultSet

### 5.1 现有表名

当前数据库表叫：

```text
cutoffs
```

这来自 TopPIC 语义。

未来在设计上建议把它理解为：

```text
ResultSet / AnalysisView
```

也就是“一套分析结果视图”。

### 5.2 现有字段

- `id`
- `dataset_id`
- `kind`
- `label`
- `data_path`

### 5.3 必须满足

- `dataset_id` 必须指向存在的 dataset。
- 同一 dataset 下 `kind` 唯一。
- `kind` 当前可为：
  - `prsm`
  - `proteoform`
- `label` 非空。
- `data_path` 可追踪来源数据位置。

### 5.4 未来扩展

如果未来来源没有 cutoff 概念，也仍然可以创建一个 ResultSet：

```text
kind = "default"
label = "Default result set"
```

不要因为外部格式没有 cutoff 这个词就无法入库。

---

## 6. 数据库入库标准：Protein

### 6.1 现有表名

当前数据库表叫：

```text
proteins
```

Protein 表用于保存某个 ResultSet / Cutoff 下的蛋白或序列条目，是 Proteoform 和 PrSM 的上层归属对象。

### 6.2 现有字段

- `id`
- `cutoff_id`
- `sequence_id`
- `sequence_name`
- `sequence_description`
- `compatible_proteoform_number`
- `prsm_number`
- `best_prsm_id`
- `best_prsm_e_value`

其中：

- `id` 是数据库主键。
- `cutoff_id` 指向 `cutoffs.id`，表示该 protein 属于哪个 ResultSet / Cutoff。
- `sequence_id` 是来源软件中的蛋白或序列业务 ID。
- `sequence_name` 是蛋白或序列名称，当前列表、详情和搜索会使用。
- `sequence_description` 是蛋白描述，例如物种、基因名、数据库描述；可为空。
- `compatible_proteoform_number` 是该 protein 下兼容的 proteoform 数量。
- `prsm_number` 是该 protein 下关联的 PrSM 总数。
- `best_prsm_id` 是该 protein 下最优 PrSM 的业务 id；可为空。
- `best_prsm_e_value` 是最优 PrSM 的 e-value；可为空。

其中 `sequence_description`、`best_prsm_id`、`best_prsm_e_value` 属于当前已有的可选但建议填写字段：

- `sequence_description` 有助于搜索、详情展示和人工识别。
- `best_prsm_id` 可用于从 protein 快速跳转到最佳 PrSM。
- `best_prsm_e_value` 可用于列表排序和质量判断。

### 6.3 必须满足

如果数据集声明支持 `topdown_prsm` 完整功能，入库时必须保证：

- `cutoff_id` 必须指向存在的 `cutoffs.id`。
- `sequence_id` 必须存在；同一 `cutoff_id` 下 `sequence_id` 唯一。
- `sequence_name` 必须存在；如果外部格式没有名称，Adapter 应生成稳定名称。
- `compatible_proteoform_number` 必须存在；没有统计时可填 `0`，但完整 Top-down 数据建议真实填写。
- `prsm_number` 必须存在；没有统计时可填 `0`，但完整 Profile 建议与子项数量一致。
- 如果填写 `best_prsm_id`，它必须能在同一 cutoff 的 `prsms.prsm_id` 中找到。
- 如果填写 `best_prsm_e_value`，它应与 `best_prsm_id` 对应。

### 6.4 未来扩展

为了接收其它格式，建议未来增加：

- `accession`：蛋白数据库 accession，例如 UniProt accession。可空；若来源能提供，建议写入；应与 `sequence_name` 区分。
- `sequence`：氨基酸完整序列。可空；若来源能提供，建议写入；适合长文本存储。
- `extra_metadata`：JSONB，用于存储来源软件特有的 protein 级字段；Adapter 不应把关键关系字段只塞进这里。

### 6.5 约束

- 同一 `cutoff_id` 下 `sequence_id` 唯一。
- 如果外部格式没有 protein，则不能声明完整 `topdown_prsm` 能力。

---

## 7. 数据库入库标准：Proteoform

### 7.1 现有表名

当前数据库表叫：

```text
proteoforms
```

Proteoform 表用于保存某个 Protein 下的蛋白异构体，是 PrSM 的直接上层归属对象。

### 7.2 现有字段

- `id`
- `cutoff_id`
- `protein_id`
- `proteoform_id`
- `sequence_id`
- `sequence_name`
- `proteoform_mass`
- `prsm_number`
- `best_prsm_id`
- `best_prsm_e_value`
- `n_acetylation`
- `unexpected_shift_number`

其中：

- `id` 是数据库主键。
- `cutoff_id` 指向 `cutoffs.id`，表示该 proteoform 属于哪个 ResultSet / Cutoff。
- `protein_id` 指向 `proteins.id`，表示该 proteoform 属于哪个 protein。
- `proteoform_id` 是来源软件中的 proteoform 业务 id，不是数据库主键。
- `sequence_id` 是来源软件中的蛋白或序列业务 ID，应与上层 protein 对应。
- `sequence_name` 是该 proteoform 所属序列名称。
- `proteoform_mass` 是 proteoform 质量；可为空。
- `prsm_number` 是该 proteoform 下关联 PrSM 数量。
- `best_prsm_id` 是该 proteoform 下最优 PrSM 的业务 id；可为空。
- `best_prsm_e_value` 是最优 PrSM 的 e-value；可为空。
- `n_acetylation` 是 N 端乙酰化信息；当前 importer 暂时写入 `None`。
- `unexpected_shift_number` 是 unexpected mass shift 数量；当前 importer 暂时写入 `None`。

其中 `proteoform_mass`、`best_prsm_id`、`best_prsm_e_value`、`n_acetylation`、`unexpected_shift_number` 属于当前已有的可选但建议填写字段：

- `proteoform_mass` 有助于质量展示和筛选。
- `best_prsm_id` 可用于从 proteoform 快速跳转到最佳 PrSM。
- `best_prsm_e_value` 可用于列表排序和质量判断。
- `n_acetylation` 和 `unexpected_shift_number` 有助于展示修饰特征；如果来源不能提供，可为空。

### 7.3 必须满足

如果数据集声明支持 `topdown_prsm` 完整功能，入库时必须保证：

- `cutoff_id` 必须指向存在的 `cutoffs.id`。
- `protein_id` 必须指向存在的 `proteins.id`。
- `proteoform_id` 必须存在；它是业务 id。
- `sequence_id` 必须存在，并应与上层 protein 的 `sequence_id` 对应。
- `sequence_name` 必须存在；如果来源没有名称，Adapter 应生成稳定名称。
- `prsm_number` 必须存在；没有统计时可填 `0`，但完整 Profile 建议与子项数量一致。
- 如果填写 `best_prsm_id`，它必须能在同一 cutoff 的 `prsms.prsm_id` 中找到。
- 如果填写 `best_prsm_e_value`，它应与 `best_prsm_id` 对应。

### 7.4 未来扩展

为了接收其它格式，建议未来增加：

- `modifications`：JSONB，用于保存修饰位点、质量偏移、修饰类型等结构化信息。
- `extra_metadata`：JSONB，用于保存来源软件特有的 proteoform 级字段；Adapter 不应把关键关系字段只塞进这里。

### 7.5 约束

- 同一 `(cutoff_id, protein_id, proteoform_id)` 唯一。
- PrSM 必须能关联到某个 Proteoform。

---

## 8. 数据库入库标准：PrSM

### 8.1 现有表名

当前数据库表叫：

```text
prsms
```

PrSM 表用于保存 proteoform 与 spectrum 的匹配结果，是当前详情页、序列注释、匹配峰表和谱图联动的核心数据表。

### 8.2 现有字段

- `id`
- `cutoff_id`
- `proteoform_id`
- `prsm_id`
- `sequence_id`
- `p_value`
- `e_value`
- `fdr`
- `matched_fragment_number`
- `matched_peak_number`
- `spectrum_file_name`
- `ms1_scans`
- `ms2_scans`
- `ms1_ids`
- `ms2_ids`
- `precursor_mono_mass`
- `precursor_charge`
- `precursor_mz`
- `feature_inte`
- `proteoform_mass`
- `ms_header`
- `ms_peaks`
- `annotated_protein`

其中：

- `id` 是数据库主键。
- `cutoff_id` 指向 `cutoffs.id`，表示该 PrSM 属于哪个 ResultSet / Cutoff。
- `proteoform_id` 指向 `proteoforms.id`，表示该 PrSM 属于哪个 proteoform。
- `prsm_id` 是来源软件中的 PrSM 业务 id；详情页 URL 当前按它查询。
- `sequence_id` 是来源软件中的蛋白或序列业务 ID。
- `p_value`、`e_value`、`fdr` 是质量评估指标；可为空。
- `matched_fragment_number`、`matched_peak_number` 是匹配统计；可为空。
- `spectrum_file_name` 是来源谱文件名；可为空。
- `ms1_scans`、`ms2_scans` 是扫描号文本；可为空，但完整图谱联动建议填写。
- `ms1_ids`、`ms2_ids` 是谱图文件定位 id；完整图谱联动必须可解析。
- `precursor_mono_mass`、`precursor_charge`、`precursor_mz`、`feature_inte` 是前体与 feature 信息；可为空，但建议填写。
- `proteoform_mass` 是该 PrSM 对应 proteoform 质量；可为空。
- `ms_header` 是谱头 JSONB。
- `ms_peaks` 是匹配峰 JSONB。
- `annotated_protein` 是序列注释 JSONB。

### 8.3 必须满足

如果数据集声明支持 `topdown_prsm` 完整功能，入库时必须保证：

- `cutoff_id` 必须指向存在的 `cutoffs.id`。
- `proteoform_id` 必须指向存在的 `proteoforms.id`。
- `prsm_id` 必须存在；同一 `cutoff_id` 下必须唯一。
- `sequence_id` 必须存在。
- `ms1_ids` 必须能解析出至少一个 MS1 spectrum id。
- `ms2_ids` 必须能解析出至少一个 MS2 spectrum id。
- `ms_header` 必须保存来源谱头信息。
- `ms_peaks` 必须保存匹配峰信息。
- `annotated_protein` 必须保存序列注释信息。

完整图谱联动还必须满足：

`ms_header` 中必须能提供：

- `ms1_ids`
- `ids`（MS2 ids）
- `ms1_scans`
- `scans`（MS2 scans）

`ms_peaks` 中每个关键 peak 必须能提供：

- `peak_id`
- `monoisotopic_mz`
- `intensity`
- `charge`
- `matched_ions`（完整高亮和标签需要）

`annotated_protein` 中必须能提供：

- `sequence_id`
- `proteoform_id`
- `sequence_name`
- `annotation`

### 8.4 当前可选但建议填写字段

- `p_value`
- `e_value`
- `fdr`
- `matched_fragment_number`
- `matched_peak_number`
- `spectrum_file_name`
- `precursor_mono_mass`
- `precursor_charge`
- `precursor_mz`
- `feature_inte`
- `proteoform_mass`

建议填写原因：

- `p_value`、`e_value`、`fdr` 用于质量评估、排序和筛选。
- `matched_fragment_number`、`matched_peak_number` 用于列表展示和结果质量判断。
- `spectrum_file_name` 有助于追溯来源文件。
- `precursor_mono_mass`、`precursor_charge`、`precursor_mz` 用于前体信息展示和 MS1 标记。
- `feature_inte` 用于 feature 强度展示。
- `proteoform_mass` 有助于详情展示和质量对照。

### 8.5 未来扩展

为了接收其它格式，建议未来增加：

- `default_ms1_id`：从 `ms1_ids` 中解析出的默认 apex id。
- `default_ms2_id`：从 `ms2_ids` 中解析出的默认 apex id。
- `all_ms1_ids`：JSONB 或数组形式，保存所有可切换 MS1 id。
- `all_ms2_ids`：JSONB 或数组形式，保存所有可切换 MS2 id。
- `extra_metadata`：JSONB，用于保存来源软件特有的 PrSM 级字段。

### 8.6 约束

- 同一 `cutoff_id` 下 `prsm_id` 唯一。
- `PrSM.annotated_protein.sequence_id` 应与 `prsms.sequence_id` 一致。
- `PrSM.annotated_protein.proteoform_id` 应能定位到对应 Proteoform。
- `PrSM.ms2_ids` 必须能定位至少一张 MS2 谱。

---

## 9. 数据库入库标准：Spectrum

### 9.1 当前存储策略

当前谱图大文件不进入 PostgreSQL。

数据库只保存：

- dataset 路径
- PrSM 中的 ms1/ms2 id
- PrSM 匹配峰信息

谱图文件仍在磁盘上。

### 9.2 当前数据库关联字段

当前没有独立 `spectra` 表。谱图通过以下现有字段间接关联：

- `datasets.source_path`：数据集根路径。
- `prsms.ms1_ids`：MS1 谱图 id。
- `prsms.ms2_ids`：MS2 谱图 id。
- `prsms.ms1_scans`：MS1 scan 文本。
- `prsms.ms2_scans`：MS2 scan 文本。
- `prsms.ms_header`：PrSM 原始谱头 JSONB。
- `prsms.ms_peaks`：PrSM 匹配峰 JSONB。

当前 TopPIC/TopFD 路径规则：

- MS1：`{datasets.source_path}/topfd/ms1_json/spectrum{id}.js`
- MS2：`{datasets.source_path}/topfd/ms2_json/spectrum{id}.js`

### 9.3 必须满足

不管谱图原始格式是什么，应用层最终要能得到统一 Spectrum 结构。

SpectrumV0 必须包含：

- `v`：版本，例如 `"0.1"`。
- `ms`：`1` 或 `2`。
- `sid`：谱图 id。
- `rt`：保留时间，单位秒。
- `peaks`：峰数组。

每个 peak 必须包含：

- `m`：m/z。
- `i`：intensity。

### 9.4 完整 Top-down PrSM 能力要求

如果数据集声明支持完整 `topdown_prsm`，MS2 Spectrum 必须包含：

- `envelopes`

每个 envelope 必须包含：

- `id`
- `mm`：monoisotopic mass
- `z`：charge
- `ep`：同位素子峰数组

并且：

- `envelopes[].id` 必须能与 `PrSM.ms_peaks.peak[].peak_id` 对齐。

### 9.5 多 scan 策略

已确认规则：

- 默认 apex。
- 支持手动切换 all。

因此准入模块应解析并输出：

- `default_sid`
- `all_sids[]`

当前 TopPIC/TopFD 中：

- MS1 来源：`ms.ms_header.ms1_ids`
- MS2 来源：`ms.ms_header.ids`

### 9.6 未来扩展

为了支持更多格式和更稳定的谱图管理，建议未来增加独立的 `spectra` 或 `spectrum_index` 表。

建议字段：

- `id`
- `dataset_id`
- `ms_level`
- `sid`
- `scan`
- `retention_time`
- `file_path`
- `standard_file_path`
- `peak_count`
- `has_envelopes`
- `extra_metadata`：JSONB

这张表不是第一阶段必须；当前可以继续用 `datasets.source_path + prsms.ms1_ids/ms2_ids` 的方式定位谱图。

---

## 10. Capability：决定是否完整展示

不是所有数据都必须支持完整 PrSM 页面。

因此每个 dataset 应有能力声明。

建议字段：

```json
{
  "has_ms1": true,
  "has_ms2": true,
  "has_spectra_peaks": true,
  "has_envelopes": true,
  "has_multi_scan": true,
  "has_proteins": true,
  "has_proteoforms": true,
  "has_prsms": true,
  "has_matched_peaks": true,
  "has_annotated_sequence": true
}
```

### 10.1 完整当前页面需要

当前完整 PrSM 页面需要：

- `has_ms1`
- `has_ms2`
- `has_spectra_peaks`
- `has_envelopes`
- `has_prsms`
- `has_matched_peaks`
- `has_annotated_sequence`

### 10.2 如果缺失能力

允许降级：

- 没有 `has_envelopes`：可以画基础 MS2，但不能保证匹配峰局部包络视图。
- 没有 `has_prsms`：只能作为谱图数据集，不进入 PrSM 页面。
- 没有 `has_annotated_sequence`：不能展示完整序列注释。

---

## 11. 建议新增表：import_runs

### 11.1 为什么需要

多格式导入后，必须能追溯：

- 哪次导入？
- 用哪个 Adapter？
- 成功还是失败？
- 错误是什么？

### 11.2 建议字段

- `id`
- `dataset_id`
- `adapter_name`
- `adapter_version`
- `format_version`
- `started_at`
- `finished_at`
- `status`
- `error_count`
- `warning_count`
- `log_path`
- `summary`：JSONB

---

## 12. 建议新增表：source_files

### 12.1 为什么需要

未来原始文件格式多样，必须登记：

- 原文件在哪里？
- 文件类型是什么？
- 文件有没有被移动或损坏？

### 12.2 建议字段

- `id`
- `dataset_id`
- `path`
- `relative_path`
- `role`
- `file_type`
- `checksum`
- `size_bytes`
- `extra_metadata`：JSONB

### 12.3 role 示例

- `raw_spectrum`
- `standard_spectrum`
- `protein_index`
- `prsm_detail`
- `metadata`

---

## 13. Adapter 标准

### 13.1 Adapter 是什么

Adapter 是把外部格式变成数据库入库标准的转换器。

每种外部格式至少对应一个 Adapter，例如：

- `toppic_topfd`
- `vendor_x`
- `custom_csv`

### 13.2 Adapter 输入

- `root`
- `slug`
- `name`
- `description`
- `format`

### 13.3 Adapter 输出

Adapter 必须输出可校验的标准 payload：

- `DatasetPayload`
- `CutoffPayload[]`
- `ProteinPayload[]`
- `ProteoformPayload[]`
- `PrsmPayload[]`
- `SpectrumIndexPayload[]`
- `SourceFilePayload[]`
- `CapabilityPayload`

### 13.4 Adapter 不能做的事

- 不能绕过校验直接写库。
- 不能把格式差异暴露给前端。
- 不能在缺少关键字段时假装完整支持。

---

## 14. 准入校验规则

### 14.1 第一层：原始包校验

检查：

- 路径是否存在。
- 必需目录/文件是否存在。
- 来源格式是否能识别。
- 文件是否可读。

### 14.2 第二层：标准 payload 校验

检查：

- Dataset 字段完整。
- Cutoff / ResultSet 可构造。
- Protein / Proteoform / PrSM 关系可解析。
- Spectrum 可定位。
- ms id 可解析。
- capability 与实际内容一致。

### 14.3 第三层：数据库约束校验

检查：

- 唯一键不冲突。
- 外键关系正确。
- JSONB 关键路径存在。
- 完整 Profile 所需字段齐全。

### 14.4 失败策略

- 结构性错误：中止导入。
- 单条错误：可跳过，但必须记录。
- 能力缺失：允许降级入库，但 capability 必须准确。

---

## 15. 导入命令建议

未来 CLI 建议支持：

```powershell
uv run python -m app.ingest.cli ingest `
  --format toppic_topfd `
  --root "E:\path\to\dataset" `
  --slug "dataset_slug" `
  --name "Dataset Name"
```

可选：

- `--description`
- `--keep-existing`
- `--validate-only`

---

## 16. 前后端是否需要修改

### 16.1 不需要大改的情况

如果新数据经过 Adapter 后，能完整满足当前数据库入库标准：

- 有 protein
- 有 proteoform
- 有 PrSM
- 有 MS1/MS2
- 有 envelopes
- 有 matched peaks
- 有 annotated protein

则前端基本不需要大改。

后端只需要支持新的导入 Adapter。

### 16.2 需要改前端的情况

如果某类数据缺少当前页面能力，例如：

- 没有 PrSM
- 没有 proteoform
- 没有 envelopes
- 只有谱图没有鉴定结果

则前端需要做降级展示。

不是为了适配原始格式，而是为了根据 capability 隐藏不可用功能。

---

## 17. 当前系统迁移步骤

### 阶段 A：先固定数据库入库标准

- 以本文为入库标准。
- 不立刻推翻现有表。
- 当前 TopPIC/TopFD 数据视为第一种标准数据。

### 阶段 B：补最小字段和管理表

建议优先增加：

- `datasets.source_software`
- `datasets.profile`
- `datasets.capabilities`
- `datasets.raw_data_path`
- `datasets.standard_data_path`
- `import_runs`
- `source_files`

### 阶段 C：做数据准入模块

- `detect_format`
- `validate_raw_package`
- `adapter.normalize`
- `validate_database_payload`
- `import_to_database`

### 阶段 D：改造现有 importer

把当前 TopPIC/TopFD 导入逻辑包装成：

```text
toppic_topfd adapter
```

### 阶段 E：接入第二种格式验证设计

第二种真实格式出现后：

- 先写 Adapter。
- 不直接改前端。
- 看它能满足哪些 capability。
- 若现有数据库标准不足，再补字段或新增 Profile。

---

## 18. 验收标准

### 18.1 完整 Top-down PrSM 数据集

导入后必须满足：

1. 数据集列表可见。
2. Protein 列表可用。
3. Proteoform 列表可用。
4. PrSM 列表可用。
5. PrSM 详情可展开序列。
6. MS1 可出图。
7. MS2 可出图。
8. MS2 envelopes 可与 matched peak 联动。
9. 默认 apex 可用。
10. all scan 可手动切换。

### 18.2 谱图-only 数据集

如果只声明 `spectrum_only`：

1. 数据集可见。
2. 谱图可查。
3. 谱图可画。
4. 不展示 PrSM 专属页面。

---

## 19. 当前真实数据集对应关系

当前样例数据集：

```text
E:\TDEase\shuju\histone_outputdata\MZ20160222DS_histone48_html
```

它应归类为：

```json
{
  "source_software": "toppic_topfd",
  "profile": "topdown_prsm",
  "capabilities": {
    "has_ms1": true,
    "has_ms2": true,
    "has_spectra_peaks": true,
    "has_envelopes": true,
    "has_multi_scan": true,
    "has_proteins": true,
    "has_proteoforms": true,
    "has_prsms": true,
    "has_matched_peaks": true,
    "has_annotated_sequence": true
  }
}
```

---

## 20. 变更记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-04-28 | 0.3.0 | 将文档重写为“数据库入库标准 + 数据准入模块”设计，明确数据库为标准，Adapter 负责让外部数据符合标准。 |

# 数据层统一契约（Dataset IR）v0.2

**状态**：草案  
**版本**：`0.2.0`  
**最后更新**：2026-04-28  
**适用项目**：proteo-viewer / future multi-format mass spectrometry viewer

---

## 1. 目标

本文件定义项目的数据层统一契约，用来解决一个核心问题：

> 未来会接入多种未知格式的质谱数据，但前端和后端不应该直接理解所有原始格式。所有输入都应先经过 Adapter 转换为系统内部统一结构，再由应用层展示、查询和画谱。

因此，本规范同时覆盖：

- 通用质谱数据层
- Top-down PrSM 业务 Profile
- 标准谱图结构
- 多格式 Adapter 机制
- 导入校验与降级规则
- 当前系统到统一契约的迁移路线

---

## 2. 总体架构

系统按两层理解：

```text
外部原始数据
  ├─ TopPIC / TopFD
  ├─ 未来其它软件
  ├─ CSV / JSON / XML / mzML
  └─ 自定义实验数据

        ↓ Adapter 解析与映射

数据层统一契约（本文）
  ├─ 通用层：Dataset / SourceFile / ImportRun / Spectrum / ResultSet
  └─ Profile 层：Top-down PrSM / 未来其它业务模型

        ↓ API

前端 + 后端应用层
  ├─ 数据集列表
  ├─ Protein / Proteoform / PrSM 浏览
  ├─ MS1 / MS2 谱图
  └─ 匹配峰与同位素包络可视化
```

关键原则：

- 输入格式可以不同。
- 内部契约必须稳定。
- 前端后端只依赖内部契约。
- 新格式通过新增 Adapter 接入。
- 不能强行要求所有未来数据都天然满足当前 TopPIC 结构。

---

## 3. 分层模型

### 3.1 通用层

通用层是所有质谱数据都应尽量落到的基础模型。

它不假设一定有 protein、proteoform 或 PrSM，只要求系统能回答：

- 这批数据是谁导入的？
- 原始文件在哪里？
- 用什么软件或 Adapter 解析？
- 有哪些谱图？
- 有哪些结果集？
- 当前数据具备哪些展示能力？

通用层实体：

- `Dataset`
- `ImportRun`
- `SourceFile`
- `ResultSet`
- `Spectrum`
- `Feature`（预留）
- `Identification`（预留）

### 3.2 Profile 层

Profile 是具体业务模型。

当前项目已有且优先支持的是：

- `topdown_prsm`

它包含：

- `Protein`
- `Proteoform`
- `PrSM`
- `AnnotatedProtein`
- `MatchedPeaks`
- `Envelopes`

未来如果接入完全不同的数据类型，不应硬塞进 PrSM，而应新增 Profile，例如：

- `bottomup_psm`
- `metabolomics_feature`
- `spectrum_only`

---

## 4. Dataset

### 4.1 语义

`Dataset` 表示一批可浏览的数据，是前端 URL、数据隔离和导入管理的根对象。

### 4.2 必需字段

- `slug`：唯一标识，用于 URL 和导入定位。
- `name`：展示名。
- `description`：可空说明。
- `source_path`：当前系统使用的根路径。对 TopPIC/TopFD 数据，它指向包含 `topfd/` 与 `toppic_*_cutoff/` 的目录。
- `source_software`：来源软件或格式，如 `toppic_topfd`、`vendor_x`。
- `profile`：数据业务类型，如 `topdown_prsm`、`spectrum_only`。

### 4.3 建议增强字段

- `raw_data_path`：原始文件归档路径。
- `standard_data_path`：若未来预生成标准谱图 JSON，指向标准文件根目录。
- `ingest_format`：Adapter 格式名。
- `ingest_version`：Adapter 或导入规范版本。
- `extra_metadata`：JSONB，用于来源软件特有信息。

---

## 5. ImportRun

### 5.1 语义

`ImportRun` 表示一次导入行为，用来审计和追溯。

未来多格式接入后，必须知道每一批数据：

- 用哪个 Adapter 导入？
- 什么时候导入？
- 是否成功？
- 跳过了多少条？
- 哪些文件失败？

### 5.2 建议字段

- `id`
- `dataset_id`
- `adapter_name`
- `adapter_version`
- `format_version`
- `started_at`
- `finished_at`
- `status`：`success` / `partial_success` / `failed`
- `error_count`
- `warning_count`
- `log_path`
- `summary`：JSONB

---

## 6. SourceFile

### 6.1 语义

`SourceFile` 登记原始文件或标准化后的文件。

它解决的问题是：

- 文件从哪里来？
- 文件是否被移动或损坏？
- 某条谱图或 PrSM 来自哪个文件？

### 6.2 建议字段

- `id`
- `dataset_id`
- `path`
- `relative_path`
- `role`：如 `raw_spectrum`、`standard_spectrum`、`protein_index`、`prsm_detail`
- `file_type`：如 `js`、`json`、`mzml`、`csv`
- `checksum`
- `size_bytes`
- `created_at`
- `extra_metadata`：JSONB

---

## 7. ResultSet

### 7.1 为什么不用只说 Cutoff

当前数据库表叫 `cutoffs`，但 `cutoff` 是 TopPIC 语义。未来其它软件可能叫：

- result set
- analysis
- search run
- confidence group
- processing version

因此在 IR 层统一叫 `ResultSet`。当前实现中可继续映射到 `cutoffs` 表。

### 7.2 必需字段

- `dataset_id`
- `kind`：当前可用 `prsm`、`proteoform`；未来可扩展。
- `label`
- `data_path`
- `profile`：如 `topdown_prsm`

### 7.3 约束

- 同一 `dataset_id` 下 `kind` 应唯一。
- 如果未来同一 `kind` 允许多个版本，应新增 `result_set_id` 或 `version` 区分，不应复用同一个 `kind`。

---

## 8. Capability

### 8.1 语义

Capability 描述一个数据集或 Adapter 能支持哪些功能。

这能避免未来出现“某格式没有 envelopes，却被强行打开完整 PrSM 页面”的问题。

### 8.2 建议能力项

- `has_ms1`
- `has_ms2`
- `has_spectra_peaks`
- `has_envelopes`
- `has_multi_scan`
- `has_proteins`
- `has_proteoforms`
- `has_prsms`
- `has_matched_peaks`
- `has_annotated_sequence`

### 8.3 当前完整页面所需能力

当前 PrSM 详情页完整功能需要：

- `has_ms1 = true`
- `has_ms2 = true`
- `has_spectra_peaks = true`
- `has_envelopes = true`
- `has_prsms = true`
- `has_matched_peaks = true`
- `has_annotated_sequence = true`

如果缺少某能力，前端应降级，而不是崩溃。

---

## 9. Top-down PrSM Profile

当前项目的主要业务 Profile 是 `topdown_prsm`。

该 Profile 继承通用层，并额外要求以下实体。

---

## 10. Protein

### 10.1 必需字段

- `result_set_id`（当前实现对应 `cutoff_id`）
- `sequence_id`
- `sequence_name`
- `compatible_proteoform_number`
- `prsm_number`

### 10.2 建议字段

- `sequence_description`
- `best_prsm_id`
- `best_prsm_e_value`
- `sequence`
- `accession`
- `extra_metadata`：JSONB

### 10.3 约束

- 同一 `result_set_id` 下 `sequence_id` 唯一。

---

## 11. Proteoform

### 11.1 必需字段

- `result_set_id`
- `protein_id`
- `proteoform_id`：业务 id
- `sequence_id`
- `sequence_name`
- `prsm_number`

### 11.2 建议字段

- `proteoform_mass`
- `best_prsm_id`
- `best_prsm_e_value`
- `n_acetylation`
- `unexpected_shift_number`
- `modifications`：JSONB
- `extra_metadata`：JSONB

### 11.3 约束

- 同一 `(result_set_id, protein_id, proteoform_id)` 唯一。

---

## 12. PrSM

### 12.1 必需字段

- `result_set_id`
- `proteoform_id`
- `prsm_id`：业务 id
- `sequence_id`
- `ms1_ids`
- `ms2_ids`
- `ms_header`：JSONB
- `ms_peaks`：JSONB
- `annotated_protein`：JSONB

### 12.2 建议字段

- `p_value`
- `e_value`
- `fdr`
- `matched_fragment_number`
- `matched_peak_number`
- `spectrum_file_name`
- `ms1_scans`
- `ms2_scans`
- `precursor_mono_mass`
- `precursor_charge`
- `precursor_mz`
- `feature_inte`
- `proteoform_mass`
- `extra_metadata`：JSONB

### 12.3 约束

- 同一 `result_set_id` 下 `prsm_id` 唯一。
- `annotated_protein.sequence_id` 与 PrSM `sequence_id` 应一致。
- `annotated_protein.proteoform_id` 应能解析到对应 Proteoform。

---

## 13. 标准谱图结构

本节整合原 `spectrum-v0.md`。

### 13.1 目标

无论原始谱图来自 TopFD `spectrum*.js` 还是其它软件，进入应用层前都应转换为统一的 `SpectrumV0`。

前端谱图组件只依赖此结构。

### 13.2 顶层对象

必需字段：

- `v`：规范版本，当前为 `"0.1"`。
- `ms`：`1` 或 `2`。
- `sid`：谱图标识，在同一 dataset + ms level 内唯一。
- `peaks`：峰数组。

强烈建议字段：

- `rt`：保留时间，单位统一为**秒**。
- `meta`：元数据。
- `precursor`：MS2 建议提供。
- `window`：视图窗口。
- `envelopes`：对 `topdown_prsm` 完整功能为必需。

### 13.3 `peaks`

每个峰对象：

- `m`：m/z，必需。
- `i`：intensity，必需。
- `e`：envelope / feature id，可选。
- `z`：charge，可选。
- `lbl`：显示标签，可选。

### 13.4 `precursor`

MS2 建议提供：

- `mz`
- `z`
- `mass`（可选）

MS1 通常省略。

### 13.5 `window`

对应 TopFD 的窗口字段：

- `tg`：target m/z
- `lo`：min m/z
- `hi`：max m/z

### 13.6 `envelopes`

在 `topdown_prsm` 完整页面中，`envelopes` 为必需。

每个 envelope：

- `id`：必须可与 PrSM `ms_peaks.peak[].peak_id` 对齐。
- `mm`：monoisotopic mass。
- `z`：charge。
- `ep`：同位素子峰数组，每项为 `{ "m": number, "i": number }`。

说明：

- 对 `spectrum_only` 或其它 Profile，`envelopes` 可不是必需能力。
- 若缺少 `envelopes`，只能支持基础谱图显示，不能保证当前匹配峰局部视图完整。

### 13.7 MS1 / MS2 差异

| 项目 | MS1 | MS2 |
|------|-----|-----|
| `ms` | `1` | `2` |
| `precursor` | 通常省略 | 建议提供 |
| `envelopes` | 按能力声明 | `topdown_prsm` 完整功能必需 |
| 路径（当前 TopFD） | `topfd/ms1_json/spectrum{sid}.js` | `topfd/ms2_json/spectrum{sid}.js` |

---

## 14. TopFD 到 SpectrumV0 映射

当前真实数据集示例路径：

`E:\TDEase\shuju\histone_outputdata\MZ20160222DS_histone48_html`

当前 TopFD 字段映射：

| TopFD 源字段 | SpectrumV0 |
|--------------|------------|
| `id` | `sid` 参考值，建议 `String(id)` |
| `scan` | `meta.scan` |
| `retention_time` | `rt`，单位秒 |
| `target_mz` | `window.tg` |
| `min_mz` | `window.lo` |
| `max_mz` | `window.hi` |
| `peaks[].mz` | `peaks[].m` |
| `peaks[].intensity` | `peaks[].i` |
| `envelopes[].id` | `envelopes[].id` |
| `envelopes[].mono_mass` | `envelopes[].mm` |
| `envelopes[].charge` | `envelopes[].z` |
| `envelopes[].env_peaks[].mz/intensity` | `envelopes[].ep[].m/i` |
| `n_ion_type` | `meta.n_ion` |
| `c_ion_type` | `meta.c_ion` |

---

## 15. 多 scan 策略

已确认规则：

- 默认使用 apex，即第一个可用 id。
- 支持手动切换 all。

因此 Adapter 或后端 API 应输出：

- `default_sid`
- `all_sids[]`

当前 TopPIC/TopFD PrSM 来源：

- MS1：`ms.ms_header.ms1_ids`
- MS2：`ms.ms_header.ids`

解析要求：

- 支持逗号、分号、空格分隔。
- 去重。
- 保留原始顺序。

---

## 16. Adapter 接口

### 16.1 目的

Adapter 是所有外部格式进入系统的唯一入口。

新格式不应直接改前端，也不应让前端读取原始文件。

### 16.2 Adapter 输出

每个 Adapter 应输出统一中间对象：

- `DatasetPayload`
- `SourceFilePayload[]`
- `ImportRunPayload`
- `ResultSetPayload[]`
- `SpectrumPayload[]`
- `ProteinPayload[]`（若 profile 支持）
- `ProteoformPayload[]`（若 profile 支持）
- `PrsmPayload[]`（若 profile 支持）

### 16.3 Adapter Capability

Adapter 必须声明能力：

- `profile`
- `has_ms1`
- `has_ms2`
- `has_spectra_peaks`
- `has_envelopes`
- `has_multi_scan`
- `has_proteins`
- `has_proteoforms`
- `has_prsms`
- `has_matched_peaks`
- `has_annotated_sequence`

### 16.4 Adapter 命令建议

建议扩展导入命令：

```powershell
uv run python -m app.ingest.cli ingest `
  --format toppic_topfd `
  --root "E:\path\to\dataset" `
  --slug "dataset_slug" `
  --name "Dataset Name"
```

可选参数：

- `--description`
- `--keep-existing`
- `--validate-only`

---

## 17. 导入校验规则

### 17.1 通用校验

- `slug` 唯一。
- `profile` 可识别。
- `source_path` 存在。
- Adapter capability 与输出内容一致。
- 所有登记的 SourceFile 可访问。

### 17.2 Spectrum 校验

- `sid` 非空。
- `ms` 为 `1` 或 `2`。
- `rt` 若存在，单位必须为秒。
- `peaks` 存在。
- 每个 peak 必须有有限数值 `m` 与 `i`。
- 若 capability 声明 `has_envelopes=true`，则 `envelopes` 必须存在且字段完整。

### 17.3 Top-down PrSM 校验

- Protein 可由 `sequence_id` 唯一定位。
- Proteoform 可由 `(sequence_id, proteoform_id)` 定位。
- PrSM 可关联到 Proteoform。
- PrSM 的 `ms1_ids` / `ms2_ids` 至少能解析出默认 apex。
- `ms_peaks.peak[].peak_id` 能与 MS2 `envelopes.id` 对齐；若不能，记录 warning 或失败，取决于是否要求完整 Profile。

### 17.4 失败策略

- 单条数据问题：跳过该条，记录错误。
- 核心结构问题：中止导入并回滚。
- 缺少完整页面能力：允许导入，但必须降低 capability，前端降级显示。

---

## 18. 前后端消费边界

### 18.1 后端

- 后端对外只暴露统一语义。
- 原始格式差异只存在于 Adapter 或解析层。
- API 应根据 capability 返回可用功能。
- 对 `topdown_prsm`，应继续支持现有列表、详情、谱图、匹配峰视图。

### 18.2 前端

- 前端不直接理解 TopFD / TopPIC 原始文件。
- 谱图组件只吃 SpectrumV0。
- 当前完整 PrSM 页面只对满足 `topdown_prsm_full` 能力的数据集开放。
- 如果 capability 不足，前端应降级：
  - 只显示谱图
  - 隐藏匹配峰局部视图
  - 隐藏序列注释
  - 提示数据集缺少某能力

---

## 19. 当前系统迁移路线

### 阶段 A：文档与契约固定

- 以本文作为唯一总规范。
- 当前 TopPIC/TopFD 数据按 `topdown_prsm` Profile 解释。
- 保留现有表结构，不立刻大迁移。

### 阶段 B：最小代码演进

- 新增 `source_software` / `profile` 等最小审计字段。
- 新增 SpectrumV0 转换函数。
- 新增 SpectrumV0 API。
- 保留旧 API，避免破坏当前前端。

### 阶段 C：Adapter 化

- 抽象 Adapter 接口。
- 现有 importer 改名或包装为 `toppic_topfd` Adapter。
- 增加 `--format`。
- 增加 `--validate-only`。

### 阶段 D：接入第二种真实格式

- 用第二种格式验证通用层是否足够。
- 不足时新增 Profile 或扩展 JSONB。
- 不为了未知格式提前大改数据库。

---

## 20. 验收标准

对 `topdown_prsm` 完整 Profile，导入后必须满足：

1. 数据集列表可见。
2. ResultSet / cutoff 计数正确。
3. Protein 列表和详情可用。
4. Proteoform 列表和详情可用。
5. PrSM 列表和详情可用。
6. MS1 可出图。
7. MS2 可出图。
8. MS2 `envelopes` 与 PrSM `peak_id` 可联动。
9. 多 scan 默认 apex。
10. 多 scan 可手动切换 all。

对 `spectrum_only` Profile，最低验收标准：

1. 数据集可见。
2. 谱图可查询。
3. MS1/MS2 或单类谱图可出图。
4. 前端不展示不具备的 PrSM 功能。

---

## 21. 示例：SpectrumV0

### 21.1 MS2

```json
{
  "v": "0.1",
  "ms": 2,
  "sid": "1234",
  "rt": 1078.1125,
  "meta": {
    "slug": "mz20160222ds_histone48",
    "src": "toppic_topfd",
    "file": "topfd/ms2_json/spectrum1234.js",
    "scan": 314
  },
  "precursor": {
    "mz": 817.7477,
    "z": 17,
    "mass": 13884.5879
  },
  "window": {
    "tg": 773.806,
    "lo": 773.506,
    "hi": 774.106
  },
  "peaks": [
    { "m": 117.9304, "i": 19.394 },
    { "m": 149.0602, "i": 352.9 }
  ],
  "envelopes": [
    {
      "id": 3,
      "mm": 13188.1944,
      "z": 16,
      "ep": [
        { "m": 824.5, "i": 1000 },
        { "m": 825.0, "i": 2000 }
      ]
    }
  ]
}
```

### 21.2 MS1

```json
{
  "v": "0.1",
  "ms": 1,
  "sid": "150",
  "rt": 604.5021,
  "meta": {
    "slug": "mz20160222ds_histone48",
    "src": "toppic_topfd",
    "file": "topfd/ms1_json/spectrum150.js",
    "scan": 303
  },
  "peaks": [
    { "m": 600.0455, "i": 699.96 },
    { "m": 600.7601, "i": 8128.9 }
  ]
}
```

---

## 22. 变更记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-04-28 | 0.2.0 | 整合原 `dataset-ir-v0.md` 与 `spectrum-v0.md`，升级为通用层 + Profile 层 + Spectrum + Adapter 的单一总规范。 |

# 数据层统一契约（Dataset IR）v0.1

**状态**：草案（全量）  
**版本**：`0.1.0`  
**最后更新**：2026-04-28  
**目标**：定义“任意来源数据 -> 系统可浏览数据”的完整标准，不只谱图。

---

## 1. 这份文档管什么

本规范覆盖你系统里的**全部核心内容**：

1. 数据集元信息（dataset）
2. cutoff 维度（prsm/proteoform）
3. 蛋白（protein）
4. 异构体（proteoform）
5. PrSM（含详情 JSON）
6. 谱图（MS1/MS2）
7. 多格式导入适配器与校验规则

> `docs/spectrum-v0.md` 是本规范的“谱图子规范”。

---

## 2. 总体原则

- 输入格式可变（TopPIC/TopFD、未来其它软件都可以）
- 内部语义固定（前后端只认这一套）
- 关系字段强约束，扩展字段 JSONB 兜底
- 可追溯（来源软件、原始路径、导入版本）

---

## 3. 统一实体模型（必须）

### 3.1 Dataset（数据集）

最小必需字段：

- `slug`（唯一，URL 用）
- `name`
- `source_path`（当前用于查找 topfd 谱文件）
- `source_software`（建议：`toppic_topfd`、`vendor_x`）
- `description`（可空）

说明：

- 一条 dataset 对应一批可浏览数据。
- 后续若引入 `raw_data_path` / `standard_data_path`，可作为增强字段。

### 3.2 Cutoff（阈值/视图）

最小必需字段：

- `dataset_id`
- `kind`（当前为 `prsm` / `proteoform`）
- `label`
- `data_path`

约束：

- 同一 `dataset_id` 下 `kind` 唯一。

### 3.3 Protein（蛋白）

最小必需字段：

- `cutoff_id`
- `sequence_id`
- `sequence_name`
- `compatible_proteoform_number`
- `prsm_number`

建议字段：

- `sequence_description`
- `best_prsm_id`
- `best_prsm_e_value`
- `extra_metadata`（JSONB，可选扩展）

约束：

- 同一 `cutoff_id` 下 `sequence_id` 唯一。

### 3.4 Proteoform（异构体）

最小必需字段：

- `cutoff_id`
- `protein_id`
- `proteoform_id`（业务 id）
- `sequence_id`
- `sequence_name`
- `prsm_number`

建议字段：

- `proteoform_mass`
- `best_prsm_id`
- `best_prsm_e_value`
- `n_acetylation`
- `unexpected_shift_number`

约束：

- 同一 `(cutoff_id, protein_id, proteoform_id)` 唯一。

### 3.5 PrSM（匹配结果）

最小必需字段：

- `cutoff_id`
- `proteoform_id`（数据库主键关联）
- `prsm_id`（业务 id）
- `sequence_id`
- `ms1_ids`（用于请求 MS1）
- `ms2_ids`（用于请求 MS2）
- `ms_peaks`（JSONB，匹配峰细节）
- `annotated_protein`（JSONB，序列注释细节）
- `ms_header`（JSONB，谱头信息）

建议字段：

- `e_value`、`p_value`、`fdr`
- `matched_fragment_number`、`matched_peak_number`
- `precursor_mono_mass`、`precursor_charge`、`precursor_mz`
- `feature_inte`
- `spectrum_file_name`

约束：

- 同一 `cutoff_id` 下 `prsm_id` 唯一。

---

## 4. 谱图模型（必须）

谱图部分由 `docs/spectrum-v0.md` 定义，关键决策如下（继承执行）：

- `envelopes`：必须
- `rt`：秒
- 多 scan：默认 apex + 支持手动切换 all

与 PrSM 的桥接要求：

- `PrSM.ms1_ids / ms2_ids` 可定位谱图 sid
- `PrSM.ms_peaks.peak_id` 可与 `MS2.envelopes.id` 对齐

---

## 5. 多格式导入契约（必须）

任何新格式必须实现一个 Adapter，输出统一中间对象：

1. `DatasetPayload`
2. `CutoffPayload[]`
3. `ProteinPayload[]`
4. `ProteoformPayload[]`
5. `PrsmPayload[]`
6. `SpectrumPayload(ms1/ms2)`（符合 spectrum-v0）

然后统一入库流程写入现有表结构。

---

## 6. 导入校验规则（必须）

入库前必须过校验：

1. 主键/唯一键可构造（slug、kind、sequence_id、prsm_id）
2. PrSM -> Proteoform 关联可解析
3. PrSM 的 `ms1_ids/ms2_ids` 至少可取默认 apex
4. MS2 谱图必须有 `envelopes`
5. `rt` 单位统一秒（若来源不是秒需转换）

失败策略：

- 单条可跳过：记录错误日志 + 错误计数
- 结构性错误：中止导入并回滚

---

## 7. 前后端消费边界

### 后端

- 对外 API 只暴露统一语义
- 旧格式差异只在 Adapter 内部消化

### 前端

- 列表/详情依赖统一字段，不感知来源软件
- 谱图组件只吃 `spectrum-v0` 结构
- 多 scan 使用 `default_sid` + `all_sids`

---

## 8. 迁移策略（从当前系统到全量 IR）

阶段 A（先做）

- 维持现有表结构
- 补 `source_software`（若尚未落表）
- 新增/实现 spectrum-v0 输出

阶段 B（随后）

- 抽象 adapter 接口（`--format` 选择）
- 第一版支持：`toppic_topfd`

阶段 C（扩展）

- 接入第二种格式
- 根据真实差异决定是否加列或扩展 JSONB

---

## 9. 命令行建议（导入）

建议扩展 ingest 参数：

- `--format`：`toppic_topfd` / `vendor_x` / `custom_y`
- `--root`
- `--slug`
- `--name`
- `--description`

可选：

- `--keep-existing`
- `--validate-only`（只校验不落库）

---

## 10. 验收标准（Definition of Done）

导入任意支持格式后，以下都要成立：

1. 数据集列表可见并计数正确
2. Protein / Proteoform / PrSM 列表分页可用
3. PrSM 详情可展开序列与匹配峰
4. MS1、MS2 可出图
5. MS2 匹配峰局部视图正常（依赖 envelopes）
6. 多 scan 默认 apex，且可手动切换 all

---

## 11. 与子文档关系

- 本文：全量“数据层统一契约”
- `docs/spectrum-v0.md`：谱图结构与策略的子规范

后续若新增：

- `docs/adapter-interface-v0.md`（适配器接口）
- `docs/ingest-validation-v0.md`（校验细则）

可与本文互相链接。

