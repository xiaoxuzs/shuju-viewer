"""Managed upload-session orchestration and filesystem validation."""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import AsyncIterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.import_uploads.dispatch import dispatch_import
from app.import_uploads.errors import UploadError
from app.import_uploads.manifest import manifest_path, read_manifest, write_manifest
from app.import_uploads.models import (
    ImportType,
    ImportUploadCreatedOut,
    ImportUploadFileOut,
    ImportUploadSessionOut,
    UploadFileRecord,
    UploadManifest,
    UploadState,
)
from app.import_uploads.paths import (
    _is_link_or_junction,
    ensure_no_link_components,
    files_dir,
    require_enabled,
    scan_regular_files,
    session_dir,
    upload_root,
    validate_relative_path,
)
from app.schemas.imports import ImportJobCreatedOut


def _storage_error() -> UploadError:
    return UploadError("UPLOAD_STORAGE_ERROR", "上传存储操作失败。", 500)


def _session_summary(manifest: UploadManifest) -> ImportUploadSessionOut:
    return ImportUploadSessionOut(
        upload_id=manifest.upload_id,
        import_type=manifest.import_type,
        state=manifest.state,
        file_count=len(manifest.files),
        total_size_bytes=manifest.total_size_bytes,
        job_id=manifest.job_id,
        created_at=manifest.created_at,
        started_at=manifest.started_at,
    )


def create_upload(import_type: ImportType) -> ImportUploadCreatedOut:
    require_enabled()
    root = upload_root(create=True)
    upload_id = str(uuid.uuid4())
    session = root / upload_id
    try:
        session.mkdir()
        (session / "files").mkdir()
        now = datetime.now(timezone.utc)
        manifest = UploadManifest(
            upload_id=upload_id,
            import_type=import_type,
            state=UploadState.CREATED,
            created_at=now,
        )
        write_manifest(session / "manifest.json", manifest)
    except Exception as exc:
        try:
            if session.exists() and not _is_link_or_junction(session):
                shutil.rmtree(session)
        except OSError:
            pass
        if isinstance(exc, UploadError):
            raise
        raise _storage_error() from exc
    return ImportUploadCreatedOut(
        upload_id=upload_id,
        import_type=import_type,
        state=UploadState.CREATED,
        created_at=now,
    )


def get_upload(upload_id: str) -> ImportUploadSessionOut:
    require_enabled()
    return _session_summary(read_manifest(upload_id))


def _parse_content_length(raw: str | None) -> int:
    if raw is None or not raw.strip():
        raise UploadError("UPLOAD_CONTENT_LENGTH_REQUIRED", "上传文件必须提供 Content-Length。", 411)
    try:
        value = int(raw)
    except ValueError as exc:
        raise UploadError("UPLOAD_CONTENT_LENGTH_REQUIRED", "Content-Length 必须是非负整数。", 411) from exc
    if value < 0:
        raise UploadError("UPLOAD_CONTENT_LENGTH_REQUIRED", "Content-Length 必须是非负整数。", 411)
    return value


def _check_upload_limits(manifest: UploadManifest, content_length: int) -> None:
    if len(manifest.files) + 1 > settings.import_upload_max_files:
        raise UploadError("UPLOAD_TOO_MANY_FILES", "上传文件数量超过限制。", 413)
    if settings.import_upload_max_file_bytes and content_length > settings.import_upload_max_file_bytes:
        raise UploadError("UPLOAD_FILE_TOO_LARGE", "上传文件大小超过限制。", 413)
    predicted_total = manifest.total_size_bytes + content_length
    if settings.import_upload_max_total_bytes and predicted_total > settings.import_upload_max_total_bytes:
        raise UploadError("UPLOAD_TOTAL_TOO_LARGE", "上传总大小超过限制。", 413)


def _check_disk_space(root: Path, content_length: int) -> None:
    try:
        free = shutil.disk_usage(root).free
    except OSError as exc:
        raise _storage_error() from exc
    if free < content_length + settings.import_upload_disk_reserve_bytes:
        raise UploadError("UPLOAD_DISK_SPACE_LOW", "磁盘可用空间不足，无法安全上传。", 507)


async def upload_file(
    *,
    upload_id: str,
    relative_path: str,
    content_length_header: str | None,
    chunks: AsyncIterable[bytes],
) -> ImportUploadFileOut:
    require_enabled()
    content_length = _parse_content_length(content_length_header)
    manifest = read_manifest(upload_id)
    if manifest.state == UploadState.STARTED:
        raise UploadError("UPLOAD_ALREADY_STARTED", "上传会话已经开始导入。", 409)
    if manifest.state not in {UploadState.CREATED, UploadState.UPLOADING, UploadState.READY}:
        raise UploadError("UPLOAD_INVALID_STATE", "当前上传会话状态不允许继续上传。", 409)

    root = files_dir(upload_id)
    normalized, target = validate_relative_path(root, relative_path)
    if any(record.relative_path == normalized for record in manifest.files):
        raise UploadError("UPLOAD_DUPLICATE_FILE", "同一路径的文件已上传完成。", 409)
    part = target.with_name(target.name + ".part")
    if target.exists() or target.is_symlink():
        raise UploadError("UPLOAD_DUPLICATE_FILE", "目标文件已存在，禁止覆盖。", 409)
    if part.exists() or part.is_symlink():
        raise UploadError("UPLOAD_DUPLICATE_FILE", "同一路径正在上传，禁止并发写入。", 409)

    _check_upload_limits(manifest, content_length)
    _check_disk_space(upload_root(create=False), content_length)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        ensure_no_link_components(root, target.parent)
    except UploadError:
        raise
    except OSError as exc:
        raise _storage_error() from exc

    manifest.state = UploadState.UPLOADING
    try:
        write_manifest(manifest_path(upload_id), manifest)
    except Exception as exc:
        raise _storage_error() from exc

    written = 0
    part_owned = False
    target_owned = False
    try:
        handle = part.open("xb")
        part_owned = True
        with handle:
            async for chunk in chunks:
                if not chunk:
                    continue
                if written + len(chunk) > content_length:
                    raise UploadError("UPLOAD_SIZE_MISMATCH", "实际上传大小与 Content-Length 不一致。", 400)
                view = memoryview(chunk)
                step = settings.import_upload_chunk_bytes
                for offset in range(0, len(view), step):
                    piece = view[offset : offset + step]
                    handle.write(piece)
                    written += len(piece)
            handle.flush()
            os.fsync(handle.fileno())
        if written != content_length:
            raise UploadError("UPLOAD_SIZE_MISMATCH", "实际上传大小与 Content-Length 不一致。", 400)
        if target.exists() or target.is_symlink():
            raise UploadError("UPLOAD_DUPLICATE_FILE", "目标文件已存在，禁止覆盖。", 409)
        try:
            reservation = target.open("xb")
            target_owned = True
            reservation.close()
        except FileExistsError as exc:
            raise UploadError("UPLOAD_DUPLICATE_FILE", "目标文件已存在，禁止覆盖。", 409) from exc
        os.replace(part, target)
        part_owned = False
        manifest.files.append(
            UploadFileRecord(relative_path=normalized, size_bytes=written, completed=True)
        )
        manifest.total_size_bytes += written
        manifest.state = UploadState.READY
        write_manifest(manifest_path(upload_id), manifest)
    except UploadError:
        try:
            if part_owned:
                part.unlink(missing_ok=True)
            if target_owned:
                target.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except FileExistsError as exc:
        raise UploadError("UPLOAD_DUPLICATE_FILE", "同一路径正在上传，禁止并发写入。", 409) from exc
    except Exception as exc:
        try:
            if part_owned:
                part.unlink(missing_ok=True)
            if target_owned:
                target.unlink(missing_ok=True)
        except OSError:
            pass
        raise _storage_error() from exc

    return ImportUploadFileOut(
        upload_id=upload_id,
        relative_path=normalized,
        size_bytes=written,
        state=manifest.state,
        total_size_bytes=manifest.total_size_bytes,
        file_count=len(manifest.files),
    )


def _validate_ready_files(upload_id: str, manifest: UploadManifest) -> Path:
    if not manifest.files:
        raise UploadError("UPLOAD_INCOMPLETE", "上传会话中没有已完成文件。", 409)
    root = files_dir(upload_id)
    for record in manifest.files:
        normalized, _target = validate_relative_path(root, record.relative_path)
        if normalized != record.relative_path:
            raise UploadError("UPLOAD_INCOMPLETE", "上传清单中的文件路径无效。", 409)
    actual = scan_regular_files(root)
    if any(path.casefold().endswith(".part") for path in actual):
        raise UploadError("UPLOAD_INCOMPLETE", "上传目录中仍有未完成文件。", 409)
    expected = {record.relative_path for record in manifest.files}
    if actual != expected:
        raise UploadError("UPLOAD_INCOMPLETE", "上传目录内容与清单不一致。", 409)
    for record in manifest.files:
        target = root.joinpath(*record.relative_path.split("/"))
        try:
            if not target.is_file() or target.stat().st_size != record.size_bytes:
                raise UploadError("UPLOAD_INCOMPLETE", "上传文件缺失或大小不一致。", 409)
            target.resolve(strict=True).relative_to(root)
        except UploadError:
            raise
        except (OSError, ValueError) as exc:
            raise UploadError("UPLOAD_INCOMPLETE", "上传文件无法安全验证。", 409) from exc
    return root


def start_upload(
    upload_id: str,
    *,
    parameters: dict[str, Any],
) -> ImportJobCreatedOut:
    require_enabled()
    manifest = read_manifest(upload_id)
    if manifest.state == UploadState.STARTED or manifest.job_id is not None:
        raise UploadError("UPLOAD_ALREADY_STARTED", "上传会话已经开始导入。", 409)
    if manifest.state not in {UploadState.CREATED, UploadState.UPLOADING, UploadState.READY}:
        raise UploadError("UPLOAD_INVALID_STATE", "当前上传会话状态不允许开始导入。", 409)
    root = _validate_ready_files(upload_id, manifest)
    try:
        result = dispatch_import(
            import_type=manifest.import_type,
            source_path=root,
            parameters=parameters,
        )
    except Exception as exc:
        manifest.state = UploadState.FAILED
        try:
            write_manifest(manifest_path(upload_id), manifest)
        except Exception:
            pass
        if isinstance(exc, UploadError):
            raise
        raise UploadError("UPLOAD_IMPORT_FAILED", "启动导入失败。", 500) from exc

    manifest.state = UploadState.STARTED
    manifest.job_id = result.job_id
    manifest.started_at = datetime.now(timezone.utc)
    try:
        write_manifest(manifest_path(upload_id), manifest)
    except Exception as exc:
        raise _storage_error() from exc
    return result


def delete_upload(upload_id: str) -> None:
    require_enabled()
    manifest = read_manifest(upload_id)
    if manifest.state == UploadState.STARTED or manifest.job_id is not None:
        raise UploadError("UPLOAD_ALREADY_STARTED", "已开始导入的上传会话不能删除。", 409)
    session = session_dir(upload_id)
    root = upload_root(create=False)
    try:
        resolved = session.resolve(strict=True)
        resolved.relative_to(root)
        if resolved == root or resolved.parent != root or _is_link_or_junction(session):
            raise UploadError("UPLOAD_INVALID_PATH", "上传会话目录不安全，拒绝删除。", 409)
        scan_regular_files(session)
        shutil.rmtree(resolved)
    except UploadError:
        raise
    except (OSError, ValueError) as exc:
        raise UploadError("UPLOAD_INVALID_PATH", "上传会话目录不安全，拒绝删除。", 409) from exc
