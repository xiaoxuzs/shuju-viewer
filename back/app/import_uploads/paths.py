"""Derive and validate paths confined to DATA_ROOT/.viewer-uploads."""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
from urllib.parse import unquote
from uuid import UUID

from app.core.config import settings
from app.import_uploads.errors import UploadError


def _storage_error() -> UploadError:
    return UploadError("UPLOAD_STORAGE_ERROR", "上传存储目录不可用。", 500)


def _not_found() -> UploadError:
    return UploadError("UPLOAD_NOT_FOUND", "上传会话不存在。", 404)


def _is_link_or_junction(path: Path) -> bool:
    try:
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
    except OSError:
        return True


def require_enabled() -> None:
    if not settings.import_upload_enabled:
        raise UploadError("UPLOAD_DISABLED", "本地上传功能已禁用。", 403)


def _validated_dir_name() -> str:
    name = settings.import_upload_dir_name.strip()
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or PureWindowsPath(name).drive
        or Path(name).is_absolute()
    ):
        raise _storage_error()
    return name


def upload_root(*, create: bool) -> Path:
    data_root = settings.resolved_data_root
    try:
        data_resolved = data_root.resolve(strict=True)
        if not data_resolved.is_dir():
            raise _storage_error()
        root = data_root / _validated_dir_name()
        if create:
            root.mkdir(exist_ok=True)
        if not root.exists():
            raise _not_found()
        if not root.is_dir() or _is_link_or_junction(root):
            raise _storage_error()
        resolved = root.resolve(strict=True)
        resolved.relative_to(data_resolved)
        if resolved == data_resolved:
            raise _storage_error()
        return resolved
    except UploadError:
        raise
    except (OSError, ValueError) as exc:
        raise _storage_error() from exc


def canonical_upload_id(upload_id: str) -> str:
    try:
        parsed = UUID(upload_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise _not_found() from exc
    canonical = str(parsed)
    if upload_id != canonical:
        raise _not_found()
    return canonical


def session_dir(upload_id: str) -> Path:
    canonical = canonical_upload_id(upload_id)
    try:
        root = upload_root(create=False)
    except UploadError as exc:
        if exc.code == "UPLOAD_NOT_FOUND":
            raise _not_found() from exc
        raise
    candidate = root / canonical
    if not candidate.exists():
        raise _not_found()
    try:
        if not candidate.is_dir() or _is_link_or_junction(candidate):
            raise _not_found()
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if resolved == root:
            raise _not_found()
        return resolved
    except UploadError:
        raise
    except (OSError, ValueError) as exc:
        raise _not_found() from exc


def files_dir(upload_id: str) -> Path:
    session = session_dir(upload_id)
    files = session / "files"
    try:
        if not files.is_dir() or _is_link_or_junction(files):
            raise _not_found()
        resolved = files.resolve(strict=True)
        resolved.relative_to(session)
        return resolved
    except UploadError:
        raise
    except (OSError, ValueError) as exc:
        raise _not_found() from exc


def validate_relative_path(files_root: Path, relative_path: str) -> tuple[str, Path]:
    value = relative_path
    if not value or not value.strip() or "\x00" in value:
        raise UploadError("UPLOAD_INVALID_PATH", "上传文件相对路径无效。", 400)
    if "\\" in value or value.startswith("/") or Path(value).is_absolute():
        raise UploadError("UPLOAD_INVALID_PATH", "上传文件相对路径无效。", 400)
    if unquote(value) != value:
        raise UploadError("UPLOAD_INVALID_PATH", "上传文件相对路径无效。", 400)
    windows_path = PureWindowsPath(value)
    if windows_path.drive or windows_path.root:
        raise UploadError("UPLOAD_INVALID_PATH", "上传文件相对路径无效。", 400)

    parts = value.split("/")
    if any(part in {"", ".", ".."} or ":" in part for part in parts):
        raise UploadError("UPLOAD_INVALID_PATH", "上传文件相对路径无效。", 400)
    if not parts[-1] or parts[-1].casefold().endswith(".part"):
        raise UploadError("UPLOAD_INVALID_PATH", "上传文件相对路径无效。", 400)

    try:
        root = files_root.resolve(strict=True)
        target = (root.joinpath(*parts)).resolve(strict=False)
        target.relative_to(root)
    except (OSError, ValueError) as exc:
        raise UploadError("UPLOAD_INVALID_PATH", "上传文件相对路径无效。", 400) from exc
    if target == root:
        raise UploadError("UPLOAD_INVALID_PATH", "上传文件相对路径无效。", 400)
    return "/".join(parts), target


def ensure_no_link_components(files_root: Path, target_parent: Path) -> None:
    root = files_root.resolve(strict=True)
    try:
        relative = target_parent.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise UploadError("UPLOAD_INVALID_PATH", "上传文件路径越过受管目录。", 400) from exc
    current = root
    for part in relative.parts:
        current = current / part
        if _is_link_or_junction(current):
            raise UploadError("UPLOAD_INVALID_PATH", "上传文件路径包含符号链接。", 400)


def scan_regular_files(root: Path) -> set[str]:
    found: set[str] = set()

    def _walk(directory: Path) -> None:
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if entry.is_symlink() or _is_link_or_junction(path):
                        raise UploadError("UPLOAD_INCOMPLETE", "上传目录包含不允许的符号链接。", 409)
                    if entry.is_dir(follow_symlinks=False):
                        _walk(path)
                    elif entry.is_file(follow_symlinks=False):
                        found.add(path.relative_to(root).as_posix())
                    else:
                        raise UploadError("UPLOAD_INCOMPLETE", "上传目录包含不支持的文件类型。", 409)
        except UploadError:
            raise
        except OSError as exc:
            raise UploadError("UPLOAD_INCOMPLETE", "无法安全检查上传目录。", 409) from exc

    _walk(root)
    return found
