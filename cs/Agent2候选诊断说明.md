# Agent 2 候选诊断与错误处理

## 本轮修复

- 每次 schema/preflight 拒绝都通过可注入的诊断回调保存 `candidate_diagnostic`，含 context revision、候选尝试号、模型、脱敏候选和字段级错误。保存发生在下一次模型请求之前，不只保留最终摘要。
- Pydantic 错误不保存 `input`、`ctx`；候选中的密钥、认证字段、已知凭据、绝对路径及 URL 脱敏。诊断存在深度、字符串长度和总体大小限制。
- `AGENT_CANDIDATE_SCHEMA_INVALID` 属于 `ENGINEERING_REVIEW`，不再循环请求用户提供实验信息；前端同时兼容历史记录中错误分类不正确的情况。
- mzML 的 `acquisition_mode` 和非空 `acquisition_mode_evidence_refs` 条件现已进入 Agent 可见的 JSON Schema，与现有 Python 校验一致。没有证据时应输出明确的 NEEDS_USER 问题，不得猜测 DDA/DIA。
- 模型 HTTP 失败保留阶段、HTTP 状态和受限原因分类；不把任意上游响应正文、请求体或 traceback 写到日志/页面。

## 不入库诊断

```powershell
back\.venv\Scripts\python.exe cs\Agent2候选诊断.py `
  --case-id <已有 Case UUID> `
  --output .tmp\Agent2诊断\诊断结果.json `
  --attempts 1
```

入口只读取现有 Case、Blueprint 和用户已提交的消息；不调用 Agent 1、不修改 Case、不生成 ZP、不批准导入。拒绝记录和结果写入指定 JSON 文件。默认 1 次请求，最多允许现有上限 3 次；不会覆盖已有诊断文件。

## 2026-09-07 真实验证

Case `bb6453a0-c14c-4709-bee9-79f0bd5313df` 的 revision 2：

1. 修复前描述下的一次独立生成返回 READY，但 `acquisition_mode=null` 且 evidence refs 为空；具体错误为 `zp_conversion_plan.declarative_plan: mzML plans require an evidence-backed acquisition_mode`，用时约356秒。
2. 补齐条件 schema 与提示后，单次生成在约51秒返回符合合同的 NEEDS_USER，明确要求确认采集模式 DDA/DIA，无执行计划。两次诊断均核对 `case_unchanged=true`。

这证明了本次复现的具体失败点和修正后的提问行为，不表示能够追回历史上未保存的候选，也不表示完整数据导入已经成功。需用户根据实际采集情况确认模式，不能由诊断脚本代为回答。

## 回归结果

- 后端全量：652 passed、12 skipped。
- 前端全量 Playwright：167 passed；生产构建通过；lint 0 errors、9 个既有 warnings。
- 指纹基准：32,998 文件，中位 0.2177 秒，满足不超过 0.5 秒。
- 前后两次脱敏诊断保留在 `.tmp/Agent2修复诊断/候选诊断-1.json` 与 `候选诊断-2.json`，没有写回旧 Case。
