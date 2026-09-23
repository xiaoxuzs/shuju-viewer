"""Service for the minimal Agent -> ZP import closure.

The model-facing contract is intentionally narrow: callers provide a structured
binary_operation, and this service only invokes whitelisted Viewer ZP paths.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dataset_capabilities import compile_semantic_capability_report, get_view_catalog
from app.declarative_ingest import DeclarativeExecutionError, read_semantic_zp
from app.declarative_ingest.semantic_schema import SemanticDataset
from app.ingest.zp import project_semantic_zp
from app.schemas.agent_zp import (
    AgentZpImportCreateIn,
    AgentZpImportOut,
    AgentZpRunVerificationOut,
    AgentZpVerificationOut,
)
from app.services.mzml_scan_index import ScanIndexError, load_scan_index
from app.services.mzml_scan_reader import MzmlScanReaderError, get_spectrum_by_scan
from app.zp_conversion.contracts import ZpConversionError
from app.zp_conversion.paths import resolve_source_path
from app.zp_conversion.service import enqueue_conversion, run_conversion_job
from app.zp_runtime.package import BinaryLayerUnavailableError, ensure_binary_layer_importable, zp_read_error_classes


PUBLIC_ERROR_MESSAGES: dict[str, str] = {
    "AGENT_ZP_DISABLED": "Agent ZP import is disabled on this server.",
    "AGENT_ZP_PATH_MUST_BE_ZP": "register_existing_zp requires a .zp file.",
    "AGENT_ZP_VALIDATION_FAILED": "The .zp file failed deep validation.",
    "AGENT_ZP_NO_RUNS": "The .zp file contains no runs.",
    "AGENT_ZP_NO_READABLE_SCAN": "No registered ZP run returned a readable spectrum.",
    "AGENT_ZP_DATASET_SLUG_EXISTS": "A dataset with this slug already exists.",
    "AGENT_ZP_DATASET_FINGERPRINT_EXISTS": "This source fingerprint was already imported through Agent ZP.",
    "AGENT_ZP_WORKER_FAILED": "The ZP conversion worker did not produce a valid .zp artifact.",
    "AGENT_ZP_CANDIDATE_CHANGED": "The approved .zp candidate changed after review.",
    "AGENT_ZP_BINARY_LAYER_UNAVAILABLE": "The configured ZP binary layer is unavailable.",
    "AGENT_ZP_UNSUPPORTED_BUSINESS_EXTENSION": (
        "This ZP contains business extensions that do not have a safe universal-schema projector."
    ),
    "AGENT_ZP_INTERNAL_ERROR": "Agent ZP import failed.",
}


class AgentZpError(Exception):
    def __init__(self, code: str, message: str | None = None, *, status_code: int = 400) -> None:
        self.code = code
        self.message = message or PUBLIC_ERROR_MESSAGES.get(code, PUBLIC_ERROR_MESSAGES["AGENT_ZP_INTERNAL_ERROR"])
        self.status_code = status_code
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class _PreparedZp:
    path: Path
    format_version: int
    output_sha256: str
    validation_mode: str
    certificate_path: Path | None


@dataclass(frozen=True, slots=True)
class _ZpRun:
    zp_run_id: str
    source_file: str
    run_name: str


@dataclass(frozen=True, slots=True)
class AgentZpStagingResult:
    transient_dataset_id: int
    verification: dict[str, Any]
    capability_report: dict[str, Any] | None


def import_agent_zp_candidate(
    session: Session,
    body: AgentZpImportCreateIn,
    *,
    case_id: str | None = None,
    expected_sha256: str | None = None,
    source_fingerprint: str | None = None,
) -> AgentZpImportOut:
    _require_enabled()
    case_id = case_id or str(uuid.uuid4())
    try:
        existing = _existing_import_result(
            session,
            body=body,
            case_id=case_id,
            expected_sha256=expected_sha256,
            source_fingerprint=source_fingerprint,
        )
        if existing is not None:
            return existing
        _reject_duplicate_fingerprint(session, source_fingerprint)
        prepared = prepare_agent_zp_artifact(
            source_path=body.source_path,
            binary_operation=body.binary_operation,
            case_id=case_id,
            format_version=body.format_version,
        )
        if expected_sha256 is not None and prepared.output_sha256.casefold() != expected_sha256.casefold():
            raise AgentZpError("AGENT_ZP_CANDIDATE_CHANGED", status_code=409)
        semantic = _semantic_dataset_or_none(prepared.path)
        runs = _read_zp_runs(prepared.path, semantic=semantic)
        dataset_id, run_ids, capability_report = _insert_dataset_and_runs(
            session,
            body,
            prepared,
            runs,
            case_id=case_id,
            source_fingerprint=source_fingerprint,
            semantic=semantic,
        )
        verification = _verify_dataset(
            session,
            dataset_id=dataset_id,
            run_ids=run_ids,
            validation_mode=prepared.validation_mode,
            semantic=semantic,
        )
        session.execute(
            text("UPDATE datasets SET status = 'READY' WHERE dataset_id = :dataset_id"),
            {"dataset_id": dataset_id},
        )
        session.execute(
            text("UPDATE runs SET status = 'READY' WHERE dataset_id = :dataset_id"),
            {"dataset_id": dataset_id},
        )
        session.commit()
    except AgentZpError:
        session.rollback()
        raise
    except ZpConversionError as exc:
        session.rollback()
        raise AgentZpError(exc.code, exc.message, status_code=exc.status_code) from exc
    except BinaryLayerUnavailableError as exc:
        session.rollback()
        raise AgentZpError("AGENT_ZP_BINARY_LAYER_UNAVAILABLE", status_code=503) from exc
    except IntegrityError as exc:
        session.rollback()
        raise AgentZpError("AGENT_ZP_DATASET_SLUG_EXISTS", status_code=409) from exc
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        raise AgentZpError("AGENT_ZP_INTERNAL_ERROR", status_code=500) from exc

    return AgentZpImportOut(
        case_id=case_id,
        status="success",
        binary_operation=body.binary_operation,
        analysis_category=body.analysis_category,
        source_profile=body.source_profile,
        dataset_id=dataset_id,
        dataset_slug=body.slug,
        run_ids=run_ids,
        zp_format_version=prepared.format_version,
        zp_output_sha256=prepared.output_sha256,
        validation_mode=prepared.validation_mode,
        verification=verification,
        capability_report=capability_report,
    )


def stage_agent_zp_candidate(
    session: Session,
    body: AgentZpImportCreateIn,
    *,
    case_id: str,
    expected_sha256: str,
    source_fingerprint: str,
) -> AgentZpStagingResult:
    """Exercise the real Viewer projection and read API contract, then roll it back."""

    _require_enabled()
    try:
        _reject_duplicate_fingerprint(session, source_fingerprint)
        prepared = _validate_existing_zp(resolve_source_path(body.source_path), case_id=f"{case_id}-staging")
        if prepared.output_sha256.casefold() != expected_sha256.casefold():
            raise AgentZpError("AGENT_ZP_CANDIDATE_CHANGED", status_code=409)
        semantic = _semantic_dataset_or_none(prepared.path)
        runs = _read_zp_runs(prepared.path, semantic=semantic)
        dataset_id, run_ids, capability_report = _insert_dataset_and_runs(
            session,
            body,
            prepared,
            runs,
            case_id=case_id,
            source_fingerprint=source_fingerprint,
            semantic=semantic,
        )
        verification = _verify_dataset(
            session,
            dataset_id=dataset_id,
            run_ids=run_ids,
            validation_mode=prepared.validation_mode,
            semantic=semantic,
        )
        result = AgentZpStagingResult(
            transient_dataset_id=dataset_id,
            verification=verification.model_dump(mode="json"),
            capability_report=capability_report,
        )
    except AgentZpError:
        raise
    except BinaryLayerUnavailableError as exc:
        raise AgentZpError("AGENT_ZP_BINARY_LAYER_UNAVAILABLE", status_code=503) from exc
    except IntegrityError as exc:
        raise AgentZpError("AGENT_ZP_DATASET_SLUG_EXISTS", status_code=409) from exc
    except Exception as exc:  # noqa: BLE001
        raise AgentZpError("AGENT_ZP_INTERNAL_ERROR", status_code=500) from exc
    finally:
        session.rollback()
    return result


def prepare_agent_zp_artifact(
    *,
    source_path: str | Path,
    binary_operation: str,
    case_id: str,
    format_version: int | None,
) -> _PreparedZp:
    """Run only Viewer's approved register/convert path and return a deep-validated artifact."""
    _require_enabled()
    source = resolve_source_path(source_path)
    if binary_operation == "register_existing_zp":
        return _validate_existing_zp(source, case_id=case_id)
    if binary_operation == "convert_supported_binary_to_zp":
        return _convert_source_to_zp(source, format_version=format_version)
    if binary_operation == "convert_declared_mapping_to_zp":
        return _convert_source_to_zp(source, format_version=format_version)
    raise AgentZpError("AGENT_ZP_INTERNAL_ERROR", "Unsupported Agent ZP binary operation.", status_code=422)


def _require_enabled() -> None:
    if not settings.zp_management_enabled or not settings.zp_import_conversion_enabled:
        raise AgentZpError("AGENT_ZP_DISABLED", status_code=403)


def _validate_existing_zp(path: Path, *, case_id: str) -> _PreparedZp:
    if path.suffix.lower() != ".zp":
        raise AgentZpError("AGENT_ZP_PATH_MUST_BE_ZP", status_code=422)
    ensure_binary_layer_importable()
    from binary_layer import validate_zp  # type: ignore[import-not-found]

    certificate_path = settings.resolved_zp_output_root / f"{case_id}.deep-validation.json"
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    validation = validate_zp(path, mode="deep", certificate_path=certificate_path)
    if not validation.valid:
        raise AgentZpError("AGENT_ZP_VALIDATION_FAILED", status_code=422)
    return _PreparedZp(
        path=path,
        format_version=int(validation.version or settings.zp_default_format_version),
        output_sha256=str(validation.file_sha256 or _sha256(path)),
        validation_mode=str(validation.mode or "deep"),
        certificate_path=certificate_path,
    )


def _convert_source_to_zp(source: Path, *, format_version: int | None) -> _PreparedZp:
    job = enqueue_conversion(
        source_path=source,
        format_version=format_version,
        start_background=False,
    )
    finished = run_conversion_job(job.job_id)
    if (
        finished is None
        or finished.status != "success"
        or finished.zp_final_path is None
        or finished.output_sha256 is None
    ):
        raise AgentZpError("AGENT_ZP_WORKER_FAILED", status_code=422)
    return _PreparedZp(
        path=finished.zp_final_path,
        format_version=finished.format_version,
        output_sha256=finished.output_sha256,
        validation_mode=finished.validation_mode or "deep",
        certificate_path=finished.validation_certificate_path,
    )


def _semantic_dataset_or_none(path: Path) -> SemanticDataset | None:
    ensure_binary_layer_importable()
    from binary_layer import ZpReader  # type: ignore[import-not-found]

    try:
        extension_types = {item.extension_type for item in ZpReader(path).read_extensions()}
    except zp_read_error_classes() as exc:
        raise AgentZpError("AGENT_ZP_VALIDATION_FAILED", status_code=422) from exc
    if "viewer_semantic_dataset" not in extension_types:
        if any(item.startswith(("bottom_up_", "top_down_")) for item in extension_types):
            raise AgentZpError("AGENT_ZP_UNSUPPORTED_BUSINESS_EXTENSION", status_code=422)
        return None
    try:
        return read_semantic_zp(path)
    except DeclarativeExecutionError as exc:
        raise AgentZpError(
            "AGENT_ZP_VALIDATION_FAILED",
            "The declarative semantic extension failed strict validation.",
            status_code=422,
        ) from exc


def _read_zp_runs(path: Path, *, semantic: SemanticDataset | None = None) -> list[_ZpRun]:
    ensure_binary_layer_importable()
    from binary_layer import ZpReader  # type: ignore[import-not-found]

    try:
        reader = ZpReader(path)
        raw_runs = reader.read_runs()
    except zp_read_error_classes() as exc:
        raise AgentZpError("AGENT_ZP_VALIDATION_FAILED", status_code=422) from exc
    runs = [
        _ZpRun(
            zp_run_id=str(getattr(run, "run_id", "") or ""),
            source_file=str(getattr(run, "source_file", "") or ""),
            run_name=str(getattr(run, "run_name", "") or ""),
        )
        for run in raw_runs
    ]
    if not runs and semantic is not None:
        runs = [
            _ZpRun(
                zp_run_id=item.run_id,
                source_file=item.source_file or "",
                run_name=item.name,
            )
            for item in semantic.runs
        ]
    if not runs and semantic is None:
        raise AgentZpError("AGENT_ZP_NO_RUNS", status_code=422)
    return runs


def _insert_dataset_and_runs(
    session: Session,
    body: AgentZpImportCreateIn,
    prepared: _PreparedZp,
    runs: list[_ZpRun],
    *,
    case_id: str,
    source_fingerprint: str | None,
    semantic: SemanticDataset | None = None,
) -> tuple[int, list[int], dict[str, Any] | None]:
    if body.replace_existing:
        session.execute(text("DELETE FROM datasets WHERE slug = :slug"), {"slug": body.slug})

    dataset_json = _dataset_json_fields(session)
    capabilities = _zp_capabilities(prepared.path, semantic)
    extra_metadata: dict[str, Any] = {
        "agent_zp": {
            "case_id": case_id,
            "binary_operation": body.binary_operation,
            "analysis_category": body.analysis_category,
            "source_profile": body.source_profile,
            "zp_format_version": prepared.format_version,
            "zp_output_sha256": prepared.output_sha256,
            "validation_mode": prepared.validation_mode,
            "embedded_source_fingerprint": semantic.source_fingerprint if semantic else None,
            "validation_certificate_name": (
                prepared.certificate_path.name if prepared.certificate_path else None
            ),
        }
    }
    dataset_row = session.execute(
        text(
            f"""
            INSERT INTO datasets (
                dataset_name, slug, analysis_mode, source_software,
                source_root, status, description, capabilities, extra_metadata,
                source_dataset_fingerprint, source_import_kind
            )
            VALUES (
                :name, :slug, :analysis_mode, 'Agent-ZP',
                :source_root, 'IMPORTED', :description,
                {dataset_json["capabilities"]}, {dataset_json["extra_metadata"]},
                :source_fingerprint, 'AGENT_ZP'
            )
            RETURNING dataset_id
            """
        ),
        {
            "name": body.name,
            "slug": body.slug,
            "analysis_mode": _analysis_mode(body.analysis_category),
            "source_root": str(prepared.path.parent),
            "description": body.description or "Agent-ZP spectra dataset",
            "source_fingerprint": source_fingerprint,
            "capabilities": _json(capabilities),
            "extra_metadata": _json(extra_metadata),
        },
    ).one()
    dataset_id = int(dataset_row.dataset_id)
    run_ids, run_id_by_zp_id = _insert_runs(
        session,
        dataset_id=dataset_id,
        body=body,
        runs=runs,
        prepared=prepared,
        semantic=semantic,
    )
    capability_report: dict[str, Any] | None = None
    if semantic is not None:
        semantic, projection = project_semantic_zp(
            session,
            dataset_id=dataset_id,
            zp_path=prepared.path,
            run_id_by_semantic_id=run_id_by_zp_id,
        )
        report = compile_semantic_capability_report(
            dataset_id=dataset_id,
            source_case_id=case_id,
            semantic=semantic,
            requested_view_ids=list(
                dict.fromkeys(
                    [
                        *(item.view_id for item in get_view_catalog("BOTTOM_UP")),
                        *semantic.requested_view_ids,
                    ]
                )
            ),
        )
        capability_report = report.model_dump(mode="json")
        extra_metadata["dataset_capability_report"] = capability_report
        extra_metadata["semantic_projection"] = projection.as_dict()
        session.execute(
            text(
                f"""
                UPDATE datasets
                SET capabilities = {dataset_json['capabilities']},
                    extra_metadata = {dataset_json['extra_metadata']}
                WHERE dataset_id = :dataset_id
                """
            ),
            {
                "dataset_id": dataset_id,
                "capabilities": _json(capabilities),
                "extra_metadata": _json(extra_metadata),
            },
        )
    _insert_dataset_asset(
        session,
        dataset_id=dataset_id,
        prepared=prepared,
        source_fingerprint=source_fingerprint,
        capabilities=capabilities,
    )
    return dataset_id, run_ids, capability_report


def _insert_runs(
    session: Session,
    *,
    dataset_id: int,
    body: AgentZpImportCreateIn,
    runs: list[_ZpRun],
    prepared: _PreparedZp,
    semantic: SemanticDataset | None = None,
) -> tuple[list[int], dict[str, int]]:
    json_fields = _run_json_fields(session)
    run_ids: list[int] = []
    run_id_by_zp_id: dict[str, int] = {}
    for index, run in enumerate(runs, start=1):
        display_name = run.source_file or run.run_name or run.zp_run_id or f"run_{index}"
        run_row = session.execute(
            text(
                f"""
                INSERT INTO runs (
                    dataset_id, file_path, file_name,
                    analysis_mode, software, status, run_metadata
                )
                VALUES (
                    :dataset_id, :file_path, :file_name,
                    :analysis_mode, 'Agent-ZP', 'IMPORTED', {json_fields["run_metadata"]}
                )
                RETURNING run_id
                """
            ),
            {
                "dataset_id": dataset_id,
                "file_path": display_name,
                "file_name": display_name,
                "analysis_mode": _analysis_mode(body.analysis_category),
                "run_metadata": _json(
                    {
                        "raw_format": "zp",
                        "run_name": run.run_name,
                        "source_file": run.source_file,
                        "zp_run_id": run.zp_run_id,
                        "zp_format_version": prepared.format_version,
                        "zp_output_sha256": prepared.output_sha256,
                        "agent_zp_spectrum": True,
                    }
                ),
            },
        ).one()
        database_run_id = int(run_row.run_id)
        run_ids.append(database_run_id)
        run_id_by_zp_id[run.zp_run_id] = database_run_id
    if semantic is not None:
        if len(runs) == 1 and len(semantic.runs) == 1:
            run_id_by_zp_id[semantic.runs[0].run_id] = run_ids[0]
        else:
            database_by_name = {
                run.run_name: run_id_by_zp_id[run.zp_run_id]
                for run in runs
                if run.run_name
            }
            for semantic_run in semantic.runs:
                database_run_id = database_by_name.get(semantic_run.name)
                if database_run_id is not None:
                    run_id_by_zp_id[semantic_run.run_id] = database_run_id
        missing = [item.run_id for item in semantic.runs if item.run_id not in run_id_by_zp_id]
        if missing:
            raise AgentZpError(
                "AGENT_ZP_VALIDATION_FAILED",
                "Semantic runs cannot be reconciled with the ZP core runs.",
                status_code=422,
            )
    return run_ids, run_id_by_zp_id


def _insert_dataset_asset(
    session: Session,
    *,
    dataset_id: int,
    prepared: _PreparedZp,
    source_fingerprint: str | None,
    capabilities: dict[str, Any],
) -> None:
    json_fields = _asset_json_fields(session)
    session.execute(
        text(
            f"""
            INSERT INTO dataset_zp_assets (
                dataset_id, run_id, zp_path, format_version, source_fingerprint,
                output_sha256, status, capabilities, created_at, updated_at
            )
            VALUES (
                :dataset_id, NULL, :zp_path, :format_version, :source_fingerprint,
                :output_sha256, 'active', {json_fields["capabilities"]},
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        ),
        {
            "dataset_id": dataset_id,
            "zp_path": str(prepared.path),
            "format_version": prepared.format_version,
            "source_fingerprint": source_fingerprint,
            "output_sha256": prepared.output_sha256,
            "capabilities": _json(capabilities.get("binary_layer", {})),
        },
    )


def _reject_duplicate_fingerprint(session: Session, source_fingerprint: str | None) -> None:
    if source_fingerprint is None:
        return
    existing = session.execute(
        text(
            """
            SELECT 1 FROM datasets
            WHERE source_dataset_fingerprint = :fingerprint
              AND source_import_kind = 'AGENT_ZP'
            LIMIT 1
            """
        ),
        {"fingerprint": source_fingerprint.casefold()},
    ).first()
    if existing is not None:
        raise AgentZpError("AGENT_ZP_DATASET_FINGERPRINT_EXISTS", status_code=409)


def _existing_import_result(
    session: Session,
    *,
    body: AgentZpImportCreateIn,
    case_id: str,
    expected_sha256: str | None,
    source_fingerprint: str | None,
) -> AgentZpImportOut | None:
    if source_fingerprint is None or expected_sha256 is None:
        return None
    rows = session.execute(
        text(
            """
            SELECT d.dataset_id, d.slug, d.extra_metadata,
                   a.zp_path, a.output_sha256, a.format_version
            FROM datasets d
            JOIN dataset_zp_assets a ON a.dataset_id = d.dataset_id AND a.status = 'active'
            WHERE d.source_dataset_fingerprint = :fingerprint
              AND d.source_import_kind = 'AGENT_ZP'
              AND d.status = 'READY'
            """
        ),
        {"fingerprint": source_fingerprint.casefold()},
    ).mappings().all()
    for row in rows:
        extra = _object(row.get("extra_metadata"))
        agent = extra.get("agent_zp") if isinstance(extra.get("agent_zp"), dict) else {}
        if agent.get("case_id") != case_id or str(row["output_sha256"]).casefold() != expected_sha256.casefold():
            continue
        dataset_id = int(row["dataset_id"])
        run_ids = [
            int(item)
            for item in session.scalars(
                text("SELECT run_id FROM runs WHERE dataset_id = :dataset_id ORDER BY run_id"),
                {"dataset_id": dataset_id},
            ).all()
        ]
        zp_path = Path(str(row["zp_path"])).resolve(strict=True)
        revalidated = _validate_existing_zp(zp_path, case_id=f"{case_id}-reconcile")
        if revalidated.output_sha256.casefold() != expected_sha256.casefold():
            raise AgentZpError("AGENT_ZP_CANDIDATE_CHANGED", status_code=409)
        semantic = _semantic_dataset_or_none(zp_path)
        verification = _verify_dataset(
            session,
            dataset_id=dataset_id,
            run_ids=run_ids,
            validation_mode=str(agent.get("validation_mode") or "deep"),
            semantic=semantic,
        )
        capability_report = extra.get("dataset_capability_report")
        return AgentZpImportOut(
            case_id=case_id,
            status="success",
            binary_operation=body.binary_operation,
            analysis_category=body.analysis_category,
            source_profile=body.source_profile,
            dataset_id=dataset_id,
            dataset_slug=str(row["slug"]),
            run_ids=run_ids,
            zp_format_version=int(row["format_version"]),
            zp_output_sha256=str(row["output_sha256"]),
            validation_mode=str(agent.get("validation_mode") or "deep"),
            verification=verification,
            capability_report=(
                capability_report if isinstance(capability_report, dict) else None
            ),
        )
    return None


def _verify_dataset(
    session: Session,
    *,
    dataset_id: int,
    run_ids: list[int],
    validation_mode: str,
    semantic: SemanticDataset | None = None,
) -> AgentZpVerificationOut:
    verified_runs: list[AgentZpRunVerificationOut] = []
    for run_id in run_ids:
        try:
            index = load_scan_index(session, dataset_id, run_id)
        except ScanIndexError:
            continue
        if index.scan_count <= 0:
            continue
        scan_number = int(index.scan_number[0])
        try:
            spectrum, _path_committed = get_spectrum_by_scan(session, dataset_id, run_id, scan_number)
        except MzmlScanReaderError:
            continue
        mz = spectrum.get("mz")
        intensity = spectrum.get("intensity")
        if not isinstance(mz, list) or not isinstance(intensity, list) or not mz or not intensity:
            continue
        verified_runs.append(
            AgentZpRunVerificationOut(
                run_id=run_id,
                run_name=str(spectrum.get("native_id") or f"run_{run_id}"),
                scan_count=index.scan_count,
                sample_scan_number=scan_number,
                sample_peak_count=min(len(mz), len(intensity)),
            )
        )

    if not verified_runs and semantic is None:
        raise AgentZpError("AGENT_ZP_NO_READABLE_SCAN", status_code=422)
    if not verified_runs and semantic is not None:
        semantic_entities = (
            len(semantic.identifications)
            + len(semantic.peptides)
            + len(semantic.proteins)
            + len(semantic.protein_groups)
            + len(semantic.quantification)
        )
        if semantic_entities <= 0:
            raise AgentZpError("AGENT_ZP_NO_READABLE_SCAN", status_code=422)
        if any(
            item.spectrum_link_state in {"DIRECT", "DERIVED"}
            for item in semantic.identifications
        ):
            raise AgentZpError("AGENT_ZP_NO_READABLE_SCAN", status_code=422)
    if (
        semantic is not None
        and semantic.core_spectrum_count > 0
        and len(verified_runs) != len(run_ids)
    ):
        raise AgentZpError(
            "AGENT_ZP_NO_READABLE_SCAN",
            "Not every semantic ZP spectrum run passed the Viewer read probe.",
            status_code=422,
        )

    business_checks = (
        _verify_semantic_business_contract(session, dataset_id, semantic)
        if semantic is not None
        else {}
    )

    return AgentZpVerificationOut(
        validation_mode=validation_mode,
        scan_index_total=sum(item.scan_count for item in verified_runs),
        readable_run_count=len(verified_runs),
        runs=verified_runs,
        business_checks=business_checks,
    )


def _verify_semantic_business_contract(
    session: Session,
    dataset_id: int,
    semantic: SemanticDataset,
) -> dict[str, int | bool]:
    counts = {
        "proteins": int(
            session.scalar(
                text("SELECT count(*) FROM proteins WHERE dataset_id = :dataset_id"),
                {"dataset_id": dataset_id},
            )
            or 0
        ),
        "peptides": int(
            session.scalar(
                text("SELECT count(*) FROM peptides WHERE dataset_id = :dataset_id"),
                {"dataset_id": dataset_id},
            )
            or 0
        ),
        "matches": int(
            session.scalar(
                text("SELECT count(*) FROM identification_matches WHERE dataset_id = :dataset_id"),
                {"dataset_id": dataset_id},
            )
            or 0
        ),
    }
    expected = {
        "proteins": len(semantic.proteins),
        "peptides": len(semantic.peptides),
        "matches": len(semantic.identifications),
    }
    if counts != expected:
        raise AgentZpError(
            "AGENT_ZP_VALIDATION_FAILED",
            "Semantic ZP projection counts do not match Viewer business tables.",
            status_code=422,
        )
    dataset = dict(
        session.execute(
            text("SELECT * FROM datasets WHERE dataset_id = :dataset_id"),
            {"dataset_id": dataset_id},
        ).mappings().one()
    )
    available_views = _available_view_ids(dataset)
    unhandled_views = available_views - {
        "spectra",
        "bu.matches",
        "bu.peptides",
        "bu.proteins",
        "bu.protein_coverage",
        "chromatogram",
        "quantification",
    }
    if unhandled_views:
        raise AgentZpError(
            "AGENT_ZP_VALIDATION_FAILED",
            "No staging probe is registered for advertised views: "
            + ", ".join(sorted(unhandled_views)),
            status_code=422,
        )
    checks: dict[str, int | bool] = {
        **counts,
        "advertised_available_views": len(available_views),
        "match_detail_probe": False,
        "service_probes": False,
    }
    try:
        from app.bu.deps import require_bu_match
        from app.bu.services import lists_service

        match_detail = None
        if "bu.matches" in available_views:
            match_id = session.scalar(
                text(
                    "SELECT match_id FROM identification_matches "
                    "WHERE dataset_id = :dataset_id ORDER BY match_id LIMIT 1"
                ),
                {"dataset_id": dataset_id},
            )
            if match_id is None:
                raise ValueError("an advertised match route has no projected match")
            match = require_bu_match(session, dataset_id, int(match_id))
            match_detail = lists_service.get_match_detail(session, dataset, match)
            if match_detail.id != int(match_id):
                raise ValueError("Viewer match detail returned a different match")
            checks["match_detail_probe"] = True

        if "quantification" in available_views and match_detail is None:
            raise ValueError("an advertised quantification route has no readable match detail")

        if "chromatogram" in available_views:
            from app.bu.services.chromatogram_service import get_chromatogram

            run_id = session.scalar(
                text("SELECT run_id FROM runs WHERE dataset_id = :dataset_id ORDER BY run_id LIMIT 1"),
                {"dataset_id": dataset_id},
            )
            if run_id is None:
                raise ValueError("an advertised chromatogram route has no projected run")
            get_chromatogram(session, dataset, int(run_id), chrom_type="tic")

        if session.get_bind().dialect.name == "postgresql":
            _verify_postgres_bu_services(
                session,
                dataset,
                counts=counts,
                available_views=available_views,
            )
            checks["service_probes"] = True
    except AgentZpError:
        raise
    except Exception as exc:  # noqa: BLE001 - every advertised route must fail closed
        raise AgentZpError(
            "AGENT_ZP_VALIDATION_FAILED",
            "An advertised Viewer Bottom-Up route failed its staging probe.",
            status_code=422,
        ) from exc
    return checks


def _available_view_ids(dataset: dict[str, Any]) -> set[str]:
    extra = _object(dataset.get("extra_metadata"))
    report = extra.get("dataset_capability_report")
    views = report.get("views") if isinstance(report, dict) else None
    if not isinstance(views, list):
        raise AgentZpError(
            "AGENT_ZP_VALIDATION_FAILED",
            "Semantic dataset has no persisted capability report for staging probes.",
            status_code=422,
        )
    aliases = {
        "bu_matches": "bu.matches",
        "bu_peptides": "bu.peptides",
        "bu_proteins": "bu.proteins",
        "protein_coverage": "bu.protein_coverage",
    }
    available: set[str] = set()
    for item in views:
        if not isinstance(item, dict) or item.get("availability") != "AVAILABLE":
            continue
        view_id = item.get("view_id")
        if isinstance(view_id, str):
            available.add(aliases.get(view_id, view_id))
    return available


def _verify_postgres_bu_services(
    session: Session,
    dataset: dict[str, Any],
    *,
    counts: dict[str, int],
    available_views: set[str],
) -> None:
    from app.bu.services import lists_service
    from app.bu.services.overview_service import get_overview
    from app.bu.services.protein_detail_service import get_protein_detail

    get_overview(session, dataset)

    proteins = None
    if "bu.proteins" in available_views:
        proteins = lists_service.list_proteins(
            session,
            dataset,
            page=1,
            page_size=1,
            search=None,
            decoy=True,
        )
        if proteins.total != counts["proteins"]:
            raise ValueError("Viewer protein list disagrees with the staged projection")

    if "bu.peptides" in available_views:
        peptides = lists_service.list_peptides(
            session,
            dataset,
            page=1,
            page_size=1,
            search=None,
            q_max=None,
        )
        if peptides.total != counts["peptides"]:
            raise ValueError("Viewer peptide list disagrees with the staged projection")

    if "bu.matches" in available_views:
        matches = lists_service.list_matches(
            session,
            dataset,
            page=1,
            page_size=1,
            q_max=None,
            run_id=None,
            peptide_id=None,
            protein_id=None,
            charge=None,
            search=None,
            decoy=True,
            sort="q_value",
            order="asc",
        )
        if matches.total != counts["matches"]:
            raise ValueError("Viewer match list disagrees with the staged projection")

    if "bu.protein_coverage" in available_views:
        if proteins is None or not proteins.items:
            raise ValueError("an advertised protein coverage route has no protein")
        if get_protein_detail(session, dataset, proteins.items[0].id) is None:
            raise ValueError("Viewer protein detail could not read the staged protein")


def _analysis_mode(category: str) -> str:
    return "BOTTOM_UP" if category == "BOTTOM_UP" else "TOP_DOWN"


def _zp_capabilities(path: Path, semantic: SemanticDataset | None) -> dict[str, Any]:
    ensure_binary_layer_importable()
    from binary_layer import ZpReader  # type: ignore[import-not-found]

    reader = ZpReader(path)
    spectra = reader.read_spectra()
    chromatograms = reader.read_chromatograms()
    if semantic is None:
        return {
            "spectra_source": "zp",
            "analysis_shape": "zp_spectra_only",
            "import_mode": "agent_zp",
            "has_spectrum_files": bool(spectra),
            "has_chromatogram": bool(chromatograms),
            "has_identifications": False,
            "entity_types": [],
            "list_routes": [],
            "binary_layer": {"spectra": bool(spectra), "chromatograms": bool(chromatograms)},
        }
    has_protein_sequences = any(
        item.sequence and item.sequence_state in {"DIRECT", "DERIVED"}
        for item in semantic.proteins
    )
    list_routes = []
    if semantic.proteins:
        list_routes.append("proteins")
    if semantic.peptides:
        list_routes.append("peptides")
    if semantic.identifications:
        list_routes.append("matches")
    return {
        "spectra_source": "zp" if spectra else "none",
        "analysis_shape": "bottom_up_agent",
        "import_mode": "agent_declarative",
        "has_spectrum_files": bool(spectra),
        "has_chromatogram": bool(chromatograms) or bool(spectra),
        "has_identifications": bool(semantic.identifications),
        "has_peptides": bool(semantic.peptides),
        "has_proteins": bool(semantic.proteins),
        "has_protein_sequences": bool(has_protein_sequences),
        "has_quantification": any(item.value is not None for item in semantic.quantification),
        "has_modifications": bool(semantic.modifications),
        "has_fragment_annotations": False,
        "entity_types": ["PEPTIDE"] if semantic.peptides else [],
        "list_routes": list_routes,
        "binary_layer": {
            "spectra": bool(spectra),
            "chromatograms": bool(chromatograms),
            "semantic_dataset": True,
        },
    }


def _dataset_json_fields(session: Session) -> dict[str, str]:
    return {
        "capabilities": _json_sql(session, "capabilities"),
        "extra_metadata": _json_sql(session, "extra_metadata"),
    }


def _run_json_fields(session: Session) -> dict[str, str]:
    return {"run_metadata": _json_sql(session, "run_metadata")}


def _asset_json_fields(session: Session) -> dict[str, str]:
    return {"capabilities": _json_sql(session, "capabilities")}


def _json_sql(session: Session, name: str) -> str:
    return f"CAST(:{name} AS jsonb)" if _dialect_name(session) != "sqlite" else f":{name}"


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
