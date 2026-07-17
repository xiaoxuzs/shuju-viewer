"""Atomic UTF-8 manifest persistence."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from pydantic import ValidationError

from app.import_uploads.errors import UploadError
from app.import_uploads.models import UploadManifest
from app.import_uploads.paths import _is_link_or_junction, session_dir


def manifest_path(upload_id: str) -> Path:
    return session_dir(upload_id) / "manifest.json"


def read_manifest(upload_id: str) -> UploadManifest:
    path = manifest_path(upload_id)
    try:
        if path.is_symlink() or _is_link_or_junction(path):
            raise OSError("unsafe manifest")
        raw = path.read_text(encoding="utf-8")
        manifest = UploadManifest.model_validate(json.loads(raw))
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise UploadError("UPLOAD_MANIFEST_INVALID", "上传清单损坏或不可用。", 409) from exc
    if manifest.upload_id != upload_id:
        raise UploadError("UPLOAD_MANIFEST_INVALID", "上传清单与会话不匹配。", 409)
    paths = [record.relative_path for record in manifest.files]
    manifest_size = sum(record.size_bytes for record in manifest.files)
    if len(paths) != len(set(paths)) or manifest.total_size_bytes != manifest_size:
        raise UploadError("UPLOAD_MANIFEST_INVALID", "上传清单内容不一致。", 409)
    return manifest


def write_manifest(path: Path, manifest: UploadManifest) -> None:
    payload = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
