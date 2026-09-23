"""Whitelisted bridge from an Agent plan to Viewer's ZP service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from collections.abc import Mapping

from app.agent_import.contracts import AgentCandidatePlan
from app.agent_import.errors import AgentBinaryPlanError
from app.agent_import.execution_control import checkpoint
from app.agent_import.mapping_preflight import preflight_mapping_plan
from app.core.config import settings
from app.declarative_ingest import build_declarative_zp_artifact, read_semantic_zp
from app.declarative_ingest.zp_artifact import semantic_verification_summary


PrepareZp = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class BinaryExecutionResult:
    zp_path: Path
    output_sha256: str
    format_version: int
    validation_mode: str
    validation_certificate_path: Path | None
    source_fingerprint: str
    semantic_verification: dict[str, Any] = field(default_factory=dict)


def execute_binary_plan(
    *,
    case_id: str,
    source_root: str | Path,
    source_fingerprint: str,
    plan: AgentCandidatePlan,
    prepare: PrepareZp | None = None,
    trusted_observations: Mapping[str, dict[str, Any]] | None = None,
) -> BinaryExecutionResult:
    if plan.status != "READY" or plan.binary_operation is None or plan.zp_conversion_plan is None:
        raise AgentBinaryPlanError("only a READY Agent plan can execute")
    root = Path(source_root).expanduser().resolve(strict=True)
    declarative = plan.zp_conversion_plan.declarative_plan
    if declarative is not None:
        preflight_mapping_plan(
            source_root=root,
            plan=plan,
            allow_legacy_mapping=False,
            trusted_observations=trusted_observations,
        )
        serialized_plan = declarative.model_dump_json()
        target = _declarative_output_path(case_id, declarative.plan_id, serialized_plan)
        if target.is_file():
            semantic = read_semantic_zp(target)
            if semantic.source_fingerprint != source_fingerprint:
                raise AgentBinaryPlanError("existing declarative artifact belongs to a different source fingerprint")
            if semantic.plan_sha256 != _sha256_text(serialized_plan):
                raise AgentBinaryPlanError("existing declarative artifact belongs to a different mapping plan")
            certificate = target.with_name(f"{target.stem}.deep-validation.json")
            return BinaryExecutionResult(
                zp_path=target,
                output_sha256=_sha256_file(target),
                format_version=3,
                validation_mode="deep",
                validation_certificate_path=certificate if certificate.is_file() else None,
                source_fingerprint=source_fingerprint,
                semantic_verification=semantic_verification_summary(semantic),
            )
        try:
            artifact = build_declarative_zp_artifact(
                source_root=root,
                source_fingerprint=source_fingerprint,
                plan=declarative,
                output_path=target,
                check_cancel=checkpoint,
            )
        except (OSError, ValueError) as exc:
            raise AgentBinaryPlanError(
                str(exc),
                code=str(getattr(exc, "code", "AGENT_BINARY_PLAN_INVALID")),
            ) from exc
        return BinaryExecutionResult(
            zp_path=artifact.path,
            output_sha256=artifact.output_sha256,
            format_version=artifact.format_version,
            validation_mode=artifact.validation_mode,
            validation_certificate_path=artifact.certificate_path,
            source_fingerprint=source_fingerprint,
            semantic_verification=artifact.semantic_verification,
        )
    relative = PurePosixPath(plan.zp_conversion_plan.relative_source)
    selected = root.joinpath(*relative.parts).resolve(strict=True)
    try:
        selected.relative_to(root)
    except ValueError as exc:
        raise AgentBinaryPlanError("relative_source escapes the Case source root") from exc

    preflight = preflight_mapping_plan(
        source_root=root,
        plan=plan,
        allow_legacy_mapping=False,
        trusted_observations=trusted_observations,
    )

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
    semantic_verification = (
        _verify_declared_mapping(zp_path, plan, preflight)
        if plan.binary_operation == "convert_declared_mapping_to_zp"
        else {}
    )
    return BinaryExecutionResult(
        zp_path=zp_path,
        output_sha256=output_sha256,
        format_version=int(prepared.format_version),
        validation_mode=str(prepared.validation_mode),
        validation_certificate_path=Path(certificate).resolve() if certificate else None,
        source_fingerprint=source_fingerprint,
        semantic_verification=semantic_verification,
    )


def _default_prepare(**kwargs: object) -> Any:
    from app.agent_zp.service import prepare_agent_zp_artifact

    return prepare_agent_zp_artifact(**kwargs)


def _declarative_output_path(case_id: str, plan_id: str, serialized_plan: str) -> Path:
    digest = _sha256_text(serialized_plan)[:16]
    safe_plan_id = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in plan_id)
    return settings.resolved_zp_output_root / "agent-cases" / case_id / f"{safe_plan_id}-{digest}.zp"


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _verify_declared_mapping(
    zp_path: Path,
    plan: AgentCandidatePlan,
    preflight: dict[str, Any],
) -> dict[str, Any]:
    assert plan.zp_conversion_plan is not None
    mapping = plan.zp_conversion_plan.mapping_plan
    if mapping is None:
        raise AgentBinaryPlanError("declared mapping verification requires a mapping plan")
    from app.zp_runtime.package import ensure_binary_layer_importable

    ensure_binary_layer_importable()
    from binary_layer import BottomUpReader, ZpReader  # type: ignore[import-not-found]
    from binary_layer.exceptions import ZpReadError  # type: ignore[import-not-found]

    try:
        reader = ZpReader(zp_path)
        spectra = reader.read_spectra()
        precursors = reader.read_precursors()
        bottom_up = BottomUpReader(zp_path)
        summary = bottom_up.get_bottom_up_summary()
        payloads = bottom_up.get_extension_payloads()
        identifications = payloads["bottom_up_identifications"]["records"]
        quantification = payloads.get("bottom_up_quantification", {}).get("records", [])
        metadata = bottom_up.get_metadata()
    except (KeyError, OSError, TypeError, ValueError, ZpReadError) as exc:
        raise AgentBinaryPlanError("written ZP cannot satisfy declared mapping readback") from exc
    actual_counts = {
        "spectra": len(spectra),
        "precursors": len(precursors),
        "evidence_rows": int(summary["identification"]),
        "protein_groups": int(summary["protein_group"]),
    }
    if actual_counts != mapping.expected_counts:
        raise AgentBinaryPlanError("written ZP counts do not match the declared mapping")
    exact_count = sum(
        isinstance(item, dict)
        and item.get("association_kind") == "exact_scan_number"
        and isinstance(item.get("source_scan"), int)
        and isinstance(item.get("source_native_id"), str)
        for item in identifications
    )
    if exact_count != actual_counts["evidence_rows"]:
        raise AgentBinaryPlanError("written ZP did not preserve every exact evidence-to-MS2 link")
    raw_identity = metadata.get("raw_mzml_identity")
    if not isinstance(raw_identity, dict) or raw_identity.get("match") is not True:
        raise AgentBinaryPlanError("written ZP lacks verified RAW-to-mzML provenance")
    null_identification_intensity = sum(
        item.get("entity_kind") == "identification"
        and isinstance(item.get("measurements"), dict)
        and item["measurements"].get("intensity") is None
        for item in quantification
        if isinstance(item, dict)
    )
    zero_protein_group_intensity = sum(
        item.get("entity_kind") == "protein_group"
        and isinstance(item.get("measurements"), dict)
        and item["measurements"].get("intensity") == 0
        for item in quantification
        if isinstance(item, dict)
    )
    return {
        "schema_version": 1,
        "status": "PASSED",
        "mapping_adapter": preflight.get("mapping_adapter"),
        "source_type": summary["source_type"],
        "actual_counts": actual_counts,
        "exact_ms2_association_count": exact_count,
        "quantification_record_count": len(quantification),
        "null_identification_intensity_count": null_identification_intensity,
        "zero_protein_group_intensity_count": zero_protein_group_intensity,
        "raw_mzml_identity_verified": True,
    }
