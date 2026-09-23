"""Path resolution and storage boundaries for .zp conversion jobs."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from app.core.config import settings
from app.zp_conversion.contracts import ZpConversionError, ZpJobPaths


def resolve_source_path(source_path: str | Path) -> Path:
    text = str(source_path).strip()
    if not text:
        raise ZpConversionError("ZP_SOURCE_PATH_REQUIRED")
    try:
        path = Path(text).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ZpConversionError("ZP_SOURCE_NOT_FOUND") from exc
    if not path.is_file() and not path.is_dir():
        raise ZpConversionError("ZP_SOURCE_UNSUPPORTED_PATH_TYPE")
    allowed_roots = _existing_allowed_source_roots()
    if not any(_is_same_or_child(path, root) for root in allowed_roots):
        raise ZpConversionError("ZP_SOURCE_OUTSIDE_ALLOWED_ROOT")
    return path


def input_size_bytes(source: Path) -> int:
    if source.is_file():
        return source.stat().st_size
    total = 0
    stack = [source]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    return total


def prepare_job_paths(job_id: str) -> ZpJobPaths:
    safe_job_id = _uuid_text(job_id)
    output_root = settings.resolved_zp_output_root.resolve(strict=False)
    temp_root = settings.resolved_zp_temp_root.resolve(strict=False)
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        temp_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ZpConversionError("ZP_OUTPUT_ROOT_UNAVAILABLE") from exc
    if not _is_same_or_child(temp_root, output_root):
        raise ZpConversionError("ZP_OUTPUT_ROOT_UNAVAILABLE")

    temp_dir = temp_root / safe_job_id
    partial_path = temp_dir / "candidate.partial.zp"
    final_path = output_root / f"{safe_job_id}.zp"
    certificate_path = output_root / f"{safe_job_id}.deep-validation.json"
    for path in (temp_dir, final_path.parent, certificate_path.parent):
        if not _is_same_or_child(path.resolve(strict=False), output_root):
            raise ZpConversionError("ZP_OUTPUT_ROOT_UNAVAILABLE")
    if final_path.exists() or certificate_path.exists():
        raise ZpConversionError("ZP_FINAL_ALREADY_EXISTS")
    try:
        temp_dir.mkdir(parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise ZpConversionError("ZP_FINAL_ALREADY_EXISTS") from exc
    except OSError as exc:
        raise ZpConversionError("ZP_OUTPUT_ROOT_UNAVAILABLE") from exc
    return ZpJobPaths(
        temp_dir=temp_dir,
        partial_path=partial_path,
        final_path=final_path,
        certificate_path=certificate_path,
    )


def cleanup_job_paths(*, temp_dir: Path | None, partial_path: Path | None) -> None:
    output_root = settings.resolved_zp_output_root.resolve(strict=False)
    if partial_path is not None:
        candidate = partial_path.resolve(strict=False)
        if _is_same_or_child(candidate, output_root):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass
    if temp_dir is None:
        return
    resolved = temp_dir.resolve(strict=False)
    if resolved == output_root or not _is_same_or_child(resolved, output_root):
        return
    try:
        shutil.rmtree(resolved)
    except FileNotFoundError:
        return
    except OSError:
        return


def _existing_allowed_source_roots() -> list[Path]:
    roots: list[Path] = []
    for root in settings.zp_allowed_source_root_list:
        try:
            resolved = root.expanduser().resolve(strict=True)
        except OSError:
            continue
        if resolved.is_dir():
            roots.append(resolved)
    return roots


def _uuid_text(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise ZpConversionError("ZP_JOB_NOT_FOUND", status_code=404) from exc


def _is_same_or_child(path: Path, root: Path) -> bool:
    path_text = os.path.normcase(str(path.resolve(strict=False)))
    root_text = os.path.normcase(str(root.resolve(strict=False)))
    if path_text == root_text:
        return True
    root_with_sep = root_text.rstrip("\\/") + os.sep
    return path_text.startswith(root_with_sep)
