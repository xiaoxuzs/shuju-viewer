"""Retained content-addressed source evidence, separate from metadata deduplication."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from app.agent_import.errors import AgentImportError
from app.agent_import.execution_control import checkpoint
from app.agent_import.source_code import canonical_bytes, digest_bytes, _linked
from app.core.config import settings


def source_files(root: Path) -> list[Path]:
    root = root.absolute()
    if _linked(root) or not root.is_dir():
        raise AgentImportError("AGENT_SOURCE_INVALID", "Source must be a regular non-linked directory.", status_code=422)
    for parent in root.parents:
        if _linked(parent):
            raise AgentImportError("AGENT_SOURCE_INVALID", "Linked source ancestors are forbidden.", status_code=422)
    found: list[Path] = []
    total = 0
    stack = [root]
    while stack:
        checkpoint()
        with os.scandir(stack.pop()) as entries:
            for entry in entries:
                path = Path(entry.path)
                if _linked(path):
                    raise AgentImportError("AGENT_SOURCE_INVALID", "Source links and junctions are forbidden.", status_code=422)
                lower = entry.name.casefold()
                if lower.startswith(".env") or lower in {".git", "credentials", "id_rsa", "id_ed25519"} or path.suffix.lower() in {".pem", ".key", ".pfx"}:
                    raise AgentImportError("AGENT_SOURCE_SECRET_PATH", "Source includes a protected credential path.", status_code=422)
                if entry.is_dir(follow_symlinks=False):
                    stack.append(path)
                elif entry.is_file(follow_symlinks=False):
                    size = entry.stat(follow_symlinks=False).st_size
                    total += size
                    found.append(path)
                    if len(found) > settings.import_upload_max_files or total > settings.agent_source_max_bytes:
                        raise AgentImportError("AGENT_SOURCE_QUOTA", "Source snapshot quota exceeded.", status_code=413)
                    if settings.import_upload_max_file_bytes and size > settings.import_upload_max_file_bytes:
                        raise AgentImportError("AGENT_SOURCE_QUOTA", "Source file quota exceeded.", status_code=413)
                else:
                    raise AgentImportError("AGENT_SOURCE_INVALID", "Non-regular source entry.", status_code=422)
    return sorted(found)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            checkpoint()
            digest.update(block)
    return digest.hexdigest()


def content_manifest(root: Path) -> dict:
    root = root.absolute()
    files = {}
    for path in source_files(root):
        before = path.stat()
        sha256 = hash_file(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise AgentImportError("SOURCE_CHANGED", "Source changed while hashing.", status_code=409)
        files[path.relative_to(root).as_posix()] = {"sha256": sha256, "size": after.st_size}
    return {"schema_version": 1, "files": files, "sha256": digest_bytes(canonical_bytes(files))}


def freeze_source(root: Path, destination: Path) -> dict:
    if destination.resolve(strict=False).is_relative_to(root.resolve(strict=True)):
        raise AgentImportError("AGENT_SOURCE_INVALID", "Retained output must not be created inside the submitted source tree.", status_code=422)
    expected = content_manifest(root)
    if destination.exists():
        manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
        if manifest != expected or content_manifest(destination / "files") != expected:
            raise AgentImportError("SOURCE_CHANGED", "Retained source identity changed.", status_code=409)
        return manifest
    destination.mkdir(parents=True)
    files_root = destination / "files"
    files_root.mkdir()
    # Leave incomplete snapshots for explicit reconciliation, never report them complete.
    for relative, entry in expected["files"].items():
        checkpoint()
        target = files_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, target, follow_symlinks=False)
        if hash_file(target) != entry["sha256"]:
            raise AgentImportError("SOURCE_CHANGED", "Source changed while retaining assets.", status_code=409)
    if content_manifest(root) != expected or content_manifest(files_root) != expected:
        raise AgentImportError("SOURCE_CHANGED", "Source changed while retaining assets.", status_code=409)
    with (destination / "manifest.json").open("xb") as stream:
        stream.write(canonical_bytes(expected))
    return expected


def retained_asset_catalog(case) -> list[dict]:
    manifest = (case.strategy_payload or {}).get("input_snapshot")
    if not manifest:
        return []
    return [{"asset_id": digest_bytes(relative.encode("utf-8")), "relative_path": relative,
             "sha256": entry["sha256"], "size_bytes": entry["size"]}
            for relative, entry in manifest["files"].items()]


def retained_asset_path(case, asset_id: str) -> Path:
    entry = next((item for item in retained_asset_catalog(case) if item["asset_id"] == asset_id), None)
    if entry is None:
        raise AgentImportError("AGENT_ASSET_NOT_FOUND", "Retained asset not found.", status_code=404)
    from app.agent_import.source_sampling import _safe_sample_path
    root = settings.resolved_zp_output_root / "agent-cases" / case.case_id / "source" / "files"
    path = _safe_sample_path(root, entry["relative_path"])
    if path.stat().st_size != entry["size_bytes"] or hash_file(path) != entry["sha256"]:
        raise AgentImportError("SOURCE_CHANGED", "Retained asset failed its content identity check.", status_code=409)
    return path
