"""Case-root path resolution that rejects traversal through links or junctions."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path, PurePosixPath


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:/")


class SourcePathError(ValueError):
    """Raised when an inspection path is outside or unsafe for the Case root."""


def is_link_or_junction(path: Path) -> bool:
    try:
        stat_result = path.lstat()
    except OSError:
        raise
    attributes = getattr(stat_result, "st_file_attributes", 0)
    windows_reparse = bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(path))
    return path.is_symlink() or windows_reparse or is_junction


def entry_is_link_or_junction(entry: os.DirEntry[str]) -> bool:
    stat_result = entry.stat(follow_symlinks=False)
    attributes = getattr(stat_result, "st_file_attributes", 0)
    windows_reparse = bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(entry.path))
    return entry.is_symlink() or windows_reparse or is_junction


class CasePathResolver:
    """Resolve only existing paths under one immutable Case source root."""

    def __init__(self, case_root: str | Path) -> None:
        unresolved = Path(case_root).expanduser().absolute()
        try:
            if is_link_or_junction(unresolved):
                raise SourcePathError("Case source root may not be a link or junction")
            root = unresolved.resolve(strict=True)
        except OSError as exc:
            raise SourcePathError("Case source root does not exist") from exc
        if not root.is_dir():
            raise SourcePathError("Case source root must be a directory")
        self.root = root

    @staticmethod
    def normalize(relative_path: str, *, allow_root: bool = False) -> str:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise SourcePathError("relative_path must be a non-empty string")
        normalized = relative_path.strip().replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or _WINDOWS_DRIVE.match(normalized) or any(part == ".." for part in path.parts):
            raise SourcePathError("relative_path must stay inside the Case source root")
        result = path.as_posix()
        if result == "." and not allow_root:
            raise SourcePathError("relative_path must name a source entry")
        return result

    def _resolve(self, relative_path: str, *, allow_root: bool) -> Path:
        normalized = self.normalize(relative_path, allow_root=allow_root)
        if normalized == ".":
            return self.root
        current = self.root
        for part in PurePosixPath(normalized).parts:
            current = current / part
            try:
                current.lstat()
            except OSError as exc:
                raise SourcePathError(f"source path does not exist: {normalized}") from exc
            if is_link_or_junction(current):
                raise SourcePathError("source path may not traverse a link or junction")
        try:
            resolved = current.resolve(strict=True)
            resolved.relative_to(self.root)
        except (OSError, ValueError) as exc:
            raise SourcePathError("source path escaped the Case source root") from exc
        return resolved

    def resolve_file(self, relative_path: str) -> Path:
        path = self._resolve(relative_path, allow_root=False)
        if not path.is_file():
            raise SourcePathError("source path is not a regular file")
        return path

    def resolve_directory(self, relative_path: str = ".") -> Path:
        path = self._resolve(relative_path, allow_root=True)
        if not path.is_dir():
            raise SourcePathError("source path is not a directory")
        return path

    def relative(self, path: Path) -> str:
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise SourcePathError("source path escaped the Case source root") from exc
        return relative.as_posix() or "."
