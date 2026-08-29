"""Whitelisted bridge from an Agent plan to Viewer's ZP service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.agent_import.contracts import AgentCandidatePlan
from app.agent_import.errors import AgentBinaryPlanError


PrepareZp = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class BinaryExecutionResult:
    zp_path: Path
    output_sha256: str
    format_version: int
    validation_mode: str
    validation_certificate_path: Path | None
    source_fingerprint: str


def execute_binary_plan(
    *,
    case_id: str,
    source_root: str | Path,
    source_fingerprint: str,
    plan: AgentCandidatePlan,
    prepare: PrepareZp | None = None,
) -> BinaryExecutionResult:
    root = Path(source_root).expanduser().resolve(strict=True)
    relative = PurePosixPath(plan.zp_conversion_plan.relative_source)
    selected = root.joinpath(*relative.parts).resolve(strict=True)
    try:
        selected.relative_to(root)
    except ValueError as exc:
        raise AgentBinaryPlanError("relative_source escapes the Case source root") from exc

    prepare_zp = prepare or _default_prepare
    prepared = prepare_zp(
        source_path=selected,
        binary_operation=plan.binary_operation,
        case_id=case_id,
        format_version=plan.zp_conversion_plan.target_format_version,
    )
    zp_path = Path(prepared.path).resolve(strict=True)
    if not zp_path.is_file() or zp_path.suffix.casefold() != ".zp":
        raise AgentBinaryPlanError("the controlled ZP service did not return a .zp artifact")
    output_sha256 = str(prepared.output_sha256).lower()
    if len(output_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in output_sha256):
        raise AgentBinaryPlanError("the controlled ZP service returned an invalid SHA-256")
    certificate = prepared.certificate_path
    return BinaryExecutionResult(
        zp_path=zp_path,
        output_sha256=output_sha256,
        format_version=int(prepared.format_version),
        validation_mode=str(prepared.validation_mode),
        validation_certificate_path=Path(certificate).resolve() if certificate else None,
        source_fingerprint=source_fingerprint,
    )


def _default_prepare(**kwargs: object) -> Any:
    from app.agent_zp.service import prepare_agent_zp_artifact

    return prepare_agent_zp_artifact(**kwargs)
