# Agent 二进制接入说明

## 结论

`viewer-agent` 中的 Case、双 Agent、状态机、人工审核和通知思路已接入 Viewer，执行目标收口为项目现有的 `.zp` 二进制主链路。

Agent 不直接写数据库业务大表，不执行模型返回的脚本或命令，也不引入第二套二进制 writer。模型只返回经过 Pydantic 校验的结构化计划；真正的 `.zp` 生成、deep validation、SHA-256 校验和数据集注册继续由 Viewer 自带的 ZP engine 完成。

## 链路

1. 前端未知格式入口提交目录、分析类型、格式名称和可选说明。
2. 后端校验目录并调用公共元数据指纹 API；目录内容不读取全文件正文来计算指纹。
3. Agent 1 读取有上限的相对路径清单和小样本，生成分析策略。
4. Agent 2 只能生成以下二进制计划之一：
   - `register_existing_zp`
   - `convert_supported_binary_to_zp`
5. `binary_executor` 校验 Case 相对路径和目录边界，然后调用 `app.agent_zp.service.prepare_agent_zp_artifact()`。
6. 现有 ZP worker 使用项目内唯一 ZP writer 生成候选文件，并执行 deep validation。
7. Case 进入 `READY_FOR_REVIEW`。用户批准前不会注册数据集。
8. 批准时再次 deep validation，并强制候选 SHA-256 与审核时一致；一致后才写入 `datasets`、`runs` 和 `dataset_zp_assets`。

## 安全边界

- 模型输出不能包含可执行代码、shell 命令、绝对路径或 `..` 路径。
- 源目录采样不跟随符号链接或 Windows junction/reparse point。
- 模型上下文最多包含 200 个文件条目、8 个样本、每样本 4096 bytes。
- API 不返回源目录、候选 `.zp` 或验证证书的真实路径；只返回 Case/Artifact 引用和哈希。
- 审核采用 `If-Match` Case 版本，用户回答采用 `Idempotency-Key`。
- 自动失败最多重试 3 次，之后进入 `NEEDS_USER`；人工补充信息后增加 context revision。
- 配置模型 API key 会把上述有限样本发送给对应模型服务；未配置 key 时完全使用本地确定性 fallback，不访问网络。

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
- `MOONSHOT_API_KEY` / `AGENT_READ_MODEL`
- `DEEPSEEK_API_KEY` / `AGENT_IMPLEMENTATION_MODEL`
- 原有 `ZP_*` 开关、输出目录和 worker 配置继续生效

## 当前能力边界

本次接入关闭了 `viewer-agent` 原型中直接落通用数据库表、固定 demo importer 和浅层 JSON “验证即成功”的路径。

当前 Agent 可以注册已有 `.zp`，或调用 ZP engine 已支持的 mzML、Thermo RAW、Top-Down bundle、DIA-NN 等转换能力。对于 ZP engine 尚无 adapter 的真正新格式，Agent 会保留 Case 证据并进入重试/询问流程，不会让模型生成任意代码绕过 writer。支持这类格式时，应在 ZP engine 中新增受测试的 source adapter，再扩展白名单契约。

## 本轮验证记录

- 后端全量 pytest：`524 passed, 12 skipped`（跳过项为需外部 PostgreSQL/参考资产或本机无符号链接权限的条件用例）。
- 前端 Agent/上传 Playwright：`10 passed`。
- 前端 `npm run build`：通过。
- 前端 `npm run lint`：0 errors；10 个 warning 均为原有文件告警。
- 指纹基准 `MZ20160222DS_histone49_html`：32,998 文件，中位数 `0.0680s`，满足 `≤ 0.5s`。
