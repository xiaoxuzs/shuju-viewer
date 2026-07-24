from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette.routing import Match

from app.api.v1 import import_uploads as upload_api
from app.api.v1 import imports as imports_api
from app.core.config import settings
from app.import_uploads import dispatch, manifest as manifest_store, paths, service
from app.import_uploads.errors import UploadError
from app.import_uploads.models import (
    ImportType,
    ImportUploadCreateIn,
    UploadFileRecord,
    UploadManifest,
    UploadState,
)
from app.main import app
from app.schemas.imports import ImportEnqueueIn, ImportJobCreatedOut
from app.services import import_jobs
from app.services.import_planner.types import DatasetShape, ImportPlan


@pytest.fixture(autouse=True)
def isolated_upload_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "data_root", tmp_path)
    monkeypatch.setattr(settings, "import_upload_enabled", True)
    monkeypatch.setattr(settings, "import_upload_dir_name", ".viewer-uploads")
    monkeypatch.setattr(settings, "import_upload_disk_reserve_bytes", 0)
    monkeypatch.setattr(settings, "import_upload_max_file_bytes", 0)
    monkeypatch.setattr(settings, "import_upload_max_total_bytes", 0)
    monkeypatch.setattr(settings, "import_upload_max_files", 5000)
    monkeypatch.setattr(settings, "import_upload_chunk_bytes", 3)


async def _chunks(*values: bytes):
    for value in values:
        yield value


def _create(import_type: ImportType = ImportType.MZML_ONLY) -> str:
    return service.create_upload(import_type).upload_id


def _upload(
    upload_id: str,
    relative_path: str,
    data: bytes,
    *,
    declared: int | None = None,
    split: int | None = None,
):
    if split is None:
        chunks = (data,)
    else:
        chunks = tuple(data[offset : offset + split] for offset in range(0, len(data), split))
    header = str(len(data) if declared is None else declared)
    return asyncio.run(
        service.upload_file(
            upload_id=upload_id,
            relative_path=relative_path,
            content_length_header=header,
            chunks=_chunks(*chunks),
        )
    )


def _manifest(upload_id: str) -> UploadManifest:
    return manifest_store.read_manifest(upload_id)


def _manifest_file(upload_id: str) -> Path:
    return settings.resolved_data_root / ".viewer-uploads" / upload_id / "manifest.json"


def _files(upload_id: str) -> Path:
    return settings.resolved_data_root / ".viewer-uploads" / upload_id / "files"


def _set_started(upload_id: str) -> None:
    current = _manifest(upload_id)
    current.state = UploadState.STARTED
    current.job_id = str(uuid4())
    current.started_at = datetime.now(timezone.utc)
    manifest_store.write_manifest(_manifest_file(upload_id), current)


def _assert_code(exc: UploadError, code: str) -> None:
    assert exc.code == code


def test_create_session_builds_uuid_directory_and_manifest_without_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(import_jobs, "create_job", lambda **_kwargs: pytest.fail("must not create ImportJob"))
    created = service.create_upload(ImportType.MZML_ONLY)

    assert str(UUID(created.upload_id)) == created.upload_id
    assert created.state == UploadState.CREATED
    assert _files(created.upload_id).is_dir()
    data = json.loads(_manifest_file(created.upload_id).read_text(encoding="utf-8"))
    assert data == {
        "created_at": created.created_at.isoformat().replace("+00:00", "Z"),
        "files": [],
        "format_version": 1,
        "import_type": "MZML_ONLY",
        "job_id": None,
        "started_at": None,
        "state": "CREATED",
        "total_size_bytes": 0,
        "upload_id": created.upload_id,
    }
    assert str(settings.resolved_data_root) not in _manifest_file(created.upload_id).read_text(encoding="utf-8")


def test_create_session_disabled_returns_stable_error() -> None:
    settings.import_upload_enabled = False
    with pytest.raises(UploadError) as exc_info:
        service.create_upload(ImportType.MZML_ONLY)
    _assert_code(exc_info.value, "UPLOAD_DISABLED")
    assert not (settings.resolved_data_root / ".viewer-uploads").exists()


def test_api_error_contains_stable_code() -> None:
    settings.import_upload_enabled = False
    with pytest.raises(HTTPException) as exc_info:
        upload_api.create_import_upload(ImportUploadCreateIn(import_type=ImportType.MZML_ONLY))
    assert exc_info.value.detail == {"code": "UPLOAD_DISABLED", "message": "本地上传功能已禁用。"}


@pytest.mark.parametrize(
    "relative_path",
    [
        "../x",
        "/tmp/x",
        "C:/x",
        "C:\\x",
        "\\\\server\\share\\x",
        "folder\\x",
        "bad\x00name",
        "",
        ".",
        "folder//x",
        "%2e%2e/x",
        "unfinished.part",
    ],
)
def test_relative_path_rejects_traversal_absolute_windows_unc_backslash_nul_and_empty(
    relative_path: str,
) -> None:
    upload_id = _create()
    with pytest.raises(UploadError) as exc_info:
        paths.validate_relative_path(_files(upload_id), relative_path)
    _assert_code(exc_info.value, "UPLOAD_INVALID_PATH")


def test_relative_path_resolved_boundary_check_rejects_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    upload_id = _create()
    root = _files(upload_id).resolve()
    candidate = root / "folder" / "x.bin"
    outside = settings.resolved_data_root / "outside.bin"
    original_resolve = Path.resolve

    def fake_resolve(path: Path, strict: bool = False) -> Path:
        if path == candidate:
            return outside
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fake_resolve)
    with pytest.raises(UploadError) as exc_info:
        paths.validate_relative_path(root, "folder/x.bin")
    _assert_code(exc_info.value, "UPLOAD_INVALID_PATH")


def test_stream_upload_preserves_relative_tree_and_updates_manifest() -> None:
    upload_id = _create()
    result = _upload(upload_id, "folder/sample.mzML", b"abcdef", split=2)

    assert result.size_bytes == 6
    assert result.state == UploadState.READY
    assert (_files(upload_id) / "folder" / "sample.mzML").read_bytes() == b"abcdef"
    current = _manifest(upload_id)
    assert current.total_size_bytes == 6
    assert current.files == [
        UploadFileRecord(relative_path="folder/sample.mzML", size_bytes=6, completed=True)
    ]
    source = inspect.getsource(upload_api.put_import_upload_file)
    assert "request.stream()" in source
    assert "request.body()" not in source


def test_duplicate_completed_path_is_rejected_without_overwrite() -> None:
    upload_id = _create()
    _upload(upload_id, "x.mzML", b"first")
    with pytest.raises(UploadError) as exc_info:
        _upload(upload_id, "x.mzML", b"second")
    _assert_code(exc_info.value, "UPLOAD_DUPLICATE_FILE")
    assert (_files(upload_id) / "x.mzML").read_bytes() == b"first"


def test_existing_unrecorded_target_is_not_overwritten() -> None:
    upload_id = _create()
    target = _files(upload_id) / "x.mzML"
    target.write_bytes(b"existing")
    with pytest.raises(UploadError) as exc_info:
        _upload(upload_id, "x.mzML", b"new")
    _assert_code(exc_info.value, "UPLOAD_DUPLICATE_FILE")
    assert target.read_bytes() == b"existing"


def test_existing_part_rejects_concurrent_same_path() -> None:
    upload_id = _create()
    part = _files(upload_id) / "x.mzML.part"
    part.write_bytes(b"in progress")
    with pytest.raises(UploadError) as exc_info:
        _upload(upload_id, "x.mzML", b"new")
    _assert_code(exc_info.value, "UPLOAD_DUPLICATE_FILE")


def test_part_race_does_not_delete_another_writer_part(monkeypatch: pytest.MonkeyPatch) -> None:
    upload_id = _create()
    part = _files(upload_id) / "x.mzML.part"
    part.write_bytes(b"other writer")
    real_exists = Path.exists
    hidden_once = False

    def hide_part_once(path: Path) -> bool:
        nonlocal hidden_once
        if path == part and not hidden_once:
            hidden_once = True
            return False
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", hide_part_once)
    with pytest.raises(UploadError) as exc_info:
        _upload(upload_id, "x.mzML", b"new")
    _assert_code(exc_info.value, "UPLOAD_DUPLICATE_FILE")
    assert part.read_bytes() == b"other writer"


def test_target_race_does_not_overwrite_existing_file(monkeypatch: pytest.MonkeyPatch) -> None:
    upload_id = _create()
    target = _files(upload_id) / "x.mzML"
    real_exists = Path.exists
    target_checks = 0

    def create_target_during_finalize(path: Path) -> bool:
        nonlocal target_checks
        if path == target:
            target_checks += 1
            if target_checks == 2:
                target.write_bytes(b"other writer")
                return True
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", create_target_during_finalize)
    with pytest.raises(UploadError) as exc_info:
        _upload(upload_id, "x.mzML", b"new")
    _assert_code(exc_info.value, "UPLOAD_DUPLICATE_FILE")
    assert target.read_bytes() == b"other writer"
    assert not (_files(upload_id) / "x.mzML.part").exists()


def test_missing_content_length_is_rejected() -> None:
    upload_id = _create()
    with pytest.raises(UploadError) as exc_info:
        asyncio.run(
            service.upload_file(
                upload_id=upload_id,
                relative_path="x.mzML",
                content_length_header=None,
                chunks=_chunks(b"x"),
            )
        )
    _assert_code(exc_info.value, "UPLOAD_CONTENT_LENGTH_REQUIRED")


@pytest.mark.parametrize("declared,data", [(5, b"abc"), (2, b"abc")])
def test_content_length_mismatch_cleans_part_and_target(declared: int, data: bytes) -> None:
    upload_id = _create()
    with pytest.raises(UploadError) as exc_info:
        _upload(upload_id, "x.mzML", data, declared=declared, split=1)
    _assert_code(exc_info.value, "UPLOAD_SIZE_MISMATCH")
    assert not (_files(upload_id) / "x.mzML.part").exists()
    assert not (_files(upload_id) / "x.mzML").exists()
    assert _manifest(upload_id).files == []


def test_manifest_commit_failure_rolls_back_final_file(monkeypatch: pytest.MonkeyPatch) -> None:
    upload_id = _create()
    real_write = service.write_manifest

    def fail_ready_manifest(path: Path, current: UploadManifest) -> None:
        if current.state == UploadState.READY:
            raise OSError("simulated manifest failure")
        real_write(path, current)

    monkeypatch.setattr(service, "write_manifest", fail_ready_manifest)
    with pytest.raises(UploadError) as exc_info:
        _upload(upload_id, "x.mzML", b"x")
    _assert_code(exc_info.value, "UPLOAD_STORAGE_ERROR")
    assert not (_files(upload_id) / "x.mzML").exists()
    assert not (_files(upload_id) / "x.mzML.part").exists()
    assert _manifest(upload_id).files == []


def test_file_count_limit() -> None:
    settings.import_upload_max_files = 1
    upload_id = _create()
    _upload(upload_id, "one.mzML", b"1")
    with pytest.raises(UploadError) as exc_info:
        _upload(upload_id, "two.mzML", b"2")
    _assert_code(exc_info.value, "UPLOAD_TOO_MANY_FILES")


def test_single_file_size_limit() -> None:
    settings.import_upload_max_file_bytes = 2
    upload_id = _create()
    with pytest.raises(UploadError) as exc_info:
        _upload(upload_id, "x.mzML", b"123")
    _assert_code(exc_info.value, "UPLOAD_FILE_TOO_LARGE")


def test_total_size_limit_uses_manifest_total() -> None:
    settings.import_upload_max_total_bytes = 4
    upload_id = _create()
    _upload(upload_id, "one.mzML", b"12")
    with pytest.raises(UploadError) as exc_info:
        _upload(upload_id, "two.mzML", b"345")
    _assert_code(exc_info.value, "UPLOAD_TOTAL_TOO_LARGE")


def test_disk_reserve_gate_runs_before_part_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    settings.import_upload_disk_reserve_bytes = 10
    monkeypatch.setattr(service.shutil, "disk_usage", lambda _root: SimpleNamespace(free=12))
    upload_id = _create()
    with pytest.raises(UploadError) as exc_info:
        _upload(upload_id, "x.mzML", b"123")
    _assert_code(exc_info.value, "UPLOAD_DISK_SPACE_LOW")
    assert not (_files(upload_id) / "x.mzML.part").exists()
    assert _manifest(upload_id).files == []


def test_started_session_rejects_upload() -> None:
    upload_id = _create()
    _set_started(upload_id)
    with pytest.raises(UploadError) as exc_info:
        _upload(upload_id, "x.mzML", b"x")
    _assert_code(exc_info.value, "UPLOAD_ALREADY_STARTED")


def test_manifest_write_is_atomic_and_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    upload_id = _create()
    current = _manifest(upload_id)
    replacements: list[tuple[Path, Path]] = []
    real_replace = manifest_store.os.replace

    def recording_replace(source: Path, target: Path) -> None:
        replacements.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr(manifest_store.os, "replace", recording_replace)
    manifest_store.write_manifest(_manifest_file(upload_id), current)

    assert replacements
    assert replacements[-1][0].parent == replacements[-1][1].parent
    assert replacements[-1][1].name == "manifest.json"
    text = _manifest_file(upload_id).read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert list(json.loads(text)) == sorted(json.loads(text))


def test_corrupt_manifest_fails_closed() -> None:
    upload_id = _create()
    _manifest_file(upload_id).write_text("{broken", encoding="utf-8")
    with pytest.raises(UploadError) as exc_info:
        service.get_upload(upload_id)
    _assert_code(exc_info.value, "UPLOAD_MANIFEST_INVALID")


@pytest.mark.parametrize("upload_id", ["../escape", ".", str(uuid4()).upper(), "not-a-uuid"])
def test_upload_id_path_forgery_is_rejected(upload_id: str) -> None:
    with pytest.raises(UploadError) as exc_info:
        service.get_upload(upload_id)
    _assert_code(exc_info.value, "UPLOAD_NOT_FOUND")


def test_symlink_or_junction_component_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    upload_id = _create()
    real_check = paths._is_link_or_junction

    def fake_check(path: Path) -> bool:
        return path.name == "linked" or real_check(path)

    monkeypatch.setattr(paths, "_is_link_or_junction", fake_check)
    with pytest.raises(UploadError) as exc_info:
        _upload(upload_id, "linked/x.mzML", b"x")
    _assert_code(exc_info.value, "UPLOAD_INVALID_PATH")
    assert not (_files(upload_id) / "linked" / "x.mzML").exists()


def test_start_without_files_is_rejected() -> None:
    upload_id = _create()
    with pytest.raises(UploadError) as exc_info:
        service.start_upload(upload_id, parameters={"slug": "x", "name": "X"})
    _assert_code(exc_info.value, "UPLOAD_INCOMPLETE")


def test_start_rejects_part_file() -> None:
    upload_id = _create()
    _upload(upload_id, "x.mzML", b"x")
    (_files(upload_id) / "other.mzML.part").write_bytes(b"partial")
    with pytest.raises(UploadError) as exc_info:
        service.start_upload(upload_id, parameters={"slug": "x", "name": "X"})
    _assert_code(exc_info.value, "UPLOAD_INCOMPLETE")


def test_start_rejects_missing_file() -> None:
    upload_id = _create()
    _upload(upload_id, "x.mzML", b"x")
    (_files(upload_id) / "x.mzML").unlink()
    with pytest.raises(UploadError) as exc_info:
        service.start_upload(upload_id, parameters={"slug": "x", "name": "X"})
    _assert_code(exc_info.value, "UPLOAD_INCOMPLETE")


def test_start_rejects_size_mismatch() -> None:
    upload_id = _create()
    _upload(upload_id, "x.mzML", b"x")
    (_files(upload_id) / "x.mzML").write_bytes(b"changed")
    with pytest.raises(UploadError) as exc_info:
        service.start_upload(upload_id, parameters={"slug": "x", "name": "X"})
    _assert_code(exc_info.value, "UPLOAD_INCOMPLETE")


def test_start_rejects_unrecorded_regular_file() -> None:
    upload_id = _create()
    _upload(upload_id, "x.mzML", b"x")
    (_files(upload_id) / "extra.txt").write_bytes(b"extra")
    with pytest.raises(UploadError) as exc_info:
        service.start_upload(upload_id, parameters={"slug": "x", "name": "X"})
    _assert_code(exc_info.value, "UPLOAD_INCOMPLETE")


def test_start_rejects_client_source_path() -> None:
    upload_id = _create()
    _upload(upload_id, "x.mzML", b"x")
    with pytest.raises(UploadError) as exc_info:
        service.start_upload(
            upload_id,
            parameters={"slug": "x", "name": "X", "source_path": "C:/attacker"},
        )
    _assert_code(exc_info.value, "UPLOAD_INVALID_PATH")
    assert _manifest(upload_id).state == UploadState.FAILED
    assert _manifest(upload_id).job_id is None


def test_start_rejects_client_import_type_override() -> None:
    upload_id = _create(ImportType.DIA_CLIP)
    _upload(upload_id, "x.mzML", b"x")
    with pytest.raises(UploadError) as exc_info:
        service.start_upload(
            upload_id,
            parameters={"slug": "x", "name": "X", "import_type": "DIA_NN"},
        )
    _assert_code(exc_info.value, "UPLOAD_IMPORT_PARAMETERS_INVALID")
    assert _manifest(upload_id).state == UploadState.FAILED
    assert _manifest(upload_id).job_id is None


@pytest.mark.parametrize(
    ("import_type", "shape", "contains_raw"),
    [
        (ImportType.RAW_ONLY, DatasetShape.MZML_ONLY, True),
        (ImportType.MZML_ONLY, DatasetShape.MZML_ONLY, False),
        (ImportType.TOPPIC, DatasetShape.TOPPIC_HTML, False),
        (ImportType.PRSM, DatasetShape.PRSM_BUNDLE, False),
        (ImportType.DIA_NN, DatasetShape.DIANN_DIA, False),
        (ImportType.DIA_CLIP, DatasetShape.DIANN_DIA, False),
    ],
)
def test_six_import_types_dispatch_to_existing_job_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    import_type: ImportType,
    shape: DatasetShape,
    contains_raw: bool,
) -> None:
    calls: list[dict[str, Any]] = []
    validated: list[ImportType] = []
    monkeypatch.setattr(dispatch, "resolve_ingest_root", lambda root: root)
    monkeypatch.setattr(
        dispatch,
        "plan_zip_ingest",
        lambda _root: ImportPlan(
            shape=shape,
            spectra_source="mzml_memory",
            need_toppic_multirun_pass=False,
            contains_raw=contains_raw,
        ),
    )
    monkeypatch.setattr(
        dispatch,
        "validate_import_selection",
        lambda selected, _root, _plan: validated.append(selected),
    )

    def fake_enqueue(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(job_id="job-five")

    monkeypatch.setattr(import_jobs, "enqueue_path_import", fake_enqueue)
    result = dispatch.dispatch_import(
        import_type=import_type,
        source_path=tmp_path,
        parameters={"slug": "five", "name": "Five", "description": "test"},
    )

    assert result == ImportJobCreatedOut(job_id="job-five", status="queued")
    assert calls[0]["source_path"] == str(tmp_path.resolve())
    assert calls[0]["slug"] == "five"
    assert calls[0]["import_type"] == import_type.value
    assert validated == [import_type]


def test_dispatch_rejects_type_layout_mismatch_before_job_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(dispatch, "resolve_ingest_root", lambda root: root)
    monkeypatch.setattr(
        dispatch,
        "plan_zip_ingest",
        lambda _root: ImportPlan(
            shape=DatasetShape.DIANN_DIA,
            spectra_source="mzml_memory",
            need_toppic_multirun_pass=False,
        ),
    )
    monkeypatch.setattr(import_jobs, "enqueue_path_import", lambda **_kwargs: pytest.fail("must not enqueue"))
    with pytest.raises(UploadError) as exc_info:
        dispatch.dispatch_import(
            import_type=ImportType.TOPPIC,
            source_path=tmp_path,
            parameters={"slug": "x", "name": "X"},
        )
    _assert_code(exc_info.value, "UPLOAD_IMPORT_TYPE_UNSUPPORTED")


def test_start_success_records_job_and_rejects_repeat(monkeypatch: pytest.MonkeyPatch) -> None:
    upload_id = _create()
    _upload(upload_id, "x.mzML", b"x")
    seen: dict[str, Any] = {}

    def fake_dispatch(**kwargs: Any) -> ImportJobCreatedOut:
        seen.update(kwargs)
        return ImportJobCreatedOut(job_id="job-start", status="queued")

    monkeypatch.setattr(service, "dispatch_import", fake_dispatch)
    result = service.start_upload(upload_id, parameters={"slug": "x", "name": "X"})

    assert result.job_id == "job-start"
    current = _manifest(upload_id)
    assert current.state == UploadState.STARTED
    assert current.job_id == "job-start"
    assert current.started_at is not None
    assert seen["source_path"] == _files(upload_id).resolve()
    with pytest.raises(UploadError) as exc_info:
        service.start_upload(upload_id, parameters={"slug": "x", "name": "X"})
    _assert_code(exc_info.value, "UPLOAD_ALREADY_STARTED")


def test_dispatch_failure_never_writes_started(monkeypatch: pytest.MonkeyPatch) -> None:
    upload_id = _create()
    _upload(upload_id, "x.mzML", b"x")

    def fail_dispatch(**_kwargs: Any) -> ImportJobCreatedOut:
        raise UploadError("UPLOAD_IMPORT_TYPE_UNSUPPORTED", "bad", 400)

    monkeypatch.setattr(service, "dispatch_import", fail_dispatch)
    with pytest.raises(UploadError):
        service.start_upload(upload_id, parameters={"slug": "x", "name": "X"})
    current = _manifest(upload_id)
    assert current.state == UploadState.FAILED
    assert current.job_id is None
    assert current.started_at is None


def test_unexpected_dispatch_failure_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    upload_id = _create()
    _upload(upload_id, "x.mzML", b"x")

    def fail_dispatch(**_kwargs: Any) -> ImportJobCreatedOut:
        raise RuntimeError("database_url=secret")

    monkeypatch.setattr(service, "dispatch_import", fail_dispatch)
    with pytest.raises(UploadError) as exc_info:
        service.start_upload(upload_id, parameters={"slug": "x", "name": "X"})
    _assert_code(exc_info.value, "UPLOAD_IMPORT_FAILED")
    assert "secret" not in exc_info.value.message
    assert _manifest(upload_id).state == UploadState.FAILED


def test_delete_unstarted_session() -> None:
    upload_id = _create()
    _upload(upload_id, "x.mzML", b"x")
    session = _files(upload_id).parent
    service.delete_upload(upload_id)
    assert not session.exists()


def test_delete_started_session_is_rejected() -> None:
    upload_id = _create()
    _set_started(upload_id)
    with pytest.raises(UploadError) as exc_info:
        service.delete_upload(upload_id)
    _assert_code(exc_info.value, "UPLOAD_ALREADY_STARTED")
    assert _files(upload_id).parent.exists()


def test_delete_cannot_target_upload_root() -> None:
    _create()
    root = settings.resolved_data_root / ".viewer-uploads"
    with pytest.raises(UploadError):
        service.delete_upload(".")
    assert root.is_dir()


def test_delete_path_anomaly_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    upload_id = _create()
    session = _files(upload_id).parent.resolve()
    real_check = service._is_link_or_junction

    def fake_check(path: Path) -> bool:
        return path.resolve() == session or real_check(path)

    monkeypatch.setattr(service, "_is_link_or_junction", fake_check)
    with pytest.raises(UploadError) as exc_info:
        service.delete_upload(upload_id)
    _assert_code(exc_info.value, "UPLOAD_INVALID_PATH")
    assert session.exists()


def test_get_session_exposes_no_server_path() -> None:
    upload_id = _create(ImportType.TOPPIC)
    _upload(upload_id, "folder/x.mzML", b"x")
    payload = service.get_upload(upload_id).model_dump(mode="json")
    assert payload["file_count"] == 1
    assert payload["total_size_bytes"] == 1
    assert "source_path" not in payload
    assert str(settings.resolved_data_root) not in json.dumps(payload)


def _matched_route(path: str, method: str) -> str | None:
    scope = {"type": "http", "method": method, "path": path, "headers": []}
    for route in app.routes:
        match, _child = route.matches(scope)
        if match == Match.FULL:
            return route.name
    return None


def test_existing_server_path_api_still_uses_same_contract_and_shared_enqueue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "sample.mzML").write_bytes(b"mzml")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(imports_api, "resolve_ingest_root", lambda root: root)

    def fake_enqueue(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(job_id="server-path-job")

    monkeypatch.setattr(import_jobs, "enqueue_path_import", fake_enqueue)
    result = imports_api.enqueue_import(
        ImportEnqueueIn(source_path=str(tmp_path), slug="server", name="Server")
    )
    assert result.job_id == "server-path-job"
    assert calls[0]["source_path"] == str(tmp_path.resolve())
    assert calls[0]["import_type"] is None

    imports_api.enqueue_import(
        ImportEnqueueIn(
            source_path=str(tmp_path),
            slug="server-explicit",
            name="Server explicit",
            import_type=ImportType.MZML_ONLY,
        )
    )
    assert calls[1]["import_type"] == "MZML_ONLY"
    assert _matched_route("/api/v1/imports", "POST") == "enqueue_import"


def test_upload_routes_openapi_and_route_order_have_no_conflicts() -> None:
    schema = app.openapi()
    assert "/api/v1/import-uploads" in schema["paths"]
    assert "/api/v1/import-uploads/{upload_id}/files" in schema["paths"]
    assert "/api/v1/import-uploads/{upload_id}/start" in schema["paths"]
    assert "/api/v1/imports" in schema["paths"]
    assert _matched_route("/api/v1/import-uploads", "POST") == "create_import_upload"
    assert _matched_route(f"/api/v1/import-uploads/{uuid4()}/files", "PUT") == "put_import_upload_file"
    assert _matched_route(f"/api/v1/import-uploads/{uuid4()}/start", "POST") == "start_import_upload"
