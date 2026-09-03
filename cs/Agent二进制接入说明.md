# Agent 二进制接入说明

## 结论

`viewer-agent` 中的 Case、双 Agent、状态机、人工审核和通知思路已接入 Viewer，执行目标收口为项目现有的 `.zp` 二进制主链路。

Agent 不直接写数据库业务大表，不执行模型返回的脚本或命令，也不引入第二套二进制 writer。模型只返回经过 Pydantic 校验的结构化计划；真正的 `.zp` 生成、deep validation、SHA-256 校验和数据集注册继续由 Viewer 自带的 ZP engine 完成。

## 链路

1. 前端未知格式入口提交目录、分析类型、格式名称和可选说明。分析类型可选择 Top-Down、Bottom-Up、Spectra Only，或选择 Custom 后输入最长 80 字符的自定义类别；自定义值去除首尾空白后原样进入 Case 与双 Agent 合同。
2. 后端校验目录并调用公共元数据指纹 API；目录内容不读取全文件正文来计算指纹。
3. Agent 1（本地 OpenAI-compatible `gpt-5.6-sol`）读取不含文件正文的相对路径清单，首轮强制进入工具调用。
4. Agent 1 可以多轮调用 Case 内本地只读 inspector；本地接口不加载 Moonshot Formula。
5. Agent 1 输出带本地证据、缺口和验收标准的 `DatasetBlueprint`；未核验外部来源时引用列表为空。
6. Agent 2 只能生成以下二进制计划之一：
   - `register_existing_zp`
   - `convert_supported_binary_to_zp`
   - `convert_declared_mapping_to_zp`
7. 对声明式映射，Agent 2 只能忠实实现已确认的 Blueprint；缺少 adapter 时返回 `UNSUPPORTED`，不能自行删减内容。
8. 本地 preflight 按运行时 `zp_capabilities` 校验；随后 Agent 1 对照自己的 Blueprint 复核。
9. `binary_executor` 再次校验 Case 相对路径和目录边界，然后调用唯一 ZP writer 链路。
10. 候选文件必须 deep validation、重新打开并执行 Blueprint 中声明的语义核对。
11. 用户批准前不会注册数据集；批准时再次绑定候选 SHA-256 和源指纹。

## `.zp` 书写提示词与能力真相

模型系统提示词包含稳定的 `ZP WRITING GUIDE`，说明 `.zp` 的逻辑块、证据要求和禁止事项；每次调用另外注入运行时 `zp_capabilities`，其内容只来自实际存在的 ZP source adapter 和 extension 常量。

提示词不是执行权限来源。即使模型输出了额外字段、代码、绝对路径、未知转换或未知 extension，Pydantic 和本地 preflight 仍会拒绝。模型不生成二进制字节、offset、checksum、压缩布局、Python 或 Shell；唯一写入器仍是 Viewer `ZpWriter`。

## Agent 1 研究工具

Agent 1 当前只获得以下本地只读工具：

- 文件树、CSV/TSV/JSONL、JSON、XML、mzML、FASTA 检查
- 本地文件哈希
- 表间引用、表到 mzML scan、表到 FASTA accession 核对
- Viewer 当前 ZP 能力检查

当前本地 Sol 模式不加载 Moonshot `web-search` / `fetch` Formula，也不向 Agent 1 提供 Shell、QuickJS、Python code-runner 或写文件工具。mzML 工具只返回谱图/峰数量、RT、precursor、色谱等统计，不返回峰值数组；FASTA 工具不返回序列正文。

## 安全边界

- 模型输出不能包含可执行代码、shell 命令、绝对路径或 `..` 路径。
- Agent 1 首轮必须调用工具，且完成数据类型对应的本地检查后才能输出 Blueprint。
- 工具参数只能使用 Case 相对路径；绝对路径、`..`、symlink 和 junction 被拒绝。
- 初始模型请求不发送文件正文；工具仅返回有界结构化统计。
- 源目录采样不跟随符号链接或 Windows junction/reparse point。
- 模型上下文最多包含 200 个文件条目、8 个样本、每样本 4096 bytes。
- API 不返回源目录、候选 `.zp` 或验证证书的真实路径；只返回 Case/Artifact 引用和哈希。
- 审核采用 `If-Match` Case 版本，用户回答采用 `Idempotency-Key`。
- 自动失败最多重试 3 次，之后进入 `NEEDS_USER`；人工补充信息后增加 context revision。
- 配置 Agent 1 API key 后会把工具的有界结构化统计发送给已配置的本地 OpenAI-compatible 接口；不会上传 RAW、mzML 峰数组或 FASTA 正文。
- 未配置 Key 或模型接口失败时返回 `RESEARCH_UNAVAILABLE`，deterministic fallback 不得冒充 Agent 1 调查完成。

## 入口与配置

前端：

- `/datasets` → `Upload local dataset` → `Unknown format import`
- `/agent-import-cases`：Case 列表
- `/agent-import-cases/{case_id}`：消息、尝试、二进制证据、审核与停止

后端：

- `POST /api/v1/agent-import-cases/from-path`
- `GET /api/v1/agent-import-cases`
- `GET /api/v1/agent-import-cases/{case_id}`
- `POST /api/v1/agent-import-cases/{case_id}/messages`
- `POST /api/v1/agent-import-cases/{case_id}/review/approve`
- `POST /api/v1/agent-import-cases/{case_id}/review/rework`
- `POST /api/v1/agent-import-cases/{case_id}/stop`

环境变量见 `back/.env.example`：

- `AGENT_IMPORT_ENABLED`
- `MOONSHOT_API_KEY` / `MOONSHOT_BASE_URL` / `AGENT_READ_MODEL`（变量名为兼容旧配置保留，当前指向本地 Sol 接口）
- `AGENT_REVIEW_MAX_OUTPUT_TOKENS` / `AGENT_REVIEW_REQUEST_TIMEOUT_SECONDS`
- `DEEPSEEK_API_KEY` / `AGENT_IMPLEMENTATION_MODEL`
- `ZP_ALLOWED_SOURCE_ROOTS`：正式 ZP 服务允许读取的额外根目录；本机已精确配置为 `E:\viewer-agent`
- 原有 `ZP_*` 开关、输出目录和 worker 配置继续生效

## 当前能力边界

本次接入关闭了 `viewer-agent` 原型中直接落通用数据库表、固定 demo importer 和浅层 JSON “验证即成功”的路径。

当前 Agent 可以注册已有 `.zp`，并调用 ZP engine 已存在的 mzML、Thermo RAW、Top-Down bundle、DIA-NN 等转换能力。之前人工硬编码、空谱图的 MaxQuant demo adapter 和 validator 豁免已经删除；本轮由 Agent 1 Blueprint 驱动新增了受控复合 adapter `maxquant_mzml_v1`：它复用真实 mzML core writer，并把 MaxQuant 结果写入既有 Bottom-Up extensions。

该 adapter 已注册进 `SourceInspector`、`SourceAdapterRegistry` 和 Agent `zp_capabilities`。后续目录满足同一严格签名时，Viewer ZP 默认转换链路可直接识别，不再调用模型重新设计：单 run、RAW/mzML/FASTA/mqpar/evidence/proteinGroups 齐全，RAW 与 mzML SHA-1 一致，且实际修饰属于当前支持范围。用户仍可在 Agent Case 中查看 Mapping Plan、要求返工或拒绝；没有通过审核的模型输出不会改变 adapter。

第一版不泛化到多 run、缺 RAW、缺 FASTA、其他厂商 RAW 或新的实际修饰；这些结构仍返回不支持并要求新的 Agent Blueprint/受控 adapter，不能静默套用本规则。

自定义分析类别当前是用户声明的研究语义，不会被静默映射成 Top-Down、Bottom-Up 或 Spectra Only。Viewer 的物理 `datasets/runs.analysis_mode` 仍只使用既有受支持模式；若 Agent 无法为自定义类别提出当前 ZP 能力可执行的物理方案，应返回 `NEEDS_USER` 或 `UNSUPPORTED`，而不是伪造可导入结果。

真实数据验收入口：

```powershell
back\.venv\Scripts\python.exe cs\Kimi研究Agent真实验收.py --output .tmp\Kimi-Agent1-blueprint.json

back\.venv\Scripts\python.exe cs\DeepSeek实施Agent真实验收.py `
  --blueprint .tmp\Kimi-Agent1-blueprint.json `
  --output .tmp\DeepSeek-Agent2-plan.json

back\.venv\Scripts\python.exe cs\Kimi复核Agent2真实验收.py `
  --blueprint .tmp\Kimi-Agent1-blueprint.json `
  --plan .tmp\DeepSeek-Agent2-plan.json `
  --output .tmp\Kimi-Agent1-review.json

back\.venv\Scripts\python.exe cs\MaxQuant复合二进制验收.py
```

研究入口真实调用当前配置的 Agent 1 模型；本地 Sol 模式只使用 Viewer 本地只读工具，不写 `.zp`、数据库或源目录。

## 本地 Sol 切换验证记录

- Agent 1 的实际运行配置已切换为本地 OpenAI-compatible `gpt-5.6-sol`；Agent 2 仍为 `deepseek-v4-pro`，其配置与请求路径未修改。
- 本地接口的工具调用、工具结果回传、`response_format=json_object` 与 `max_completion_tokens` 两轮协议探测均返回 HTTP 200，最终内容可解析为 JSON。
- Agent 1/Agent 2 核心 mock 测试通过；最终后端全量测试 `545 passed, 12 skipped`。
- 前端生产构建通过；lint 为 0 errors、10 个既有 warnings。
- 真实链路已完成：Sol 研究生成 v2 Blueprint，DeepSeek 方案通过 preflight，Sol 复核返回 `APPROVED`，v3 `.zp` deep validation 通过且 issue_count=0。
- 实际输入、完整输出、首轮失败与修正过程见 `cs/双Agent真实联调输入输出记录.md`。

## 第一阶段验证记录

- 后端全量 pytest：`534 passed, 12 skipped`（跳过项为需外部 PostgreSQL/参考资产或本机无符号链接权限的条件用例）。
- 前端 Agent/上传 Playwright：`10 passed`。
- 前端 `npm run build`：通过。
- 前端 `npm run lint`：0 errors；10 个 warning 均为原有文件告警。
- 指纹基准 `MZ20160222DS_histone49_html`：32,998 文件，中位数 `0.0680s`，满足 `≤ 0.5s`。

## 原 Kimi 研究阶段验证记录（切换前历史）

- 旧硬编码 MaxQuant adapter、固定能力清单、空峰 validator 豁免及对应验收脚本已删除。
- 本地 mzML inspector 在 `single-sample` 上独立读出 7,534 spectra、1,431 MS1、6,103 MS2、3,949,930 峰对和一条 7,534 点 BPC，但不向模型返回峰数组。
- 35 个表内 MS/MS scan 全部与 mzML 匹配；32 个 protein-group 引用完整；FASTA 未命中的 4 个 accession 均为外部污染库条目。
- Kimi Formula + 本地工具的模拟多轮协议测试已通过；真实联网验收结果另行记录。

## 真实双 Agent 验收记录（切换前历史）

- Agent 1：`kimi-k3`，完成 17 次工具调用（14 次本地只读检查、2 次 web search、1 次 fetch），生成并通过 Pydantic 校验的 `DatasetBlueprint`。
- Agent 1 Blueprint：识别 10 个源资产、12 类科学实体、13 个建议 ZP 逻辑区块、10 个可视化视图和 8 项明确数据缺口；没有把峰数组或 FASTA 正文发送给模型。
- Agent 1 自主结论：应把完整 mzML spectra/precursor/chromatogram 写入 core blocks，并把 MaxQuant evidence/peptide/protein-group/modification/Intensity 写入 Bottom-Up extensions；缺失 `msms.txt` 时不能声明支持 b/y fragment annotation。
- Adapter 新增前，Agent 2：`deepseek-v4-pro`，真实读取 Agent 1 Blueprint 后返回 `UNSUPPORTED`，准确指出 Viewer 缺少 MaxQuant mapping adapter 和 mzML-core/结果扩展组合能力，没有伪造实现。
- Adapter 新增后，Agent 2 真实返回 `READY`：`maxquant_mzml_v1`、8 个源角色、25 个 canonical field mappings、2 个 exact join rules；本地 preflight 校验物理字段、required 标志、transform、join 和真实计数后 `PASSED`。
- Agent 2 的无效中间方案被 Pydantic/preflight 拒绝；最多 3 次的结构化修复循环只接受完整替换方案，不放宽合同。
- Agent 1 真实复核最终方案并返回 `APPROVED`，`issues=[]`、`questions=[]`。
- Viewer 正式执行链生成 v3 `.zp`，SHA-256 为 `0756a16faba18076c76665b32fba70d1bca67571d403af1ef7a17c703a916bca`，deep validation 和证书快速复验均通过。
- 写后语义回读：7,534 spectra（1,431 MS1 / 6,103 MS2）、6,103 precursors、3,949,930 峰对、1 条 7,534 点 BPC、35 evidence、32 peptides、33 proteins、32 groups、1 observed Oxidation、67 quantification；35/35 exact MS2 links，15 个缺失 Intensity 与 15 个数值零保持区分。
- RAW 实际 SHA-1 与 mzML `MS:1000569` 声明均为 `5e050c8abc697891e2286271e062a8144518108a`；同名替换 RAW 会被拒绝。
- 本轮后端全量 pytest：`534 passed, 12 skipped`；前端 Agent/上传 Playwright `10 passed`；前端 build 通过；lint 0 errors、10 个既有 warnings。
