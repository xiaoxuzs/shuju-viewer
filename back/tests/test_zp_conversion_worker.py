from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from starlette.routing import Match

from app.api.v1 import zp_conversions as api
from app.core.config import settings
from app.core.db import engine
from app.main import app
from app.schemas.zp_conversions import ZpConversionCreateIn
from app.zp_conversion import repository, service
from app.zp_conversion.contracts import ZpConversionError, ZpConversionJob
from app.zp_conversion.worker_runner import WorkerRequest, WorkerResult


@pytest.fixture(autouse=True)
def isolated_zp_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    monkeypatch.setattr(settings, "data_root", data_root)
    monkeypatch.setattr(settings, "zp_output_root", tmp_path / "zp-output")
    monkeypatch.setattr(settings, "zp_temp_root", Path(".tmp"))
    monkeypatch.setattr(settings, "zp_allowed_source_roots", "")
    monkeypatch.setattr(settings, "zp_worker_python", None)
    monkeypatch.setattr(settings, "zp_worker_pythonpath", "")
    monkeypatch.setattr(settings, "zp_default_format_version", 1)
    monkeypatch.setattr(settings, "zp_conversion_timeout_seconds", 60)
    monkeypatch.setattr(settings, "zp_conversion_worker_threads", 2)
    monkeypatch.setattr(settings, "zp_binary_layer_commit", "test-commit")
    repository.ensure_zp_conversion_schema()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM dataset_zp_assets"))
        conn.execute(text("DELETE FROM zp_conversion_jobs"))


def test_enqueue_rejects_source_outside_allowed_roots(tmp_path: Path) -> None:
    outside = tmp_path / "outside.mzML"
    outside.write_text("<mzML />", encoding="utf-8")

    with pytest.raises(ZpConversionError) as exc_info:
        service.enqueue_conversion(source_path=outside, start_background=False)

    assert exc_info.value.code == "ZP_SOURCE_OUTSIDE_ALLOWED_ROOT"


def test_enqueue_creates_job_paths_under_output_root_without_starting_worker() -> None:
    source = settings.resolved_data_root / "sample.mzML"
    source.write_bytes(b"mzml")

    job = service.enqueue_conversion(
        source_path=source,
        dataset_slug="sample-dataset",
        start_background=False,
    )

    assert job.status == "queued"
    assert job.stage == "queued"
    assert job.input_bytes == 4
    assert job.dataset_slug == "sample-dataset"
    assert job.zp_final_path is not None
    assert str(job.zp_final_path).startswith(str(settings.resolved_zp_output_root))
    assert job.zp_temp_path is not None
    assert job.zp_temp_path.parent.is_dir()


def test_run_conversion_with_injected_runner_marks_success_and_cleans_temp() -> None:
    source = settings.resolved_data_root / "sample.mzML"
    source.write_bytes(b"mzml")
    queued = service.enqueue_conversion(source_path=source, dataset_slug="sample-dataset", start_background=False)
    progress: list[tuple[str, float]] = []

    class SuccessfulRunner:
        def run(self, request: WorkerRequest, report_progress):  # type: ignore[no-untyped-def]
            report_progress("convert", 50.0, None)
            progress.append(("convert", 50.0))
            payload = b"fake-zp-artifact"
            request.final_path.write_bytes(payload)
            request.certificate_path.write_text('{"valid": true}', encoding="utf-8")
            return WorkerResult(
                output_bytes=len(payload),
                output_sha256=hashlib.sha256(payload).hexdigest(),
                validation_mode="deep",
                validation_certificate_path=request.certificate_path,
                format_version=request.format_version,
                viewer_two_version="test-commit",
            )

    finished = service.run_conversion_job(queued.job_id, runner=SuccessfulRunner())

    assert finished is not None
    assert finished.status == "success"
    assert finished.progress == 100.0
    assert finished.output_sha256 == hashlib.sha256(b"fake-zp-artifact").hexdigest()
    assert finished.validation_mode == "deep"
    assert progress == [("convert", 50.0)]
    assert finished.zp_temp_path is not None
    assert not finished.zp_temp_path.parent.exists()
    assert finished.zp_final_path is not None
    assert finished.zp_final_path.read_bytes() == b"fake-zp-artifact"


def test_default_unconfigured_worker_fails_closed_without_exposing_paths() -> None:
    source = settings.resolved_data_root / "sample.mzML"
    source.write_bytes(b"mzml")
    queued = service.enqueue_conversion(source_path=source, start_background=False)

    failed = service.run_conversion_job(queued.job_id)

    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_code == "ZP_WORKER_NOT_CONFIGURED"
    out = api._job_out(failed).model_dump(mode="json")
    assert out["error_message"] == "ZP worker is not configured on this server."
    assert str(settings.resolved_data_root) not in json.dumps(out)
    assert str(settings.resolved_zp_output_root) not in json.dumps(out)


def test_cancel_queued_job_cleans_temporary_directory() -> None:
    source = settings.resolved_data_root / "sample.mzML"
    source.write_bytes(b"mzml")
    queued = service.enqueue_conversion(source_path=source, start_background=False)
    assert queued.zp_temp_path is not None
    assert queued.zp_temp_path.parent.is_dir()

    cancelled = service.cancel_conversion(queued.job_id)

    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert not queued.zp_temp_path.parent.exists()


def test_api_maps_path_errors_to_stable_code_without_absolute_path(tmp_path: Path) -> None:
    outside = tmp_path / "outside.mzML"
    outside.write_text("<mzML />", encoding="utf-8")

    with pytest.raises(HTTPException) as exc_info:
        api.create_zp_conversion(ZpConversionCreateIn(source_path=str(outside)))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "ZP_SOURCE_OUTSIDE_ALLOWED_ROOT"
    assert str(outside) not in json.dumps(exc_info.value.detail)


def test_api_job_response_does_not_return_internal_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_job = ZpConversionJob(
        job_id="1cfca367-62b3-4721-bb11-d3acaa2bd117",
        status="queued",
        stage="queued",
        progress=0.0,
        dataset_slug="dataset-one",
        input_root=tmp_path / "data" / "secret.mzML",
        zp_temp_path=tmp_path / "zp" / ".tmp" / "secret.partial.zp",
        zp_final_path=tmp_path / "zp" / "secret.zp",
        format_version=1,
    )
    monkeypatch.setattr(api, "enqueue_conversion", lambda **_kwargs: fake_job)

    out = api.create_zp_conversion(
        ZpConversionCreateIn(source_path=str(fake_job.input_root), dataset_slug="dataset-one")
    )

    payload = out.model_dump(mode="json")
    assert payload == {"job_id": fake_job.job_id, "status": "queued"}
    assert str(tmp_path) not in json.dumps(payload)


def _matched_route(path: str, method: str) -> str | None:
    scope = {"type": "http", "method": method, "path": path, "headers": []}
    for route in app.routes:
        match, _child = route.matches(scope)
        if match == Match.FULL:
            return route.name
    return None


def test_zp_routes_are_registered_without_shadowing_import_routes() -> None:
    schema = app.openapi()
    assert "/api/v1/zp-conversions" in schema["paths"]
    assert "/api/v1/zp-conversions/{job_id}" in schema["paths"]
    assert "/api/v1/zp-conversions/{job_id}/cancel" in schema["paths"]
    assert "/api/v1/datasets/{dataset_id}/zp-status" in schema["paths"]
    assert _matched_route("/api/v1/zp-conversions", "POST") == "create_zp_conversion"
    assert _matched_route("/api/v1/imports", "POST") == "enqueue_import"
