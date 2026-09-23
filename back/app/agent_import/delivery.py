"""Candidate application gate and factual handover, called by the existing workflow."""

from __future__ import annotations

import json
import sys
import os
from pathlib import Path
from typing import Any

from app.agent_import.errors import AgentImportError
from app.agent_import.input_assets import hash_file
from app.agent_import.source_code import SourceSnapshot, canonical_bytes, digest_bytes
from app.agent_import.verification import AcceptanceContract, CandidateVerifier, VerificationRuntime, verify_receipt, load_acceptance_contract
from app.core.config import settings


def require_auto_test_policy() -> None:
    from sqlalchemy.engine import make_url
    url = make_url(settings.database_url)
    if not (os.environ.get("VIEWER_ENV") == "test" and settings.agent_auto_delivery_enabled
            and settings.agent_candidate_verification_enabled and settings.agent_input_snapshot_enabled
            and not settings.agent_api_worker_enabled and len(settings.agent_internal_token or "") >= 32
            and url.get_backend_name() == "postgresql" and url.host in {"127.0.0.1", "localhost", "::1"}
            and (url.database or "").startswith("viewer_test_") and url.username not in {None, "postgres", "viewer"}):
        raise AgentImportError("AUTO_DELIVERY_NOT_AUTHORIZED", "Automatic delivery is only authorized on an explicitly configured isolated PostgreSQL test runtime.", status_code=403)
    running_root = Path(__file__).resolve().parents[3]
    try:
        manifest = json.loads((running_root / "source-manifest.json").read_text(encoding="utf-8"))
        actual = SourceSnapshot.capture(running_root).identity
        immutable_identity = (
            settings.agent_source_root.resolve() == running_root
            and manifest.get("identity") == actual == settings.viewer_build_id
        )
    except (OSError, ValueError):
        immutable_identity = False
    if not immutable_identity:
        raise AgentImportError("AUTO_DELIVERY_NOT_AUTHORIZED", "Automatic publication requires the identified immutable source snapshot used by the running Worker, not an editable checkout.", status_code=403)


def validate_candidate_application(case: Any, candidate: Path) -> dict:
    if settings.agent_api_worker_enabled:
        raise AgentImportError("APPLICATION_VERIFICATION_NOT_CONFIGURED", "Application validation requires the standalone Worker, not the API process.", status_code=409)
    snapshot = (case.strategy_payload or {}).get("input_snapshot")
    paths = (settings.agent_verification_postgres_bin, settings.agent_verification_node,
             settings.agent_verification_browser_cache, settings.agent_verification_oracle_root)
    key = (settings.agent_verification_signing_key or "").encode("utf-8")
    if not snapshot or any(path is None for path in paths) or len(key) < 32:
        raise AgentImportError("APPLICATION_VERIFICATION_NOT_CONFIGURED", "Retained inputs, trusted source oracle and explicit validation runtime/key are required.", status_code=409)
    requirement_hash = (case.strategy_payload or {}).get("requirements_sha256")
    if not requirement_hash:
        raise AgentImportError("VERIFICATION_BASELINE_REQUIRED", "The source oracle must also bind the exact user requirements.", status_code=409)
    oracle_path = settings.agent_verification_oracle_root / f"{snapshot['sha256']}-{requirement_hash}.json"
    if not oracle_path.is_file():
        raise AgentImportError("VERIFICATION_BASELINE_REQUIRED", "No protected source acceptance oracle exists for this exact content identity.", status_code=409)
    oracle = load_acceptance_contract(oracle_path.read_text(encoding="utf-8"))
    acceptance = (case.strategy_payload or {}).get("source_acceptance")
    if acceptance and acceptance.get("sha256") != digest_bytes(canonical_bytes(oracle.model_dump(mode="json"))):
        raise AgentImportError("VERIFICATION_BASELINE_REQUIRED", "Frozen independent source acceptance changed after research", status_code=409)
    if oracle.source_identity != snapshot["sha256"] or oracle.requirements_sha256 != requirement_hash:
        raise AgentImportError("VERIFICATION_BASELINE_REQUIRED", "Source oracle identity mismatch.", status_code=409)
    candidate_payload = case.candidate_payload or {}
    if candidate_payload.get("physical_analysis_mode", candidate_payload.get("analysis_category")) != "BOTTOM_UP":
        raise AgentImportError("APPLICATION_VALIDATION_COVERAGE_MISSING", "The registered real-browser recipe currently covers Bottom-Up match delivery only.", status_code=409)
    runtime = VerificationRuntime(
        source_root=settings.agent_source_root, postgres_bin=settings.agent_verification_postgres_bin,
        python=Path(sys.executable), node=settings.agent_verification_node,
        browser_cache=settings.agent_verification_browser_cache,
        evidence_root=settings.resolved_zp_output_root / "agent-cases" / case.case_id / "verification",
    )
    try:
        return CandidateVerifier(runtime, signing_key=key).verify(candidate, oracle, case_id=case.case_id, context_revision=case.context_revision,
            input_root=settings.resolved_zp_output_root / "agent-cases" / case.case_id / "source" / "files")
    except AgentImportError:
        raise
    except Exception as exc:
        raise AgentImportError("APPLICATION_VALIDATION_FAILED", "Trusted application validation did not complete; retain the candidate and inspect its evidence before resuming the affected step.",
            status_code=409, diagnostics={"cause_type": type(exc).__name__}) from exc


def assert_application_receipt(case: Any) -> dict:
    verification = case.verification_payload or {}
    receipt = (verification.get("semantic_reconciliation") or {}).get("application_verification")
    snapshot = (case.strategy_payload or {}).get("input_snapshot")
    if not isinstance(receipt, dict) or not isinstance(snapshot, dict) or not case.candidate_zp_path:
        raise AgentImportError("APPLICATION_VERIFICATION_REQUIRED", "Real candidate verification and retained source evidence are required.", status_code=409)
    try:
        verify_receipt(receipt, (settings.agent_verification_signing_key or "").encode("utf-8"),
                       code_sha256=SourceSnapshot.capture(settings.agent_source_root).identity,
                       candidate_sha256=hash_file(Path(case.candidate_zp_path)), source_sha256=snapshot["sha256"])
        record = receipt["record"]
        if record.get("case_id") != case.case_id or record.get("context_revision") != case.context_revision:
            raise ValueError("Case revision identity mismatch")
        operation = record["operation_key"]
        if len(operation) != 64 or any(ch not in "0123456789abcdef" for ch in operation):
            raise ValueError("Invalid verification operation")
        evidence = settings.resolved_zp_output_root / "agent-cases" / case.case_id / "verification" / operation
        for name, key_name in (("browser.json", "browser_artifact_sha256"), ("browser-trace.zip", "trace_sha256")):
            if hash_file(evidence / name) != record[key_name]:
                raise ValueError("Verification artifact changed")
        if record.get("verifier_version") in {"full-semantic-v2.0", "full-semantic-v2.1"} and hash_file(evidence / "full-verification.json") != record.get("full_verification_sha256"):
            raise ValueError("Full verification evidence changed")
        requirement_hash = (case.strategy_payload or {}).get("requirements_sha256")
        oracle_path = settings.agent_verification_oracle_root / f"{snapshot['sha256']}-{requirement_hash}.json"
        oracle = load_acceptance_contract(oracle_path.read_text(encoding="utf-8"))
        if oracle.schema_version >= 2 and record.get("verifier_version") != oracle.verifier_version:
            raise ValueError("Old sampling evidence cannot authorize a full-source contract")
        if oracle.requirements_sha256 != requirement_hash:
            raise ValueError("User requirements changed")
        if digest_bytes(canonical_bytes(oracle.model_dump(mode="json"))) != record["oracle_sha256"]:
            raise ValueError("Protected acceptance oracle changed")
    except (ValueError, KeyError, OSError, TypeError) as exc:
        raise AgentImportError("APPLICATION_VERIFICATION_STALE", "Candidate verification is stale, invalid or incomplete.", status_code=409) from exc
    return receipt


def write_handover(case: Any, imported: Any, *, persist: bool = True) -> dict:
    receipt = assert_application_receipt(case)
    record = receipt["record"]
    plan = case.candidate_payload or {}
    strategy = case.strategy_payload or {}
    blueprint = strategy.get("blueprint") or {}
    retained = strategy["input_snapshot"]
    capabilities = getattr(imported, "capability_report", None) or {}
    # No circular hash: evidence -> document -> document digest/artifact. The
    # signed receipt does not hash a future handover or claim a production release.
    lines = ["# Viewer HANDOVER", "", "## 实际交付身份", "",
             f"- Case: `{case.case_id}`；context revision: {case.context_revision}",
             f"- Dataset ID: {imported.dataset_id}；slug: `{imported.dataset_slug}`",
             f"- ZP SHA-256: `{case.candidate_zp_sha256}`",
             f"- Source content SHA-256: `{retained['sha256']}`",
             f"- Code snapshot SHA-256: `{record['code_sha256']}`", "",
             "这是已导入数据的交接记录，不宣称生产部署或发布修订系统已经完成。", "",
             "## 数据与执行合同", "", str(blueprint.get("executive_summary") or "See the persisted structured plan and source observations."), "",
             f"- Physical mode: `{plan.get('physical_analysis_mode', plan.get('analysis_category'))}`",
             f"- Binary operation: `{plan.get('binary_operation')}`",
             "- 保留源资产位于本 Case 的 source/files；下面逐项记录内容哈希，不以 disposition 代替文件保存。", "",
             "| Source asset | Bytes | SHA-256 |", "| --- | ---: | --- |"]
    for path, entry in retained["files"].items():
        asset_id = digest_bytes(path.encode("utf-8"))
        label = path.replace("|", "&#124;").replace("[", "\\[").replace("]", "\\]")
        lines.append(f"| [{label}](/api/v1/agent-import-cases/{case.case_id}/source-assets/{asset_id}) | {entry['size']} | {entry['sha256']} |")
    lines.extend(["", "来源资产在共享工作区内读取，无需用户登录；链接只接受受管理 asset ID，不接受任意客户端文件路径。"])
    lines.extend(["", "## 真实验证", "", f"- 覆盖范围：{record['scope']}",
                  f"- 独立来源依据：{record['source_evidence']}",
                  f"- PostgreSQL：{record.get('postgres_version', 'unknown')}",
                  f"- 验证操作：`{record['operation_key']}`", "",
                  "| Assertion | Actual | Expected |", "| --- | --- | --- |"])
    for assertion in record["browser_assertions"]:
        cells = [json.dumps(assertion.get(name), ensure_ascii=False).replace("|", "&#124;").replace("\n", " ") for name in ("name", "actual", "expected")]
        lines.append("| " + " | ".join(cells) + " |")
    full = record.get("full_verification")
    if full:
        lines.extend(["", "## 全量核对与抽样边界", "", f"可信验证器：`{full['verifier_version']}`。浏览器检查代表性记录，不宣称点击每条记录。", "",
            "| Layer | Coverage | Expected | Observed |", "| --- | --- | ---: | ---: |"])
        for layer, coverage in full["coverage"].items():
            lines.append(f"| {layer} | {coverage.get('coverage')} | {coverage.get('expected', '-')} | {coverage.get('observed_unique', coverage.get('observed', coverage.get('records', coverage.get('spectra', '-'))))} |")
        lines.extend(["", f"核对阶段耗时（秒）：`{json.dumps(full['timings'], ensure_ascii=False)}`",
            f"核对子进程峰值RSS：{full.get('peak_rss_bytes')} bytes；磁盘台账：{full.get('ledger_bytes')} bytes。",
            "此测量不代表全链路有界内存：当前语义Reader/转换器仍有全量对象。来源强度单位为来源标签，不声称物理标定或已知归一化。",
            "未结构化的原始字段仍在source_fields/原始资产；原始mzML其他CV及辅助数组按完整资产保留。"])
    lines.extend(["", "## 展示与未支持边界", ""])
    for view in capabilities.get("views", []):
        lines.append(f"- `{view['view_id']}`: {view['availability']} — {view.get('message') or view.get('reason_code') or ''}")
    lines.extend(["", "## 工程与验证边界", "", "本路径未执行模型生成代码；未进行生产部署。无谱图/FASTA/注释时不推断这些内容。",
                  "此文档引用确定性运行记录；模型复核 APPROVED 不等于浏览器或入库通过。", ""])
    markdown = "\n".join(lines)
    payload = {"schema_version": 1, "dataset_id": imported.dataset_id, "dataset_slug": imported.dataset_slug,
               "markdown": markdown, "sha256": digest_bytes(markdown.encode("utf-8")),
               "verification_operation": record["operation_key"]}
    if not persist:
        return payload
    target = settings.resolved_zp_output_root / "agent-cases" / case.case_id / case.candidate_zp_sha256 / "HANDOVER.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_text(encoding="utf-8") != markdown:
            raise AgentImportError("HANDOVER_CONFLICT", "An existing handover has a different identity.", status_code=409)
    else:
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(markdown)
    return payload
