# `front/src/features/prsm/parse.ts` 逐行解释

> 来源文件：`front/src/features/prsm/parse.ts`
>
> 该文件把后端返回的“TopPIC 风格 JSON blobs”（annotated_protein、ms_peaks、谱图对象）解析/归一化为前端可直接消费的强类型结构，核心目标是：
> - 把字符串数字转成 number
> - 把“单元素数组压扁成对象”的字段恢复成数组
> - 建立 matched-peak 与 envelope 的对齐关系（peak_id ↔ envelopes.id）

---

## L1-L10（模块定位）

- 注释说明该文件负责 normalization：
  - `.js` 文件常把标量包成字符串
  - 单元素数组经常变成 object
- 因此前端需要统一的 `asList/num` 等工具。

## L11

- 引入 `PrsmDetailOut`：用于 splitDataForDetail 的输入类型

## L15-L18：`asList`

- 将 `T | T[] | null | undefined` 统一成 `T[]`：
  - null/undefined → []
  - array → 原样
  - 单对象 → [单对象]
- 这是适配 TopPIC “数组长度为 1 被压扁”的关键函数。

## L20-L24：`num`

- 将 unknown 转成 number|null：
  - null/undefined → null
  - number → number
  - string 等 → `Number(v)`，非有限数返回 null

## L26-L129：Sequence / annotation 解析（AnnotatedProtein）

### 类型定义（L28-L75）

- IonType：允许 B/C/Y/Z_DOT 等，或其它字符串
- Residue：位置（0-based）+ 氨基酸字符
- MatchedPeakLite：sequence cleavage 上的 matched peak 轻量信息（specId/peakId/ionPosition 等）
- Cleavage：切割位点 + 是否存在 N/C 离子 + matchedPeaks
- MassShift：修饰/质量偏移区间（left/right/shift/anno/type）
- AnnotatedProtein：整合 protein/proteoform 注释信息（长度、序列、cleavage、mass shifts）

### `parseAnnotatedProtein(raw)`（L77-L129）

- 若 raw 不存在 → null
- `ann = raw.annotation ?? {}`：annotation 子对象
- residues：
  - `asList(ann.residue)` → Residue[]
- cleavages：
  - `asList(ann.cleavage)` → Cleavage[]
  - `matched_peaks.matched_peak` 也要 asList
  - `exist_n_ion/exist_c_ion` 在 TopPIC 输出中是 `"1"/"0"`，前端转成 boolean
- massShifts：
  - `asList(ann.mass_shift)` → MassShift[]
  - `shift` 用 `num`
- 返回 AnnotatedProtein：
  - 顶层很多字段是 number|string 混杂，统一用 `num/Number/String`
  - `proteinLength` 等字段提供 fallback（例如缺失时用 residues.length）

## L131-L187：MS peak table 解析（MsPeakRow）

### 类型定义（L133-L153）

- MatchedIon：离子类型/位置/误差/ppm 等
- MsPeakRow：去卷积峰（spec_id/peak_id/mono mass/mz/intensity/charge + matchedIons）

### `matchedPeakDetailKey`（L155-L158）

- 生成稳定 key：peak_id + ion_type + ion_display_position + ion_sort_name
- 用于表格行选择与 detail panel 的 React key

### `parseMsPeaks(raw)`（L160-L187）

- raw 不存在 → []
- `peaks = asList(raw.peak)`
- 对每个 peak：
  - `matched_ions.matched_ion` 也要 asList
  - 数字字段统一 `Number/num`
- 返回 MsPeakRow[]

## L189-L298：MS1/MS2 谱图解析（RawSpectrum）

### 类型定义（L191-L230）

- RawPeak：mz/intensity
- RawEnvelopePeak：同位素子峰（mz/intensity）
- RawEnvelope：
  - `id`：必须与 `ms_peaks.peak[].peak_id` 对齐（用于 matched-peak detail）
  - `monoMass/charge/envPeaks`
- RawSpectrum：
  - 基本信息：id/scan/RT/窗口/离子类型
  - `peaks[]`：原始峰
  - `envelopes[]`：TopFD 的去卷积包络（mzML 模式可能没有这一块）

### `parseRawSpectrum(raw)`（L232-L292）

- raw 不存在 → null。
- **mzML-memory API 分支（L234-L259）**：若顶层同时存在 **`mz`/`intensity` 平行数组**（动态谱图接口返回），则按 `Math.min(len)` 逐对 zip 成 `RawPeak[]`，过滤非有限数；`id/scan` 从 `raw.id` 或 `raw.scan` 取；`retentionTime` 兼容 `rt_seconds` 与 `retention_time`；**`envelopes` 固定为 `[]`**（mzML 路径通常无 TopFD 包络）。
- **TopFD / 旧 JSON 分支（L261-L291）**：`asList(raw.peaks)` 映射为 peaks；`asList(raw.envelopes)` 解析包络与 `env_peaks`；各标量字段用 `num` 做 null 保护。

### `findMatchedEnvelope(spectrum, peak, tolerance=0.5)`（L274-L298）

- 先尝试直接对齐：`envelope.id === peak.peakId`
- 若没命中：
  - 用 monoMass + charge 做最近邻（容差默认 0.5 Da）
  - 这是对“导出重编号/不一致”情况下的容错
- 返回最合适 envelope 或 null

## L300-L315：顶层 helper

- ShiftRegion：用于描述 annotated_seq 中括号区间（目前作为预留类型）
- `splitDataForDetail(d)`：
  - 方便调用者一次性拿到 `{protein, peaks}`（内部调用 parseAnnotatedProtein/parseMsPeaks）

