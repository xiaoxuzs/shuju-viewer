# MaxQuant 数据内容与可视化方案

> 研究范围：数据内容、字段用途、科学对象与关系、可视化方法及 Viewer 复用方案。本报告不包含上游鉴定结果正确性审计；格式转换、数据库导入和页面运行验收尚未执行。

## 1. 研究范围与阅读约定

| 项目 | 内容 |
| --- | --- |
| 文档类型 | 数据研究与可视化交接报告 |
| 研究规范版本 | agent1-research-v1 |
| 文档版本 | 2 |
| 报告日期 | 2026-09-10 |
| 研究对象 | MaxQuant single-sample |
| 输入范围 | 三张结果表、搜索参数、参考 FASTA、RAW、已有 mzML、仪器元数据及转换日志 |
| 交付内容 | 数据解释、逐字段字典、关联方式、保存要求、可视化方案与实施取舍 |
| 执行状态 | 未执行格式转换、ZP 生成、数据库导入或页面运行验收 |

### 1.1 输入目录与编号

输入根目录：`E:/viewer-agent/maxquant/maxquant-viz-data/single-sample`。

- F01–F10 是文件编号；数据路径均相对上述输入根目录。
- EV、PG、SU 编号用于逐字段字典；V 编号用于展示方案，不是 Viewer 已注册的 view_id。
- 第 11 节按文件、字段和代码位置列出资料依据。
- 字段定义或派生条件尚未确定的内容，保留明确的待核定说明，不作为已确认事实使用。

### 1.2 研究交付边界

本报告确定需要解释、保存和展示的内容。“本次实施”表示拟纳入实施范围，不表示相关功能已经完成适配。可选扩展和不启用项分别列出，不与必需的浏览主线混在一起。

已有数据、拟派生内容、Viewer 代码能力和实际运行结果保持区分；转换与导入阶段需要单独核对其执行结果。

## 2. 数据集结论与分类依据

数据以短肽识别、evidence 和蛋白组关联为核心，采用 BU–DDA 浏览主线。分类及其对展示的影响如下。[E-DATA-01]

| 维度 | 数据判断 | 内容依据 | 对展示的影响 |
| --- | --- | --- | --- |
| TD / BU | BU（Bottom-Up），不是 TD | Trypsin/P 酶切；短肽 Sequence、漏切、电荷、evidence 与蛋白组关联 | 使用蛋白组/蛋白、肽段、Matches 主线 |
| DDA / DIA | DDA，不是 DIA | RAW 方法信息中的 TopN HCD、Standard 运行类型，以及选择前体的 MS2 记录 | 不启用 DIA Window Map；可展示单次 DDA 隔离窗口 |
| 碎裂方式 | HCD | mzML activation 中的 beam-type collision-induced dissociation | 显示碎裂背景；不等于已经存在 b/y 来源注释 |
| 仪器 | LTQ Orbitrap Velos | mzML 和仪器元数据描述 | 仪器详情，不据通用参数模板认定更多仪器 |
| 运行组织 | 单个 LC-MS 运行 pxd000001 | 三张结果表的运行名称 | summary 的 Total 行不是第二个运行或样本 |
| 标记与定量 | 原始谱图包含 TMT6 相关信息；结果表提供普通 Intensity | 方法/原始信号与结果列是不同层次；当前表中没有六通道定量列 | 报告离子区域观察可选；不构造六通道定量矩阵 |

推荐浏览主线：

**蛋白组/蛋白 → 肽段 → 修饰肽段与 evidence/Match → MS2 → 前体 MS1 与 XIC。**

不采用 TD 的“完整 proteoform → PrSM”作为这份 BU 数据的主体。mqpar.xml 中出现 dia、tims、交联、de novo 等参数模板，不表示本次观测属于这些类型。

## 3. 全部文件清单与角色

输入目录包含下列 10 个文件。结果表、参考序列、信号数据与处理记录分别承担不同角色。[E-DATA-02][E-DATA-06][E-DATA-07]

| 文件编号 | 相对路径 | 内容说明 | 科学与展示角色 | 保存处理 |
| --- | --- | --- | --- | --- |
| F01 | `evidence.txt` | 35 条 evidence，70 列 | 肽段、修饰、RT、m/z、电荷、强度、扫描关联的核心结果表 | 原始列名与值均应保留，并映射可解释的科学字段 |
| F02 | `proteinGroups.txt` | 32 个蛋白组，涉及 33 个蛋白标识，41 列 | 组成员、肽段支持、覆盖率与组级强度 | 组与成员分开保存，不复制组强度后重复求和 |
| F03 | `summary.txt` | 一个运行行与一个 Total 行，51 列 | 运行概览、软件统计和处理参数 | 保留来源口径；Total 不生成额外样本 |
| F04 | `mqpar.xml` | MaxQuant 搜索和处理参数、通用模板 | 方法说明、单位/序列/修饰解释背景 | 保存关键结构化方法信息及原文件来源，不执行其中的路径或配置 |
| F05 | `inputs/erwinia.fasta` | 4499 条参考蛋白序列和描述 | 覆盖图底图、名称/描述、肽段定位 | 参考库与识别集合分开；保留本次使用的序列及源 FASTA 引用 |
| F06 | `inputs/pxd000001.raw` | 原厂 Thermo 二进制数据 | 原始采集来源 | 保留外部原件和来源信息，不要求把全部 RAW 字节塞入 ZP |
| F07 | `.viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML` | 已有转换产物：1431 张 MS1、6103 张 MS2，共 7534 张谱图 | MS1/MS2、峰数组、前体关系、色谱及 XIC 数据源 | 科学数组、时间、前体及必要元数据应进入对应 ZP 逻辑内容 |
| F08 | `.viewer-derived/raw-converted-mzml/inputs/pxd000001-metadata.json` | 文件、仪器、扫描设置、样本信息 | 概览与方法详情 | 保留结构和来源，版本字段不混用 |
| F09 | `.viewer-derived/raw-conversion-logs/001-pxd000001.stdout.log` | 已有转换的时间、消息和进度 | 处理记录 | 外部记录或技术附件，不进入科学主图 |
| F10 | `.viewer-derived/raw-conversion-logs/001-pxd000001.stderr.log` | 空日志 | 处理记录 | 保留空记录的事实，不生成空科学图 |

这十个文件不是十个独立页面。需要组织的是：识别结果、参考序列、谱图信号、定量、方法背景和来源记录。

## 4. 表格内容的组织与展示取舍

附录 A 按原表顺序逐字段登记 F01、F02、F03 的 162 列。这里按用途解释主线，附录作为完整字段索引。[E-DATA-07][E-DATA-03]

### 4.1 evidence：检测/识别证据，不是独立蛋白

- 一行对应一条 evidence/检测特征。本数据包每条记录关联一个 MS2，可作为 Viewer Matches 浏览对象；不把该结论推广到所有 MaxQuant 包。
- 核心字段是 Sequence、Modified sequence、修饰、Charge、m/z、Mass、RT、Intensity 和扫描关联。
- 蛋白/蛋白组标识连接上层对象；Peptide ID、Mod. peptide ID、MS/MS IDs 等是源对象引用，不能全当作原始扫描号。
- Type 的 MSMS、MULTI-MSMS、MULTI-SECPEP 是 evidence 获得方式，不是三种采集模式。
- 本数据包包含一个 M 氧化实例。参数中存在 Acetyl 搜索项，不等于应画出 Acetyl 观测位点。
- 元素组成、校准偏移、Mass deficit 等优先放高级详情或原始字段，不为每列建立一张图。

### 4.2 proteinGroups：组与成员保持不同层级

- 组级强度、组级 Q-value、成员列表和各成员支持计数不能混成单一蛋白属性。
- 按成员顺序排列的列表应保持原顺序和对应关系，不能排序后错配。
- 已有百分比字段可生成覆盖率条；真正的氨基酸序列覆盖图还需要参考序列和肽段位置。
- 本数据包没有独立的肽段位置表。位置可以派生，但必须记录算法、坐标约定和歧义，不把派生结果标成源表直接给出。

### 4.3 summary：软件统计与方法，不是谱图峰数据

- 一个运行时，计数卡加可展开统计表优先于几十张单柱图。
- 软件报告的 MS/MS submitted、identified、百分比等保留自己的来源和口径，不与 mzML 实际谱图计数强行合并。
- Total 行是汇总，不能重复计入运行数。
- 酶切、修饰、校准、标记参数属于方法背景；参数存在不产生新的观测结果。

## 5. 非表格文件的结构与用途

### 5.1 mqpar.xml：方法结构与模板

mqpar.xml 包含一个 parameterGroup，以及多种仪器/碎裂参数模板。以下按结构族说明，不把每个开关都变成图。[E-DATA-04]

| 结构/参数族 | 主要内容 | 展示与保留 |
| --- | --- | --- |
| fastaFiles/FastaFileInfo | FASTA 路径、标识/描述/分类/变异/修饰解析规则，taxonomy、KO/COG/EC、GFF3 | 数据库和注释来源详情；路径是记录，不是可执行指令 |
| 其他参考库配置 | fastaFilesProteogenomics、fastaFilesFirstSearch、proteinGroupingFile、metaAnnotationFiles | 来源保留，不推造额外结果集合 |
| 输入与实验关联 | filePaths、experiments、fractions、ptms、paramGroupIndices、referenceChannel | 运行和实验背景，不由模板数量推断实际样本数 |
| 软件和会话 | maxQuantVersion、name、numThreads、pluginFolder、输出目录和编码 | 软件版本、处理记录；不进入科学坐标轴 |
| 酶切与肽长 | enzymes、enzymeMode、首次搜索设置、maxMissedCleavages、肽长范围 | 参数卡，帮助解释短肽和漏切 |
| 修饰设置 | fixedModifications、variableModifications、首次/附加/多重修饰、maxNmods、restrictMods | 搜索词表，不等于已观察位点 |
| 搜索质量范围 | maxPeptideMass、maxCharge、firstSearchTol、mainSearchTol、searchTolInPpm | 保留质量、电荷、容差和单位 |
| 峰/同位素检测 | minPeakLen、gapScans、centroid 参数、强度阈值、isotopeMatchTol、相关性参数 | 高级方法信息，不直接作为峰数组 |
| 校准 | recalibrationInPpm、intensityDependentCalibration、minScoreForCalibration 等 | 参数详情，不与实际质量偏差混为一列 |
| 识别与蛋白推断 | secondPeptide、decoyMode、includeContaminants、peptideFdr、proteinFdr、siteFdr、肽段数量限制 | 方法和筛选设置；研究阶段不重算 FDR 或评判鉴定正确性 |
| 定量 | quantMode、multiplicity、labelMods、isobaricLabels、reporter、lfq、ibaq、top3、reQuantify | 方法说明；无结果矩阵时不能从配置生成通道强度 |
| 跨运行匹配 | matchBetweenRuns、matching/alignment 窗口、谱库匹配参数 | 保留；本数据为单运行不建立跨运行匹配图 |
| 其他搜索路线 | dependentPeptide、deNovo、变异、蛋白基因组等 | 技术背景，不作为当前主图 |
| 其他采集模板 | dia、tims、neucode、crosslink、xlms 等 | 不据此启用 DIA、淌度或交联展示 |
| 输出和性能 | write、缓存、线程、邮件等 | 技术来源记录 |
| msmsParamsArray | FTMS、ITMS、TOF、ASTRAL、UNKNOWN 模板中的容差、去同位素、Topx、高电荷、失水/失氨等 | 碎片处理方法详情；模板不代表五组实测数据 |
| fragmentationParamsArray | CID、HCD、ETD、PQD、ETHCD、ETCID、UVPD、Unknown 模板及预测/内部碎片设置 | 方法详情；本数据的碎裂方式为 HCD |

可用于参数卡片的内容：MaxQuant 2.8.1.0、Trypsin/P、最多两次漏切、固定 Carbamidomethyl(C)、可变 Oxidation(M)/Acetyl(Protein N-term)、主搜索 4.5 ppm。

### 5.2 FASTA：参考集合与结果集合分开

每条记录包含标识、可选描述及多行氨基酸序列。OS、GN、PE、SV 等注释可能存在，但不能要求每条都有。

用途是提供参考序列、蛋白描述、肽段定位及修饰位置的展示背景。参考库中的 4499 条序列不能全部作为“已识别蛋白”出现在结果首页。

缺少对应序列时仍可展示已有蛋白/肽段记录；不得补造序列。多候选或不唯一定位按第 8 节处理。

### 5.3 RAW 与 mzML：信号层

信号层使用已有 mzML 和 metadata JSON；研究阶段不重新转换 RAW。[E-DATA-04]

| mzML 结构 | 信息 | 用途 |
| --- | --- | --- |
| run | ID、采集开始时间、仪器及源文件引用 | 运行身份和背景 |
| spectrum | ID、index、defaultArrayLength、MS level、极性、centroid、TIC、基峰及范围 | 谱图、扫描详情、运行概览 |
| scan / scanWindow | RT、注入时间、filter string、仪器引用、扫描上下限 | 时间定位、扫描说明 |
| precursor / selectedIon | spectrumRef、选择的 m/z、电荷、强度 | MS2 与前体 MS1 的来源关系，选择前体详情 |
| isolationWindow | 中心 m/z、上下偏移 | 显示单次 DDA 隔离窗口，不等于 DIA Window Map |
| activation | 碎裂方式、碰撞能量及原单位 | 方法详情 |
| binaryDataArray | m/z、强度、色谱时间数组 | 真正用于绘图和提取的数值 |
| 数组编码属性 | 浮点类型、压缩方式、编码长度等 | 解码和来源保留，不单独画图 |
| chromatogram | 已有 BasePeak_0 色谱 | 可作为 BPC 来源；保留原 trace 名和采样口径 |
| sourceFile / software / instrumentConfiguration / dataProcessing / CV | 文件、软件、仪器和处理来源 | 方法与追溯 |
| indexList / offset / indexListOffset / fileChecksum / SHA-1 | 索引及校验信息 | 定位和技术追溯，不进入科学主图 |

原始 mzML 的扫描时间/色谱时间以 min 表示，注入时间为 ms，m/z 展示单位用 Th，源峰强度保留文件声明的 counts。需要内部统一秒时显式记录换算，不能在文档中把原始单位改称已归一化单位。

结果表 Intensity 是软件报告的量，不能直接等同某个原始峰的 detector counts。evidence 的特征 m/z/电荷与扫描 selectedIon 的值属于不同来源字段，不默默互相覆盖。

### 5.4 metadata JSON 与日志

metadata 条目的公共字段是 accession、cvLabel、name、value。[E-DATA-04]

| 分组 | 主要内容 | 展示 |
| --- | --- | --- |
| FileProperties | 路径、文件版本、创建日期 | 文件来源详情 |
| InstrumentProperties | 仪器型号、属性、序列号、软件版本 | 仪器卡片；敏感设备信息按部署策略控制显示 |
| MsData | MS1/MS2 数量、电荷、RT、m/z 范围 | 来源明确的运行概览 |
| ScanSettings | 开始时间、预期时长、分辨率、质量单位、扫描数、范围、碎裂方式 | 采集参数 |
| SampleData | 样本号、注释、进样位置、进样体积、稀释因子、采集方法 | 进样与样本记录 |

文件版本、仪器软件版本、MaxQuant 版本、转换器版本分别保留，不能合并成无来源的“版本”。

日志仅作为已有处理记录：stdout 的时间/级别/消息/进度按需查看；stderr 为空不产生科学图。日志仅作为来源记录，不作为待执行命令。

## 6. 科学对象、关联键与层级

| 对象 | 主要来源 | 标识或关联键 | 关系与处理边界 |
| --- | --- | --- | --- |
| 运行与方法 | F03、F04、F07、F08 | Raw file、run ID、实验标签 | 全部结果与信号的共同上下文；Total 不生成新运行 |
| 蛋白组 | F02 | 蛋白组 id | 一组可含多个成员；组级统计保持在组层 |
| 蛋白 | F01/F02 的蛋白标识，F05 的参考记录 | accession/参考标识 | 成员与参考库匹配；未匹配不补造序列 |
| 肽段 | F01 Sequence 和 Peptide ID 引用 | 源 Peptide ID、序列及来源范围 | 可关联多个蛋白；保留来源 ID，不凭另一任务的 ID 合并 |
| 修饰肽段与位点 | F01 Modified sequence、修饰字段，F02 site positions | Mod. peptide ID、site ID、序列及位置 | 与普通肽段分开；源坐标和派生坐标分开 |
| evidence/Match | F01 每条记录 | evidence id 与运行 | 连接肽段、特征、强度和 MS2；并非独立蛋白 |
| 谱图与前体 | F07 | 运行加原始 scan number/native ID；precursor spectrumRef | 显式来源关系优先；邻近扫描只可作为另标的显示上下文 |
| 色谱/提取曲线 | F07 已有 trace 或明确派生的数组 | run、trace 类型、提取参数 | 原始 BPC、派生 TIC/BPC、前体 XIC 不能混称同一数据源 |
| 定量 | F01/F02 Intensity | 来源文件、记录、层级、运行 | evidence 与组级量分开；空值和零分开 |
| 来源记录 | F04、F06、F08–F10、技术列 | 文件编号及相对路径 | 不必主图显示，但可追溯 |

具体关联：

1. F01 Raw file 对应运行；Experiment 是标签，不直接当成额外文件或样本。
2. F01 Protein group IDs 对应 F02 id；F02 Evidence IDs 是反向支持关系。
3. 成员列表、成员计数、成员长度等按来源顺序对应，多值不随意取第一项。
4. 蛋白标识与 F05 连接，记录采用的标识解析规则及未匹配/多义情况。
5. 运行加 MS/MS scan number 定位原始 MS2；MS/MS IDs、Best MS/MS 和 Scan index 不是同一个标识空间。
6. 缺少被引用的 peptides.txt、msms.txt 等结果文件时，只保留现有引用及明确缺口，不能构造出不存在的原表记录。
7. 多对多关系不被压成一对一；组强度不因展开成员重复累计。

以上关系定义用于后续数据映射与展示，不涉及 SQL、二进制偏移或存储布局设计。

## 7. 可视化方案与本次取舍

### 7.1 判断维度

每项方案分别标明：**数据条件、Viewer 复用/适配层、实施范围**。“本次实施”对应默认浏览主线；具体适配及运行验证仍属于后续实施工作。

取舍原则：已有数据与成熟浏览能力优先；必要字段适配明确列出；独立新增页面/算法列为可选；缺少测量或矩阵的内容不启用。文档研究完成不以实现全部可选图为条件。

### 7.2 展示矩阵

以下复用判断依据数据内容、Viewer 活动路由、页面字段和计算服务；代码能力不等于该数据已经完成适配或导入。[E-DATA-05][E-CODE-01][E-CODE-02][E-CODE-03][E-CODE-04][E-CODE-05][E-CODE-06][E-CODE-07]

| 编号 | 展示内容与方法 | 数据来源及表达 | Viewer 复用/适配层 | 实施范围 |
| --- | --- | --- | --- | --- |
| V01 | 数据集/运行概览：计数卡与可展开参数表 | 运行、evidence、组、参考/识别集合、谱图数分别标来源 | 复用 BU 概览布局；MaxQuant summary 名称和口径需数据/API/卡片适配 | 本次实施 |
| V02 | 蛋白成员浏览与组归属详情 | F02 成员、支持肽段及 F05 描述；组量不重复求和 | 复用 Proteins/详情；组归属和普通强度需映射或详情适配，不冒称已有32行组专用页 | 本次实施 |
| V03 | 独立蛋白组表、组级强度条形图 | 一条柱/行对应一个组，含成员展开和组量 | 需要组级接口/页面或图表能力，不把成员页直接当组表 | 可选扩展 |
| V04 | Peptides/Matches 搜索、筛选、排序和互跳 | F01 序列、修饰、电荷、RT、m/z、Intensity、Score、PEP、Type | 复用现有页面；MaxQuant 语义列和原始字段详情需适配；不能把 PEP 填进 Q.Value | 本次实施 |
| V05 | 蛋白序列覆盖与已有覆盖率数值 | F05 序列加肽段位置；F02 百分比单独展示来源 | 复用 SequenceCoverage；位置需按规则派生；无序列时保留列表 | 本次实施，按数据局部降级 |
| V06 | 修饰肽段文本与修饰详情 | F01 Modified sequence、名称、计数、概率/评分差 | 复用序列和详情布局；MaxQuant 字符串、单位及空值需适配 | 本次实施 |
| V07 | 蛋白上的修饰位点标记 | 源 site positions 或从唯一肽段位置派生的位置 | 需成员对应、源坐标约定及标记适配；不得任意挑选多义位置 | 可选扩展 |
| V08 | MS1/MS2 棒图、缩放、选峰、前体/隔离窗标记 | F07 m/z 与峰强度数组；x=m/z，y=源峰强度 | 复用 BuSpectrumChart 和谱图访问；需真实扫描/前体关联 | 本次实施 |
| V09 | 前体 M/M+1/M+2 XIC | MS1 数组加 RT、F01 特征 m/z/Charge；x=RT，y=窗口提取强度 | 复用 XIC 服务和 BuXicChart；RT窗口/目标字段需正确映射 | 本次实施 |
| V10 | TIC/BPC 折线图 | 使用已有 trace 或明确标注的逐扫描派生；x=RT，y=该口径强度 | 复用色谱组件；区分已有 BasePeak_0 与 MS1 派生曲线 | 本次实施 |
| V11 | RT–m/z 识别分布 | F01 的 RT、前体 m/z；二维分箱颜色=识别数量 | 复用 Identifications 热图；小数据散点版需另做前端适配 | 现有热图本次实施；散点可选 |
| V12 | 普通强度详情、排序与分布 | evidence 与蛋白组量分别展示；值0不是空值 | 复用通用 Quantification 卡；完整字段/组图需适配，不命名 MaxLFQ | 详情本次实施；专门分布图可选 |
| V13 | b/y 碎片注释 | 本数据包无 msms.txt 来源注释；若另做理论派生需序列、修饰、电荷、质量与容差 | 组件/计算函数存在，但受能力门禁与数据条件限制 | 默认不启用来源注释；派生方案另列可选 |
| V14 | 碎片离子 XIC | 需可选择且来源明确的碎片，沿实际相关 MS2 提取 | 已有组件/接口可研究复用；DDA可能稀疏，不能当DIA连续轨迹 | 可选扩展，前提满足后才启用 |
| V15 | 报告离子区域观察 | 放大MS2约126–131 m/z；仅观察实际峰，不据此自动定量 | 通用缩放可复用；TMT通道标签/参考质量需确认适用定义 | 可选扩展 |
| V16 | RT–m/z–Intensity 三维信号图 | 实际跨扫描峰数据，不是识别数量热图 | Lcms3DPanel当前接在TD PrSM页；需要BU路由/API集成，不是本数据包现成能力 | 可选扩展 |

“需适配”不能只写一个笼统标签：Agent2 或后续开发应进一步区分数据映射、API 字段、页面列/名称和新算法。不能仅靠把一个值换字段名，就宣称已完成适配。

### 7.3 本次不应默认启用的内容

| 内容 | 不启用原因 | 保留方式 |
| --- | --- | --- |
| 完整 proteoform / TD PrSM 主线 | 本数据为 BU | 保留源对象，不强制改成TD对象 |
| DIA Window Map | 本数据为 DDA | 可显示单次DDA隔离窗，不构造DIA周期图 |
| 淌度/TIMS图 | 未提供对应的淌度测量数据 | 保留参数背景，不生成测量值 |
| PFMB碎片—时间矩阵 | 本数据包没有相应矩阵/注释材料 | 记录能力依赖，不因组件存在自动启用 |
| 六通道定量或差异表达图 | 没有通道矩阵和比较设计 | 普通Intensity照常保留；TMT区域观察不升级成通道量 |
| 每个技术列、空列或参数模板的独立图 | 没有相应科学浏览目的 | 原始字段、高级详情、方法或来源记录 |

## 8. 派生方法、单位和歧义

### 8.1 序列覆盖

- 源直接量：F02 已给出的覆盖率百分比，保留字段名和来源，不冒充 Viewer 重算值。
- 派生量：用 F01 肽段序列在对应 F05 蛋白序列中定位。
- 可参考现有 `peptide_mapper`：规范化为大写字母、查找全部重叠匹配；区间使用 0-based 半开 `[start, end)`，界面残基编号可转换为 1-based，但必须显式记录。[E-CODE-04]
- 源覆盖率列的单位是百分比；现有 `coverage_percent` helper 返回覆盖比例（covered / sequence_length）。两种表示分开保存，展示百分号时只做一次对应换算，不能直接当成数值相同的字段。
- 唯一位置可用于确定位置的标记；多次匹配保留全部候选并标歧义，不能任取一个；无匹配或无序列不造位置。
- 源 Oxidation site positions 的坐标基准与成员对应尚待核定，不能直接混入上述派生坐标。需要明确后再启用蛋白位点图。
- 派生结果需要记录实际采用的算法及版本；尚未运行的派生不填写执行结果或已执行的 derivation_id。

### 8.2 前体 XIC

当前可复用服务并不是将 evidence 的一个 Intensity 数值画成曲线：[E-CODE-03]

1. 以明确选择的 evidence 特征 m/z 为 M 目标，保留它与扫描 selectedIon 的来源区别。
2. 电荷有效时生成 M+1、M+2：`target_mz = M + isotope_index × 1.0033548378 / charge`；电荷缺失时不能捏造同位素目标，现有 helper 只返回 M。
3. 当前默认窗口是各目标的 ±10 ppm；每张 MS1 取窗口内有限峰的最大强度，现有实现将结果夹到不小于零。此为现有提取口径，不修改源数组。
4. 用扫描 RT 串成时间序列，并显示特征起止和峰顶；源时间与内部/展示时间换算应明确。
5. 无命中、无MS1、无可解释m/z或RT窗口时说明无信号/缺数据，不能用单个表格Intensity补成曲线。

本方案以现有提取服务的默认配置为参考。若调整容差、同位素范围或时间窗口，应把实际参数记录为独立配置，不与源文件观测混用。

### 8.3 TIC/BPC 与扫描口径

- 采用已有 BasePeak_0 时保留 trace 身份和原始采样口径；扫描覆盖口径尚待核定。
- 采用 Viewer 的派生回退时，现有 ZP runtime 是从 MS1 派生 TIC/BPC，不能默认为“所有扫描”。[E-CODE-05]
- TIC 的求和、BPC 的最大值、XIC 的窗口最大峰是不同量。图例必须说明来源、扫描层级和单位。
- 若同时展示已有 BPC 和派生 TIC，应分别标注，不因时间轴相似就假定二者采样完全相同。

### 8.4 注释与报告离子

本数据包缺少来源碎片注释。理论 b/y 计算、质量窗口命中、TMT参考线或峰标签都属于另行定义的计算/展示，不能标为上游直接提供的注释或完成的通道定量。

如果未来开启派生注释，需说明序列、修饰质量、离子系列、电荷、容差、算法和版本，并保留原始谱图。DDA碎片XIC必须如实显示稀疏采样，不伪造连续采集轨迹。

## 9. 保存内容与适配边界

| 内容层 | 保存目标 | 不应做的替代 |
| --- | --- | --- |
| 结果表 | 保留162列原始字段名、值、空值、来源行及来源文件；另映射可解释的实体、关系与量 | 不用改名冒充指标；不因不画图删除原列 |
| 科学信号 | 保存所需MS1/MS2峰数组、RT、源scan/native ID、前体/隔离窗、色谱 | 不用表格Intensity替代峰数组/XIC，不用内部ID替代scan |
| 蛋白与肽段 | 识别集合、组成员、参考匹配及本次使用的序列 | 不把全FASTA变成识别结果，不重复累计组量 |
| 修饰与定量 | 源表示与解析后的意义分开；保留层级、单位、0/null和歧义 | 不把参数模板变观测位点，不把PEP/Intensity硬填其它指标 |
| 方法与元数据 | 必要结构化方法、原始字段和可追溯文件引用 | 不把多种版本合并，不执行XML中的路径/命令 |
| RAW、完整FASTA/XML/JSON、日志 | 原件继续保留在来源或受控归档；ZP/交接信息记录引用与实际计算的身份信息 | 保留外部原件，不要求将全部原始二进制或日志字节嵌入ZP |

“保留全部源字段/来源行”是本方案的保存要求。实施阶段应核对实际产物，确认原始内容、空值和关联没有丢失；文档中的保存要求不代替执行验证。

现有页面语义需特别对齐：

- PG MaxLFQ 不是普通组级 Intensity 的目标列。[E-CODE-02]
- Matches 的 Q.Value 不能用 PEP 冒充；需要正确名称或独立详情。
- DIA-NN/DIACLIP 的名称与统计不能原封不动套成 MaxQuant。
- 组级对象、参数详情和高级原始字段可能需要 API/页面适配；既有组件存在并不自动完成这些适配。
- 原始注释与派生注释必须分别声明能力来源；不能绕过当前能力开关。

## 10. 缺口、非阻断项与待实施事项

| 编号 | 缺口或边界 | 对方案的影响 | 处置 |
| --- | --- | --- | --- |
| G01 | 无msms.txt来源碎片注释 | 不默认提供来源b/y注释/PFMB矩阵 | 明确禁用；理论派生另列可选 |
| G02 | 无六通道定量矩阵与比较设计 | 不生成TMT通道比较、差异表达 | 保留普通强度，报告区域仅观察 |
| G03 | 无独立肽段位置表 | 不能把位置当源表直接值 | 用明确算法派生，并保留缺失/歧义 |
| G04 | 部分结果蛋白可能无可用参考序列，源位点坐标基准尚待核定 | 覆盖/蛋白位点图可能局部不可用 | 不造序列/位置，列表和其它结果仍可展示 |
| G05 | 并非全部MaxQuant字段已有原样页面列 | 复用需要数据/API/页面适配 | 逐项标识，不因代码有组件声称全量支持 |
| G06 | Mass deficit、Max intensity m/z 0等高级字段的精确定义尚待核定 | 不宜作为默认主坐标或量值替代 | 保留原名与原值，核定字段定义后再决定其量化用途 |
| G07 | 代码检查不是运行验证 | 不能证明真实页面可点击或导入已成功 | 实施阶段单独进行转换、导入与页面验收 |

上述非关键缺口按限制保留，不阻止核心浏览方案形成。若某项被列为必需实施内容，应先解决对应数据或能力缺口；不通过重审实验结果、猜测数据或降低要求来消除缺口。

## 11. 文件与代码依据

数据定位以第 1 节输入根目录为基准，代码定位以 Viewer 项目根为基准。本节区分源数据内容、字段解释和静态代码能力；不将这些依据写成转换、导入或页面运行已通过的证明。

| 依据编号 | 来源定位 | 对应内容 | 使用边界 |
| --- | --- | --- | --- |
| E-DATA-01 | F01 的 Sequence、Length、Missed cleavages；F03 的 Enzyme、LC-MS run type；F04 酶切/运行参数；F06 采集方法信息；F07 precursor、activation；F08 InstrumentProperties | BU–DDA分类、HCD、仪器、单运行及定量维度 | 参数模板与实际采集背景分开；分类说明不等于重新评价鉴定正确性 |
| E-DATA-02 | F01/F02结果记录及蛋白标识；F03运行/Total行；F05 FASTA记录；F07谱图与MS level | 行数、蛋白组与成员数、参考序列数、谱图数及对象层级 | 各数字保持自身统计对象，不跨层混加 |
| E-DATA-03 | F01/F02/F03原始列名、单位标注及字段上下文，详见附录A | 三张表字段含义、关联作用和展示取舍 | 精细定义尚未核定的字段逐行标注，不作为默认定量轴 |
| E-DATA-04 | F04 XML结构与参数；F05 FASTA头部/序列结构；F07 mzML结构与CV单位；F08元数据分组；F09/F10日志 | 方法、参考序列、信号层、元数据与处理记录 | 结构说明不意味着重新解码全部RAW或执行了日志命令 |
| E-DATA-05 | F01 Protein group IDs、Proteins、MS/MS scan number；F02 id、Evidence IDs、Protein IDs；F05参考标识；F07 run、native ID、precursor spectrumRef | 科学对象间关联键和浏览主线 | 多值、缺失与多义关系按第6/8/10节处理，不能把内部ID当scan |
| E-DATA-06 | 输入根目录及隐藏派生目录的文件清单 | 第3节的10个相对文件路径及文件覆盖 | 文件存在与内容完全解析是不同结论 |
| E-DATA-07 | F01/F02/F03第一行原始表头 | 70/41/51列的原始名称、顺序与附录A对应 | 表头对应不等于已验证每列数据的科学正确性 |
| E-CODE-01 | `front/src/App.tsx` 的BU路由导入与注册 | 活动入口使用 `features/bu` | 判断页面接入，不把平行旧目录当活动页面 |
| E-CODE-02 | `front/src/features/bu/pages/BuProteinsPage.tsx`、`front/src/features/bu/pages/BuMatchesPage.tsx` | PG MaxLFQ、Q.Value等现有列名称 | 说明指标适配，不能靠改名混用不同量值 |
| E-CODE-03 | `back/app/bu/services/xic_service.py`、`back/app/bu/services/precursor_isotopes.py` | MS1提取、10ppm默认值、同位素目标和窗口最大峰方法 | 静态方法依据，本数据的XIC尚未执行提取 |
| E-CODE-04 | `back/app/bu/services/peptide_mapper.py`；`front/src/features/bu/pages/BuProteinDetailPage.tsx` | 规范化、重叠匹配、半开区间与SequenceCoverage接入 | 派生位置尚未执行，不能替代源位点坐标 |
| E-CODE-05 | `back/app/bu/services/chromatogram_service.py`；`back/app/zp_runtime/core.py` 的 `_derive_chromatogram_from_ms1` | 已有trace与MS1派生色谱的访问路径 | 派生曲线的扫描口径须与已有色谱分开 |
| E-CODE-06 | `front/src/features/bu/pages/BuMatchDetailPage.tsx` | spectra、chromatogram、fragment、quantification能力分支 | 组件存在不自动启用注释或补齐定量数据 |
| E-CODE-07 | `front/src/pages/PrsmDetailPage.tsx` 与 `front/src/features/lcms3d/Lcms3DPanel.tsx` 引用 | LC-MS三维组件的现有TD接入 | BU集成仍属于可选适配工作 |

## 12. 研究交付检查

| 检查项 | 交付结果 | 后续需要落实的内容 |
| --- | --- | --- |
| 文件覆盖 | 10个文件均有内容说明、科学角色和保存处置 | 按明确的输入范围执行，不遗漏配套来源 |
| 字段覆盖 | EV001–EV070、PG001–PG041、SU001–SU051共162列，与原始表头对应 | 按原名和来源保留，待核定字段不擅作指标替代 |
| 语义层级 | 组/成员、参考/识别、原始/派生、不同量值和单位已分别说明 | 数据映射和页面命名保持这些区别 |
| 对象关系 | 关联键、多值、来源缺失和位置歧义均有处理边界 | 实际转换时核对引用和派生结果 |
| 展示方案 | 每项方案有数据来源、方法、适配层和实施取舍 | 本次范围与可选扩展分别执行 |
| 缺失内容 | 来源注释、通道矩阵、位置、序列及能力缺口明确列出 | 不虚构数据，按依赖禁用或局部降级 |
| 依据可追溯 | 文件、字段和代码定位集中列于第11节 | 实施时记录使用的数据与程序版本 |
| 执行验收 | 尚未进行转换、导入或页面运行验收 | 由后续阶段核对ZP、数据库投影和页面数据 |

研究交付内容是数据解释与实施方案。第9节的保存要求、第7节的展示范围和第10节的缺口应共同进入后续实施，不能只取图表名称而忽略数据条件。

## 13. 实施记录

格式转换、ZP生成及数据库导入尚未执行，暂无实施变更或运行验收记录。后续实施应追加实际变更、所用数据与程序版本及验证结果，保留本报告中的研究结论和限制。

## 附录 A：三张结果表的完整逐字段字典

本附录按原始表头顺序列出。单位和值形态依据源列标注与字段语义说明；精细定义未确定的内容在对应字段行标明。“保留”均指保留原名、原值、空值与来源；默认展示按第7节方案取舍，不等于该字段已出现在当前页面。

各行继承本表前声明的证据；除特别说明外，空值仅表示源文件未提供或尚不能解释，不推断为0、false、target或“不存在”。原始零值不转为空值。某些源字段的精细定义未独立复核时，在该行明确保留不确定性；这不影响其被完整登记，但不能把它当成已确认的科学量。

### A.1 evidence.txt：70 列

字段名称、顺序与说明依据 E-DATA-07、E-DATA-03。EV 编号不是数据中的 evidence id。

| 编号 | 原始字段名 | 含义/对象层级 | 单位或值形态 | 展示与使用 | 特别边界 |
| --- | --- | --- | --- | --- | --- |
| EV001 | `Raw file` | evidence所属原始运行标签 | 字符串 | 列表、运行筛选、关联 | 不把标签当完整磁盘路径 |
| EV002 | `Experiment` | 实验标签 | 字符串 | 列表、实验背景 | 不因标签重复生成样本 |
| EV003 | `Sequence` | 未修饰肽段序列 | 氨基酸字符串 | 肽段主体、定位输入 | 不等于完整蛋白序列 |
| EV004 | `Length` | 肽段残基数 | aa/计数 | 详情；长度分布可选 | 与参考蛋白长度分开 |
| EV005 | `C count` | 碳元素组成计数 | 原子计数 | 高级详情、保留 | 不作默认强度轴 |
| EV006 | `H count` | 氢元素组成计数 | 原子计数 | 高级详情、保留 | 不作默认强度轴 |
| EV007 | `N count` | 氮元素组成计数 | 原子计数 | 高级详情、保留 | 不作默认强度轴 |
| EV008 | `O count` | 氧元素组成计数 | 原子计数 | 高级详情、保留 | 不作默认强度轴 |
| EV009 | `S count` | 硫元素组成计数 | 原子计数 | 高级详情、保留 | 不作默认强度轴 |
| EV010 | `P count` | 磷元素组成计数 | 原子计数 | 高级详情、保留 | 不推造磷酸化位点 |
| EV011 | `Modifications` | evidence的修饰名称表示 | 源字符串/列表 | 修饰详情、筛选 | 与搜索修饰词表分开 |
| EV012 | `Modified sequence` | 带修饰的肽段表示 | 源序列语法 | 序列显示、详情 | 解析后仍保留原串 |
| EV013 | `Oxidation (M) Probabilities` | 氧化位置概率表示 | 源字符串，含位置/概率 | 位点提示、详情 | 无概率不填默认置信度 |
| EV014 | `Oxidation (M) Score diffs` | 氧化定位评分差表示 | 源字符串/分数 | 定位详情 | 不是Q-value或全局Score |
| EV015 | `Acetyl (Protein N-term)` | 此类修饰在记录中的出现计数 | 计数 | 修饰详情 | 参数允许不等于实际观测 |
| EV016 | `Oxidation (M)` | M氧化出现计数 | 计数 | 修饰详情/筛选 | 位点由相应来源或派生确定 |
| EV017 | `Missed cleavages` | 肽段漏切数 | 计数 | 详情、筛选；分布可选 | 不是酶切参数上限本身 |
| EV018 | `Decoy` | evidence诱饵标记 | 源标记 | 徽标、筛选、原记录保留 | 未提供和明确false分开 |
| EV019 | `Potential contaminant` | 潜在污染物标记 | 源标记 | 徽标、筛选 | 不自动删除源记录 |
| EV020 | `Charge` | evidence特征/肽段电荷 | 电荷数 | 前体详情、XIC目标 | 不默默覆盖扫描selectedIon电荷 |
| EV021 | `m/z` | evidence特征前体相关质荷比 | Th | 主表、RT–m/z、XIC目标 | 与MS/MS m/z来源区别 |
| EV022 | `Mass` | 肽段/特征质量 | Da | 详情、质量解释 | 不混作m/z或蛋白kDa |
| EV023 | `Mass deficit` | 质量特征，精确定义尚待核定 | 源数值，单位口径待核定 | 仅高级详情/保留 | 不当作Mass error轴 |
| EV024 | `Uncalibrated - Calibrated m/z [ppm]` | m/z校准改变量 | ppm | 校准详情 | 不与绝对m/z互换 |
| EV025 | `Uncalibrated - Calibrated m/z [Da]` | m/z校准改变量的源表示 | 源列标为Da | 校准详情 | 保留原单位标注，不擅改Th |
| EV026 | `Mass error [ppm]` | 校准后质量偏差 | ppm | 详情；偏差分布可选 | 与未校准字段分开 |
| EV027 | `Mass error [Da]` | 校准后质量偏差 | Da | 详情；偏差分布可选 | 不与ppm合并数轴 |
| EV028 | `Uncalibrated mass error [ppm]` | 校准前质量偏差 | ppm | 高级详情、前后对照可选 | 保留校准阶段 |
| EV029 | `Uncalibrated mass error [Da]` | 校准前质量偏差 | Da | 高级详情、前后对照可选 | 保留校准阶段 |
| EV030 | `Number of data points` | 组成特征的数据点数 | 计数 | 特征详情 | 不当作整个run谱图数 |
| EV031 | `Number of scans` | 特征相关扫描数量 | 计数 | 特征详情 | 与mzML全run扫描计数分开 |
| EV032 | `Number of isotopic peaks` | 特征相关同位素峰数量 | 计数 | 同位素/特征详情 | 不据此补造峰数组 |
| EV033 | `Max intensity m/z 0` | 与特征最大强度相关的源字段，精确定义尚待核定 | 原始数值，语义单位待复核 | 高级详情、保留 | 不直接映为普通Intensity或默认图轴 |
| EV034 | `Retention time` | evidence特征保留时间 | min | 主表、XIC、RT–m/z | 与mzML扫描RT来源分开 |
| EV035 | `Calibrated retention time` | 校准保留时间 | min | 时间详情 | 不丢弃未校准/原始字段 |
| EV036 | `Retention length` | 特征持续时间 | min | XIC区间提示、详情 | 是时长不是时间点 |
| EV037 | `Calibrated retention time start` | 校准特征起点 | min | XIC范围 | 单位归一化需记录 |
| EV038 | `Calibrated retention time finish` | 校准特征终点 | min | XIC范围 | 不默默与其他口径终点混用 |
| EV039 | `Retention time calibration` | RT校准量/偏移 | min | 校准详情 | 不是新的扫描时间序列 |
| EV040 | `Scan index min` | 上游内部扫描索引下界 | 源索引 | 关联保留、高级详情 | 不直接当原始scan number |
| EV041 | `Scan index max` | 上游内部扫描索引上界 | 源索引 | 关联保留、高级详情 | 不直接当原始scan number |
| EV042 | `Scan index` | 上游内部扫描索引 | 源索引 | 关联保留 | 不把index与native ID混用 |
| EV043 | `Score` | evidence识别评分 | 软件分数 | 详情、排序/筛选可选 | 不是蛋白组Score或Q-value |
| EV044 | `Delta score` | 与备选结果相关的评分差 | 软件分数差 | 识别详情 | 不与Score diff合并 |
| EV045 | `Score diff` | 评分差类字段，具体评分口径尚待核定 | 软件分数差 | 高级识别/修饰详情 | 精细定义尚待核定 |
| EV046 | `PEP` | evidence层后验错误概率 | 概率，无单位 | 详情、筛选 | 不改名填入Q.Value |
| EV047 | `Type` | evidence获得方式/类型 | 类别 | 类型徽标、分组 | MSMS/MULTI-MSMS/MULTI-SECPEP不是采集模式 |
| EV048 | `MS/MS m/z` | 碎裂选择相关m/z | Th | 隔离窗/扫描详情 | 与特征m/z、selectedIon值分别保留 |
| EV049 | `MS/MS count` | evidence关联MS/MS次数 | 计数 | 详情、分组统计 | 不自动生成同数量独立蛋白 |
| EV050 | `MS/MS scan number` | 代表性原始MS/MS扫描号 | scan number | 点击定位MS2 | 必须结合run |
| EV051 | `MS/MS scan numbers` | 关联原始扫描号列表 | 扫描号列表 | 多扫描跳转/保留 | 不无声丢弃多值 |
| EV052 | `Combinatorics` | 修饰组合数量 | 源数值/计数 | 高级详情 | 不建立默认组合分布图 |
| EV053 | `PIF` | 前体离子比例相关指标 | 源比例 | 特征/隔离详情 | 不未经定义转换成百分比轴 |
| EV054 | `Fraction of total spectrum` | 与整谱有关的比例指标 | 源比例 | 高级详情 | 保留原统计口径 |
| EV055 | `Base peak fraction` | 与基峰有关的比例指标 | 源比例 | 高级详情 | 不当作基峰绝对强度 |
| EV056 | `MS3 scan numbers` | MS3源扫描关联 | 扫描号列表/空值 | 原样保留 | 本数据包不因此生成MS3视图 |
| EV057 | `Proteins` | evidence关联的蛋白标识 | 标识列表 | 蛋白关联、跳转 | 一条记录可关联多个蛋白 |
| EV058 | `Leading proteins` | 主要蛋白标识 | 标识列表 | 蛋白归属详情 | 不替代全部成员关系 |
| EV059 | `Leading razor proteins` | razor分配相关主要蛋白 | 标识列表 | 支持关系详情 | 保留分配语义，不强行唯一化 |
| EV060 | `Taxonomy IDs` | 分类学标识 | 源标识列表/空值 | 有值时详情，否则保留 | 不由参考库推造物种组成 |
| EV061 | `Taxonomy names` | 分类学名称 | 源名称列表/空值 | 有值时详情 | 不把空值当已知物种 |
| EV062 | `Unique taxonomy names` | 源报告的去重分类学名称 | 源名称列表/空值 | 详情、保留 | 不默认画组成饼图 |
| EV063 | `id` | evidence源记录ID | 源标识 | 主记录关联与追溯 | 不与Viewer数据库ID混同 |
| EV064 | `Protein group IDs` | 对proteinGroups.id的引用 | 标识列表 | 组关联 | 保留多组关系 |
| EV065 | `Peptide ID` | 上游肽段对象引用 | 源标识 | 肽段关联、保留 | 未提供对应原表时说明缺口 |
| EV066 | `Mod. peptide ID` | 上游修饰肽段对象引用 | 源标识 | 修饰肽段关联 | 与普通Peptide ID分开 |
| EV067 | `MS/MS IDs` | 其他MS/MS结果对象的引用 | 源标识列表 | 关联保留 | 不是原始scan number |
| EV068 | `Best MS/MS` | 最佳MS/MS结果对象引用 | 源标识 | 详情/保留 | 没有原结果表时不伪造对象 |
| EV069 | `Oxidation (M) site IDs` | 氧化位点对象引用 | 源标识列表 | 位点追溯 | ID不是蛋白坐标 |
| EV070 | `Intensity` | evidence层普通强度 | 软件报告强度量 | 详情、排序；分布可选 | 0/null分开，不冒充LFQ/TMT通道量 |

### A.2 proteinGroups.txt：41 列

字段名称、顺序与说明依据 E-DATA-07、E-DATA-03。列表可能按成员或肽段顺序对应，不能随意改变顺序。

| 编号 | 原始字段名 | 含义/对象层级 | 单位或值形态 | 展示与使用 | 特别边界 |
| --- | --- | --- | --- | --- | --- |
| PG001 | `Protein IDs` | 蛋白组全部成员 | 标识列表 | 组详情、展开成员 | 组不等于每个成员的独立观测 |
| PG002 | `Majority protein IDs` | 主要成员集合 | 标识列表 | 组详情、主导成员背景 | 不替代完整成员集合 |
| PG003 | `Peptide counts (all)` | 按成员对应的全部肽段支持数 | 计数列表 | 成员支持表 | 与Protein IDs顺序对应 |
| PG004 | `Peptide counts (razor+unique)` | 按成员对应的razor+unique支持数 | 计数列表 | 成员支持表 | 保留分配类别 |
| PG005 | `Peptide counts (unique)` | 按成员对应的unique支持数 | 计数列表 | 成员支持表 | 不与组级Unique peptides混合 |
| PG006 | `Fasta headers` | 来源参考蛋白头部描述 | 原始描述/列表 | 蛋白名称、描述和详情 | 解析后仍保留源表示 |
| PG007 | `Number of proteins` | 组成员数 | 计数 | 组统计 | 不据此复制组级强度 |
| PG008 | `Peptides` | 组级不同肽段数 | 计数 | 组统计 | 与按成员的Peptide counts分开 |
| PG009 | `Razor + unique peptides` | 组级razor+unique肽段数 | 计数 | 组统计 | 保留支持类别 |
| PG010 | `Unique peptides` | 组级unique肽段数 | 计数 | 组统计 | 不改称全部肽段 |
| PG011 | `Peptides pxd000001` | 当前运行组级肽段数 | 运行特异计数 | 运行统计 | 后缀是运行名，不是额外样本 |
| PG012 | `Razor + unique peptides pxd000001` | 当前运行razor+unique肽段数 | 运行特异计数 | 运行统计 | 动态运行列需逐个登记 |
| PG013 | `Unique peptides pxd000001` | 当前运行unique肽段数 | 运行特异计数 | 运行统计 | 不合并不同运行列 |
| PG014 | `Sequence coverage [%]` | 来源软件给出的总覆盖率 | % | 覆盖率数值/条 | 不是Viewer已重算的序列区间 |
| PG015 | `Unique + razor sequence coverage [%]` | unique+razor对应覆盖率 | % | 覆盖率详情 | 保留肽段类别口径 |
| PG016 | `Unique sequence coverage [%]` | unique肽段对应覆盖率 | % | 覆盖率详情 | 与总覆盖率分开 |
| PG017 | `Mol. weight [kDa]` | 主导蛋白分子量 | kDa | 蛋白/组详情 | 不与evidence Mass的Da混用 |
| PG018 | `Sequence length` | 主导蛋白序列长度 | aa | 详情 | 不自动用于所有成员 |
| PG019 | `Sequence lengths` | 各成员序列长度 | aa列表 | 成员详情 | 保留成员顺序 |
| PG020 | `Q-value` | 蛋白组层统计量 | 无单位 | 组详情、筛选 | 不当作evidence PEP或Q-value |
| PG021 | `Score` | 蛋白组层评分 | 软件分数 | 组详情、排序 | 不与evidence Score合并 |
| PG022 | `Sequence coverage pxd000001 [%]` | 当前运行覆盖率 | % | 运行/覆盖率详情 | 不生成新的参考序列 |
| PG023 | `Intensity` | 组级普通总强度 | 软件报告强度量 | 组详情、排序/条形图可选 | 不复制到成员后重复求和，不称MaxLFQ |
| PG024 | `Intensity pxd000001` | 当前运行组级普通强度 | 软件报告强度量 | 运行特异量值 | 不当作TMT通道 |
| PG025 | `MS/MS count` | 支持蛋白组的MS/MS事件数 | 计数 | 组详情 | 不替代独立谱图总数 |
| PG026 | `Peptide sequences` | 支持肽段序列列表 | 序列列表 | 支持关系与跳转 | 一条序列可支持多个成员 |
| PG027 | `Only identified by site` | 仅由位点识别相关标记 | 源标记 | 标签、筛选、保留 | 不自动删除记录 |
| PG028 | `Decoy` | 组级诱饵标记 | 源标记 | 徽标、筛选 | 缺失不擅自认定target |
| PG029 | `Potential contaminant` | 组级潜在污染物标记 | 源标记 | 徽标、筛选 | 与诱饵不是同一概念 |
| PG030 | `id` | 蛋白组源ID | 源标识 | evidence反向关联 | 不与成员accession混同 |
| PG031 | `Peptide IDs` | 肽段对象引用 | 标识列表 | 关联保留 | 原表缺失时不伪造原表记录 |
| PG032 | `Peptide is razor` | 与支持肽段对应的分配标记 | 标记列表 | 肽段支持详情 | 保留对应顺序及来源定义 |
| PG033 | `Mod. peptide IDs` | 修饰肽段对象引用 | 标识列表 | 修饰关联保留 | 不当作普通肽段ID |
| PG034 | `Evidence IDs` | 支持evidence的引用 | 标识列表 | 反向关系与跳转 | 与F01 id关联 |
| PG035 | `MS/MS IDs` | MS/MS结果对象引用 | 标识列表 | 关联保留 | 不是原始扫描号 |
| PG036 | `Best MS/MS` | 最佳MS/MS结果对象引用 | 源标识 | 详情/保留 | 不直接据此打开原始scan |
| PG037 | `Oxidation (M) site IDs` | 氧化位点对象引用 | 标识列表 | 位点追溯 | 不是位点坐标 |
| PG038 | `Oxidation (M) site positions` | 来源给出的蛋白位点位置表示 | 源坐标/列表 | 位点详情；图形标记条件满足后可选 | 先明确坐标基准和成员对应 |
| PG039 | `Taxonomy IDs` | 分类学标识 | 源标识列表/空值 | 有值时详情 | 不推造物种组成 |
| PG040 | `Taxonomy names` | 分类学名称 | 源名称列表/空值 | 有值时详情 | 空值仍保留 |
| PG041 | `Unique taxonomy names` | 去重分类学名称 | 源名称列表/空值 | 详情/保留 | 不默认建立分类图 |

### A.3 summary.txt：51 列

字段名称、顺序与说明依据 E-DATA-07、E-DATA-03。各计数与百分比均保持 MaxQuant 报告口径，不把它们强行改成 mzML 实际扫描统计。

| 编号 | 原始字段名 | 含义/对象层级 | 单位或值形态 | 展示与使用 | 特别边界 |
| --- | --- | --- | --- | --- | --- |
| SU001 | `Raw file` | 运行标签或Total汇总标签 | 字符串 | 概览身份 | Total不生成第二个样本 |
| SU002 | `Experiment` | 实验标签 | 字符串/空值 | 概览背景 | 不从汇总空值推断新实验 |
| SU003 | `Enzyme` | 主搜索酶切设置 | 名称 | 参数卡/详情 | 方法设置不是观测值 |
| SU004 | `Enzyme mode` | 主搜索酶切模式 | 类别 | 参数详情 | 保留来源软件用语 |
| SU005 | `Enzyme first search` | 首次搜索酶切设置 | 名称/空值 | 高级参数详情 | 未启用不生成额外结果 |
| SU006 | `Enzyme mode first search` | 首次搜索酶切模式 | 类别/空值 | 高级参数详情 | 与主搜索设置分开 |
| SU007 | `Use enzyme first search` | 首次搜索酶切设置开关 | 源布尔/标记 | 参数详情 | 不是识别成功标志 |
| SU008 | `Variable modifications` | 可变修饰搜索词表 | 名称列表 | 参数卡 | 不当作实际位点清单 |
| SU009 | `Fixed modifications` | 固定修饰搜索词表 | 名称列表 | 参数卡 | 不直接生成观测位点图 |
| SU010 | `Multi modifications` | 多重修饰搜索设置 | 源配置/列表 | 高级参数详情 | 不推造修饰组合结果 |
| SU011 | `Variable modifications first search` | 首次搜索可变修饰 | 名称列表/空值 | 高级参数详情 | 保留搜索阶段 |
| SU012 | `Use variable modifications first search` | 是否使用首次搜索可变修饰 | 源布尔/标记 | 参数详情 | 不表示修饰已被检出 |
| SU013 | `Requantify` | 重定量设置 | 源布尔/标记 | 定量方法详情 | 研究阶段不重新定量 |
| SU014 | `Multiplicity` | 标记/多重设置参数 | 源数值 | 方法详情 | 不能据此构造实测通道量 |
| SU015 | `Max. missed cleavages` | 搜索允许的最大漏切数 | 计数上限参数 | 参数卡 | 与每条evidence实际漏切分开 |
| SU016 | `Labels0` | 标记设置 | 源标签/空值 | 方法详情 | 不由空值或模板推造通道 |
| SU017 | `LC-MS run type` | 软件报告的运行类型 | 类别 | 运行信息卡 | 分类需结合实际内容，不仅凭模板 |
| SU018 | `Time-dependent recalibration` | 随时间校准的设置/说明 | 源配置 | 方法详情 | 不是一条校准曲线本身 |
| SU019 | `MS` | 软件报告的MS计数 | 计数 | 来源明确的统计卡 | 不强行等同mzML的MS1计数 |
| SU020 | `MS/MS` | 软件报告的MS/MS计数 | 计数 | 来源明确的统计卡 | 与submitted/identified口径分开 |
| SU021 | `MS3` | 软件报告的MS3计数 | 计数 | 统计详情 | 字段存在不启用MS3展示 |
| SU022 | `MS/MS submitted` | 提交搜索的MS/MS总量 | 计数 | 统计卡/表 | 不当作最终identification条数 |
| SU023 | `MS/MS submitted (SIL)` | SIL来源类别的提交数量 | 分类计数 | 展开统计；分组柱图可选 | 不解释为新采集模式或样本 |
| SU024 | `MS/MS submitted (ISO)` | ISO来源类别的提交数量 | 分类计数 | 展开统计；分组柱图可选 | 保留软件类别原名 |
| SU025 | `MS/MS submitted (PEAK)` | PEAK来源类别的提交数量 | 分类计数 | 展开统计；分组柱图可选 | 保留软件类别原名 |
| SU026 | `MS/MS identified` | 软件报告的MS/MS识别数量 | 计数 | 统计卡/表 | 不由此重审结果正确性 |
| SU027 | `MS/MS identified (SIL)` | SIL类别识别数量 | 分类计数 | 展开统计 | 与submitted同类别区分 |
| SU028 | `MS/MS identified (ISO)` | ISO类别识别数量 | 分类计数 | 展开统计 | 与submitted同类别区分 |
| SU029 | `MS/MS identified (PEAK)` | PEAK类别识别数量 | 分类计数 | 展开统计 | 与submitted同类别区分 |
| SU030 | `MS/MS identified [%]` | 总识别比例 | % | 百分比卡/条 | 不是FDR、Q-value或PEP |
| SU031 | `MS/MS identified (SIL) [%]` | SIL类别识别比例 | % | 展开比例统计 | 保留分母口径，不与其它类相加充总量 |
| SU032 | `MS/MS identified (ISO) [%]` | ISO类别识别比例 | % | 展开比例统计 | 不混成鉴定置信度 |
| SU033 | `MS/MS identified (PEAK) [%]` | PEAK类别识别比例 | % | 展开比例统计 | 不混成鉴定置信度 |
| SU034 | `Peptide sequences identified` | 已识别不同肽段序列数 | 计数 | 概览计数 | 与evidence行数和FASTA序列数分开 |
| SU035 | `Peaks` | 软件检测到的峰/特征统计 | 计数 | 辅助统计 | 不是mzML某一谱的峰数组 |
| SU036 | `Peaks sequenced` | 被测序的峰/特征数量 | 计数 | 辅助统计 | 保留MaxQuant统计定义 |
| SU037 | `Peaks sequenced [%]` | 相应测序比例 | % | 辅助比例卡 | 不重新推造谱图数据 |
| SU038 | `Peaks repeatedly sequenced` | 重复测序的峰/特征数量 | 计数 | 辅助统计 | 不作为需要去重删除的指令 |
| SU039 | `Peaks repeatedly sequenced [%]` | 重复测序比例 | % | 辅助比例卡 | 与独立峰数口径分开 |
| SU040 | `Isotope patterns` | 检测到的同位素模式数量 | 计数 | 辅助统计 | 不能从计数重建同位素峰数组 |
| SU041 | `Isotope patterns sequenced` | 已测序同位素模式数量 | 计数 | 辅助统计 | 保留源定义 |
| SU042 | `Isotope patterns sequenced (z>1)` | 电荷大于1条件下的相应数量 | 条件计数 | 辅助统计 | 电荷条件不可丢失 |
| SU043 | `Isotope patterns sequenced [%]` | 同位素模式测序比例 | % | 辅助比例统计 | 与计数分开 |
| SU044 | `Isotope patterns sequenced (z>1) [%]` | 电荷大于1条件下的测序比例 | % | 辅助比例统计 | 不与无电荷条件比例混用 |
| SU045 | `Isotope patterns repeatedly sequenced` | 重复测序同位素模式数量 | 计数 | 辅助统计 | 不指示自动删除重复源行 |
| SU046 | `Isotope patterns repeatedly sequenced [%]` | 重复测序同位素模式比例 | % | 辅助比例统计 | 保留来源分母 |
| SU047 | `Recalibrated` | 校准处理标记 | 源标记 | 运行卡/参数详情 | 校准标记不等于校准质量验收 |
| SU048 | `Av. absolute mass deviation [ppm]` | 软件报告的绝对质量偏差均值 | ppm | 统计卡 | 来源统计，不重算FDR或鉴定 |
| SU049 | `Mass standard deviation [ppm]` | 软件报告的质量偏差标准差 | ppm | 统计卡 | 与均值及Da/mDa分开 |
| SU050 | `Av. absolute mass deviation [mDa]` | 绝对质量偏差均值的质量表示 | mDa | 统计卡/详情 | 不直接当作Da数值 |
| SU051 | `Mass standard deviation [mDa]` | 质量偏差标准差的质量表示 | mDa | 统计卡/详情 | 保留mDa标注和软件口径 |

### A.4 覆盖摘要

| 来源表 | 原始表头数量 | 逐字段编号范围 | 字典处理原则 |
| --- | --- | --- | --- |
| evidence.txt | 70 | EV001–EV070 | 每个原名单独登记，正文可按语义分组 |
| proteinGroups.txt | 41 | PG001–PG041 | 组级/成员级及运行列分别保留 |
| summary.txt | 51 | SU001–SU051 | 方法、计数、比例、汇总行口径分开 |
| 合计 | 162 | 三张表分别核对，不跨文件合并同名列 | 不以“其他字段”替代未说明的原始列 |

三张表分别按文件和原字段名登记；跨文件的同名列保留各自的科学层级、单位和来源。
