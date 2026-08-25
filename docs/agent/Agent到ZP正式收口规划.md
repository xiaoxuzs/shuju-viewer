# Agent 到 ZP 正式收口规划

> 文档版本：v0.1
> 编写日期：2026-08-18
> 文档性质：内部规划文档
> 规划范围：从当前 `viewer-agent` 原型走向 Viewer 正式项目中的未知格式 Agent 与 `.zp` 二进制中间层闭环
> 重要说明：本文是规划，不表示相关能力已经全部实现。

## 1. 项目目的

Viewer 的最终目的不是单纯的数据文件查看器，而是一个面向蛋白组学和质谱证据的本地数据平台。它需要把不同来源、不同格式、不同完整度的数据，统一收敛到 Viewer 可以稳定导入、索引、验证和可视化的内部数据体系中。

当前主线能力是：对已知格式进行确定性导入，生成 dataset、runs、派生索引、谱图读取入口和前端证据视图，让用户能浏览蛋白、肽段、谱图、色谱和匹配证据。

后续 Agent 主线要补齐的是：当用户遇到未知格式时，不再只能人工写固定 importer，而是由用户选择目标分类，Agent 在受控边界内分析源目录，生成结构化转换方案，调用 Viewer 允许的二进制转换能力，最终产出可验证的 `.zp` 二进制中间产物，并把该格式挂接到用户选择的分类下。用户如果不满意，可以在 Case 中与 Agent 对话，要求修改方案、重新验证，直到接纳或停止。

因此，正式目标可以概括为：

```text
已知格式：确定性 planner/importer -> Viewer 数据集与可视化
未知格式：用户选分类 -> Agent Case -> 结构化计划 -> 受控执行 -> .zp -> 强验证 -> 用户接纳 -> 分类下复用
```

## 2. 当前基线

### 2.1 主项目 `E:\viewer`

主项目已经具备多类数据导入、谱图访问、派生数据、前端数据集浏览等基础能力。同时，主项目中已有 `.zp` 相关运行时和转换模块的雏形，例如 `zp_runtime`、`zp_conversion`、`vendor/zp_engine/binary_layer` 等。

当前需要注意：

- `.zp` 还不是所有导入流程的默认产物。
- `.zp` 管理和导入转换能力在配置上仍偏保守，正式开关尚未作为主链路启用。
- 现有 Viewer 谱图可视化主要依赖已经接通的 mzML、RAW 转换结果、PFMB 侧车和派生索引。
- Agent 与 `.zp` 的正式闭环尚未落在主项目中。

### 2.2 实验项目 `E:\viewer-agent`

`E:\viewer-agent\viewer` 中已经实现了可参考的 Agent Import 原型。该原型的价值在于：它已经把 Agent Case 作为一个受控任务系统搭起来了。

已具备的部分：

- Agent Case 表、状态机、attempt、message、artifact、notification。
- 后端 API、前端 Case 页面、通知红点、approve/rework 交互。
- 后台 worker 和轻量 LangGraph 状态流。
- 只读 source sampling。
- Agent 1/Agent 2 模型 provider 抽象。
- 结构化 JSON strategy/candidate 输出。
- `profile_executor`，可根据 Agent 输出生成 profile dataset，并注册已有 mzML 或部分 RAW 转换结果。

尚未具备的部分：

- 未知 vendor binary 的真实通用解析。
- Agent 输出 `.zp` 转换格式。
- 完整 ZP bridge。
- 完整二进制谱图服务接入。
- 真正的 execution sandbox。
- 强验证门禁，例如至少一张谱图能通过 API 返回 `mz/intensity`。
- 新格式应用到用户分类并沉淀为后续确定性导入能力。

结论：`viewer-agent` 适合作为正式 Agent 的任务框架参考，但不能直接视为最终实现。它的 Case、状态机、消息、rework、通知、source sampling、profile executor 思路可以复用；二进制执行、`.zp` 产出、验证和格式接纳机制需要补齐或重构。

## 3. 正式闭环目标

正式闭环不是“Agent 说它能导入”，而是要完成一条可验证链路：

1. 用户选择分类，例如 Top-Down、Bottom-Up、仅谱图、DIA、其他扩展分类。
2. 用户选择或上传未知数据目录，并提供可选说明。
3. Viewer 创建 Agent Case，记录源路径引用、数据指纹、用户选择分类和上下文版本。
4. Agent 只通过受控采样工具读取有限信息。
5. Agent 输出结构化策略和转换计划。
6. 后端 executor 只调用白名单 Viewer 服务，不让模型直接跑任意 shell。
7. executor 生成候选 `.zp`。
8. verifier 对 `.zp` 做 deep validation。
9. Viewer staging import 读取 `.zp`，生成临时 dataset/runs/derived data。
10. verifier 调用真实谱图 API，确认至少一个 scan 能返回 mz/intensity。
11. 前端能打开该数据集的谱图或对应证据视图。
12. 用户 approve 后，当前数据集转为正式结果。
13. 如果该格式需要复用，进入人工接纳流程，把新 source profile 挂到对应分类。
14. 用户 rework 时，反馈进入下一轮 Agent 上下文，重新生成计划和验证。

## 4. 核心缺口

### 4.1 分类与格式注册

当前 “UNKNOWN/Other” 还不足以表达正式产品语义。后续需要新增或明确以下概念：

| 概念 | 说明 |
| --- | --- |
| `analysis_category` | 用户选择的大类，例如 Top-Down、Bottom-Up、Spectra Only、DIA、未知其他 |
| `source_profile` | Agent 识别或新建的来源格式，例如某 vendor bundle 或某结果目录布局 |
| `format_profile_version` | 同一个 source profile 的版本 |
| `profile_status` | `candidate`、`staging_passed`、`accepted`、`rejected`、`deprecated` |
| `accepted_adapter_ref` | 人工接纳后对应的确定性 planner/adapter 引用 |

没有这层机制，Agent 成功一次也只能算“当前 Case 导入成功”，不能沉淀为“该分类下的新格式”。

### 4.2 Agent 输出契约

Agent 输出必须从普通说明升级成可执行的结构化契约。建议最小字段如下：

```json
{
  "schema_version": 1,
  "case_id": "uuid",
  "context_revision": 1,
  "analysis_category": "BOTTOM_UP",
  "source_profile": {
    "proposed_name": "vendor_x_result_bundle",
    "version": 1,
    "confidence": 0.82
  },
  "input_roles": [
    {
      "role": "spectrum_source",
      "patterns": ["*.raw", "*.mzML"],
      "required": true,
      "cardinality": "one_or_more"
    }
  ],
  "table_plan": {
    "enabled": true,
    "files": [],
    "field_mappings": []
  },
  "spectra_plan": {
    "enabled": true,
    "ms_levels": ["MS1", "MS2"],
    "run_identity": "file_stem"
  },
  "binary_operation": "convert_supported_binary_to_zp",
  "zp_conversion_plan": {
    "target_format_version": 3,
    "writer_profile": "default",
    "required_blocks": [],
    "extension_blocks": []
  },
  "output_contract": {
    "requires_dataset": true,
    "requires_spectrum_run": true,
    "requires_scan_api_sample": true
  },
  "verifier_checks": [
    "zp_deep_validation",
    "viewer_staging_import",
    "scan_index_non_empty",
    "spectrum_api_returns_peaks"
  ],
  "user_questions": []
}
```

`binary_operation` 必须是白名单枚举，不允许自由文本：

- `none`
- `use_existing_mzml`
- `convert_supported_binary_to_mzml`
- `convert_supported_binary_to_zp`
- `register_existing_zp`

### 4.3 `.zp` 生成链路

正式链路中，Agent 不应直接写 `.zp`。Agent 只负责提出计划，实际写入必须由 Viewer 后端受控服务完成。

建议新增或完善：

```text
back/app/agent_import/binary_executor.py
back/app/ingest/zp/adapter.py
back/app/ingest/zp/contracts.py
back/app/spectrum_zp/reader_service.py
back/app/spectrum_zp/contracts.py
```

职责边界：

- `binary_executor`：读取 Agent plan，调用白名单转换能力，写 Case artifact。
- `ingest/zp`：把已验证 `.zp` 导入 Viewer dataset/runs。
- `spectrum_zp`：根据 dataset/run metadata 读取 `.zp` 中的谱图数组，转换成现有 API DTO。
- `agent_import` route：只做 API 入参、状态查询和 service 调用，不直接解析二进制。

### 4.4 强验证

正式成功必须从“结构正确”升级为“真实可读、可展示”。

最小强验证标准：

| 验证项 | 要求 |
| --- | --- |
| `.zp` 文件存在 | Case 输出目录中有候选 `.zp` |
| `.zp` 身份稳定 | 记录 sha256、大小、格式版本、source fingerprint |
| deep validation | `validate_zp(mode="deep")` 通过 |
| staging import | Viewer 能从 `.zp` 创建 staging dataset |
| spectrum run | 至少一个 run 有可读 `.zp` locator |
| scan index | scan index count 大于 0 |
| spectrum API | 至少一个 scan 返回非空 mz/intensity |
| 前端入口 | 对应页面能拿到 runs 并打开谱图或证据视图 |

### 4.5 用户修改闭环

`viewer-agent` 已有 approve/rework/message 基础，可以沿用并加强。

需要完善：

- rework feedback 必须进入下一轮 `context_revision`。
- 每轮策略、候选、验证结果都要作为 artifact 保存。
- 前端需要展示“本轮修改了什么”和“为什么仍失败”。
- 用户可以修改分类、补充文件语义、确认单位、指定 run 对应关系。
- 每轮失败要给出稳定错误码，而不是只给模型解释文本。

### 4.6 接纳与复用

一次 Case 成功不等于新格式自动进入公共导入链路。

建议区分两层：

| 层级 | 含义 |
| --- | --- |
| 当前 Case 成功 | 当前数据已经通过 `.zp` 和 Viewer staging 验证，可以正式导入 |
| 公共格式接纳 | 该 source profile 被人工审核后挂到分类下，后续同类数据走确定性 planner |

公共格式接纳应至少记录：

- source profile 名称和版本。
- 适用的 analysis category。
- Agent strategy/candidate artifact。
- `.zp` validation certificate。
- 测试样本和验收结果。
- 人工审核人或审核记录。
- 回滚或废弃方式。

## 5. 推荐优先级

### P0：先收口契约和最小闭环

这是当前最应该先做的一步。目标不是立刻支持所有未知格式，而是先跑通一条小而完整的链路。

P0 交付物：

1. 分类字段和 source profile 草案。
2. Agent candidate 输出契约。
3. `binary_operation` 与 `zp_conversion_plan` 白名单字段。
4. `binary_executor` 空壳和最小实现。
5. 一个可控测试输入，能生成或注册 `.zp` staging artifact。
6. verifier 从浅 JSON 检查升级到最小强验证。
7. 前端 Case 页能展示分类、转换计划、验证结果、approve/rework。

P0 验收标准：

- 用户能在创建 Case 时选择分类。
- Agent 产物中有明确 `binary_operation`。
- 后端能基于 plan 走到 `.zp` staging 结果。
- verifier 至少验证一个 scan 的 mz/intensity。
- 用户可以 approve 成功，也可以 rework 进入下一轮。

### P1：正式接入 `.zp` Viewer bridge

P1 目标是让 `.zp` 成为 Viewer 正式可读的数据来源，而不是只作为文件产物存在。

P1 交付物：

1. `ZpImportAdapter`。
2. `ZpSpectrumReaderService`。
3. `.zp` dataset/run metadata contract。
4. `.zp` 谱图 API DTO 映射。
5. TD/BU/Spectra Only 至少一类完整打通。
6. 失败清理和 staging dataset 隐藏策略。

P1 验收标准：

- deep validation 通过的 `.zp` 能导入 staging dataset。
- 谱图 API 能稳定读取 `.zp`。
- 前端复用现有谱图组件，不新造一套重复图表。

### P2：格式接纳与分类复用

P2 目标是把一次成功的 Agent Case 沉淀为后续可复用格式。

P2 交付物：

1. source profile registry。
2. profile version 和状态流。
3. 人工接纳页面或操作入口。
4. planner fallback 接入：已接纳格式不再触发 Agent。
5. 版本回滚和废弃机制。

P2 验收标准：

- 成功 Case 可以被接纳为某分类下的新 source profile。
- 后续同类数据走确定性导入。
- 被废弃或回滚的 profile 不再被自动使用。

### P3：生产级 Agent 运行时

P3 目标是把原型 worker 和轻量 graph 升级到更稳的任务执行能力。

P3 交付物：

1. 独立 worker 或更可靠的后台任务机制。
2. 持久化 checkpoint。
3. 更完整的 execution sandbox。
4. 任务恢复、租约、停止、超时、日志截断。
5. 模型 provider 观测、成本记录和失败分类。

P3 验收标准：

- 后端重启不丢 Case。
- worker 崩溃后不会重复提交副作用。
- 停止任务不会删除源数据或污染正式数据。
- 模型服务失败不消耗科学修复轮次。

## 6. 第一阶段详细计划

第一阶段建议命名为：Agent-ZP 最小闭环。

目标：用最小范围证明“用户选分类 -> Agent 输出结构化 plan -> 后端生成或注册 `.zp` -> Viewer 验证谱图可读 -> 用户 approve/rework”这条链路可行。

### 6.1 工作包

| 工作包 | 内容 | 验证方式 |
| --- | --- | --- |
| W0 | 对齐字段命名：`analysis_category`、`source_profile`、`binary_operation` | 文档和 schema 一致 |
| W1 | 扩展 Agent candidate schema | 单测覆盖合法和非法 plan |
| W2 | 新增 `binary_executor` 最小实现 | executor 不接受自由 shell，只接受白名单枚举 |
| W3 | 接入现有 `.zp` conversion/runtime 能力或注册已有 `.zp` | 生成 artifact，记录 sha256 和版本 |
| W4 | 扩展 verifier | 至少检查 `.zp`、staging、scan API |
| W5 | 前端 Case 页展示转换计划和验证证书 | 手工或 E2E 检查页面状态 |
| W6 | approve/rework 串联 | rework 后 context revision 递增并重新生成计划 |

### 6.2 第一阶段不做的事

为控制范围，第一阶段不建议同时做：

- 不支持所有 vendor binary。
- 不让模型直接写代码、跑 shell 或改仓库。
- 不做多用户权限。
- 不把所有 TD/BU/Spectra Only 一次性打通。
- 不把 source profile 自动发布为公共格式。
- 不重写现有 Viewer 前端图表。

### 6.3 第一阶段推荐样本

第一阶段可以选择一种最可控的样本：

1. 已有 `.zp` 文件：先验证 register/read/import 闭环。
2. 已有 mzML：先通过受控转换生成 `.zp`，再验证 Viewer 读取。
3. 小型人工 fixture：用于测试 writer、reader、validator 和 Viewer API。

优先建议从“已有 `.zp` 或小型 fixture”开始，因为这能先验证 Viewer bridge 和强验证，不会被真实 vendor binary 的复杂性拖住。

## 7. 架构原则

### 7.1 Agent 不直接拥有写入权

Agent 的职责是分析和提出结构化计划。真正执行转换、写 artifact、写 dataset、读谱图，都必须由 Viewer 后端白名单 service 完成。

### 7.2 `.zp` 是中间层，不是前端概念

前端不应该直接理解磁盘路径、二进制布局或 writer 细节。前端只消费 Viewer API 返回的 dataset、run、scan、chromatogram、evidence DTO。

### 7.3 Case 是上下文边界

所有消息、策略、候选、验证报告、`.zp` artifact 都属于一个 Case。不能把多个未知导入任务混在同一个上下文里。

### 7.4 成功必须可复现

每次成功都要保留：

- source fingerprint。
- Agent plan。
- executor 输入。
- `.zp` sha256。
- validation certificate。
- Viewer staging import 结果。
- 用户 approve/rework 记录。

## 8. 风险与处理

| 风险 | 影响 | 处理 |
| --- | --- | --- |
| 先做真实 vendor binary，范围失控 | 长期卡住，闭环无法证明 | 先用已有 `.zp` 或小 fixture 做最小闭环 |
| Agent 输出自由文本 | executor 和 verifier 无法稳定实现 | 先定 JSON contract |
| `.zp` 只生成不读取 | 不能证明 Viewer 可用 | verifier 必须调真实谱图 API |
| 只做当前 Case 导入 | 不能形成长期价值 | P2 增加 source profile registry |
| 模型直接执行代码 | 安全风险高 | 只允许后端白名单 service |
| 前端重复造图表 | 维护成本上升 | 复用现有 Viewer DTO 和组件 |

## 9. 建议立即开始的第一步

建议下一步先做“契约层收口”，而不是直接写大量转换逻辑。

具体动作：

1. 在主项目中明确 `analysis_category`、`source_profile`、`binary_operation`、`zp_conversion_plan` 的字段定义。
2. 对照 `viewer-agent` 当前 `candidate` payload，设计一个兼容升级路径。
3. 写最小 schema 校验测试，保证 Agent 输出不符合契约时不能进入 executor。
4. 再接 `binary_executor`，先支持 `register_existing_zp` 或最小 fixture 转换。
5. 最后把 verifier 接到真实 `.zp` reader 和谱图 API。

这一步完成后，项目方向会从“Agent 原型能跑”推进到“Agent 正式链路有骨架”。后续支持更多未知格式，就可以沿着这个骨架扩展，而不是继续新增固定 demo importer。

## 10. 阶段性完成度判断

按最终目标估算：

| 模块 | 当前判断 |
| --- | --- |
| Viewer 已知格式导入与可视化 | 已有基础，继续补强 |
| `.zp` 中间层基础 | 有雏形，但未成为 Agent 主链路 |
| Agent Case 框架 | `viewer-agent` 中较完整，可迁移参考 |
| Agent 输出契约 | 需要正式收口 |
| 二进制 executor | 基本缺失 |
| `.zp` Viewer bridge | 基本缺失或未完整接入 |
| 强验证 | 当前不足，需要升级 |
| 分类复用 | 仍需设计和实现 |
| 用户 rework 闭环 | 有基础，需要接入真实 plan 和验证 |

综合判断：

- 如果目标是 Agent 框架 demo，当前已有 60% 到 70% 的基础。
- 如果目标是正式产品闭环，当前约 35% 到 45%。
- 最短收口路径不是扩 demo，而是先完成契约、`.zp` bridge、强验证和分类复用。
