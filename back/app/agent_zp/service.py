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
        _reject_duplicate_fingerprint(session, source_fingerprint)
        prepared = prepare_agent_zp_artifact(
            source_path=body.source_path,
            binary_operation=body.binary_operation,
            case_id=case_id,
            format_version=body.format_version,
        )
        if expected_sha256 is not None and prepared.output_sha256.casefold() != expected_sha256.casefold():
            raise AgentZpError("AGENT_ZP_CANDIDATE_CHANGED", status_code=409)
        runs = _read_zp_runs(prepared.path)
        dataset_id, run_ids = _insert_dataset_and_runs(
            session,
            body,
            prepared,
            runs,
            case_id=case_id,
            source_fingerprint=source_fingerprint,
        )
        verification = _verify_dataset(
            session,
            dataset_id=dataset_id,
            run_ids=run_ids,
            validation_mode=prepared.validation_mode,
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
    )


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


def _read_zp_runs(path: Path) -> list[_ZpRun]:
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
    if not runs:
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
) -> tuple[int, list[int]]:
    if body.replace_existing:
        session.execute(text("DELETE FROM datasets WHERE slug = :slug"), {"slug": body.slug})

    dataset_json = _dataset_json_fields(session)
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
            "capabilities": _json(
                {
                    "spectra_source": "zp",
                    "analysis_shape": "zp_spectra_only",
                    "import_mode": "agent_zp",
                    "has_spectrum_files": True,
                    "has_chromatogram": True,
                    "has_identifications": False,
                    "entity_types": [],
                    "list_routes": [],
                    "binary_layer": {"spectra": True},
                }
            ),
            "extra_metadata": _json(
                {
                    "agent_zp": {
                        "case_id": case_id,
                        "binary_operation": body.binary_operation,
                        "analysis_category": body.analysis_category,
                        "source_profile": body.source_profile,
                        "zp_format_version": prepared.format_version,
                        "zp_output_sha256": prepared.output_sha256,
                        "validation_mode": prepared.validation_mode,
                        "validation_certificate_name": (
                            prepared.certificate_path.name if prepared.certificate_path else None
                        ),
                    }
                }
            ),
        },
    ).one()
    dataset_id = int(dataset_row.dataset_id)
    run_ids = _insert_runs(session, dataset_id=dataset_id, body=body, runs=runs, prepared=prepared)
    _insert_dataset_asset(
        session,
        dataset_id=dataset_id,
        prepared=prepared,
        source_fingerprint=source_fingerprint,
    )
    return dataset_id, run_ids


def _insert_runs(
    session: Session,
    *,
    dataset_id: int,
    body: AgentZpImportCreateIn,
    runs: list[_ZpRun],
    prepared: _PreparedZp,
) -> list[int]:
    json_fields = _run_json_fields(session)
    run_ids: list[int] = []
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
        run_ids.append(int(run_row.run_id))
    return run_ids


def _insert_dataset_asset(
    session: Session,
    *,
    dataset_id: int,
    prepared: _PreparedZp,
    source_fingerprint: str | None,
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
            "capabilities": _json({"spectra": True}),
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


def _verify_dataset(
    session: Session,
    *,
    dataset_id: int,
    run_ids: list[int],
    validation_mode: str,
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

    if not verified_runs:
        raise AgentZpError("AGENT_ZP_NO_READABLE_SCAN", status_code=422)

    return AgentZpVerificationOut(
        validation_mode=validation_mode,
        scan_index_total=sum(item.scan_count for item in verified_runs),
        readable_run_count=len(verified_runs),
        runs=verified_runs,
    )


def _analysis_mode(category: str) -> str:
    return "BOTTOM_UP" if category == "BOTTOM_UP" else "TOP_DOWN"


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
