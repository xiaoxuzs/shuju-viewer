"""Bounded, immutable working-copy evidence; never reads Git objects or dotenv.

This is an evidence/snapshot utility, NOT an execution sandbox. Generated code
must not be run merely because it is contained in one of these snapshots.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


_TREES = ("back/app", "back/vendor/zp_engine", "back/tests", "front/src", "front/tests", "front/verification")
_FILES = frozenset({
    "back/pyproject.toml", "back/uv.lock", "front/package.json", "front/pnpm-lock.yaml",
    "front/index.html", "front/vite.config.ts", "front/tsconfig.json", "front/tsconfig.app.json",
    "front/tsconfig.node.json", "front/tailwind.config.ts", "front/postcss.config.js",
    "front/playwright.config.ts", "docs/universal_schema.sql",
    "front/playwright.local-regression.config.ts", "front/vite.regression.config.ts",
    "back/config/agent-gpt-local.json",
})
_SUFFIXES = frozenset({".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".css", ".cpp", ".h", ".sql"})
_EXCLUDED = frozenset({"__pycache__", "node_modules", "resources", "bin", "dist", "test-results"})
_SENSITIVE = re.compile(r'''(?i)password|api[_-]?key|secret|authorization|bearer\s|cookie|token\s*["']?\s*[:=]|sk-[a-z0-9_-]{16,}|gh[pousr]_[a-z0-9]{20,}|AKIA[0-9A-Z]{16}|://[^\s/]+:[^\s/]+@|[a-z]:[\\/]|/home/|/Users/''')
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 96 * 1024 * 1024


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("A canonical relative path is required")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(
        part in {".", ".."} or part.startswith(".") or part.endswith((".", " ")) for part in path.parts
    ):
        raise ValueError("Path is outside the source policy")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("Control characters are forbidden")
    return value


def _linked(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def permitted_source_path(value: str) -> bool:
    safe_relative(value)
    path = PurePosixPath(value)
    if any(part in _EXCLUDED or part.casefold().startswith(".env") for part in path.parts):
        return False
    return value in _FILES or (
        any(value.startswith(prefix + "/") for prefix in _TREES) and path.suffix in _SUFFIXES
    )


@dataclass(frozen=True)
class SourceFile:
    relative_path: str
    sha256: str
    content: bytes


class SourceSnapshot:
    def __init__(self, files: tuple[SourceFile, ...]) -> None:
        self.files = files
        self._by_path = {item.relative_path: item for item in files}
        self.manifest = {item.relative_path: {"sha256": item.sha256, "size": len(item.content)} for item in files}
        self.identity = digest_bytes(canonical_bytes(self.manifest))

    @classmethod
    def capture(cls, root: Path) -> "SourceSnapshot":
        # Do not follow a junction at the root or anywhere within an allowed tree.
        root = root.absolute()
        if any(_linked(path) for path in (root, *root.parents)):
            raise ValueError("Linked source roots are forbidden")
        root = root.resolve(strict=True)
        candidates: list[Path] = []
        for name in sorted(_FILES):
            path = root / name
            if path.exists():
                candidates.append(path)
        for name in _TREES:
            tree = root / name
            if not tree.exists():
                continue
            stack = [tree]
            while stack:
                directory = stack.pop()
                if _linked(directory):
                    raise ValueError("Linked source directories are forbidden")
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if entry.name.startswith(".") or entry.name in _EXCLUDED:
                            continue
                        path = Path(entry.path)
                        if _linked(path):
                            raise ValueError("Linked source entries are forbidden")
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(path)
                        elif entry.is_file(follow_symlinks=False) and permitted_source_path(path.relative_to(root).as_posix()):
                            candidates.append(path)
        files: list[SourceFile] = []
        total = 0
        for path in sorted(set(candidates)):
            for parent in (path, *path.parents):
                if parent == root:
                    break
                if _linked(parent):
                    raise ValueError("Linked source ancestors are forbidden")
            before = path.stat()
            if before.st_size > MAX_FILE_BYTES:
                raise ValueError("Source file exceeds snapshot budget")
            content = path.read_bytes()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("Source changed during snapshot")
            total += len(content)
            if total > MAX_SNAPSHOT_BYTES:
                raise ValueError("Source snapshot exceeds budget")
            files.append(SourceFile(path.relative_to(root).as_posix(), digest_bytes(content), content))
        if not files:
            raise ValueError("No permitted source files")
        return cls(tuple(files))

    def export(self, destination: Path) -> None:
        # New directory only; never overwrite a working tree or merge a snapshot.
        if destination.exists():
            raise ValueError("Snapshot destination already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.parent.resolve() != destination.parent.absolute():
            raise ValueError("Linked snapshot destination is forbidden")
        destination.mkdir()
        for item in self.files:
            target = destination / item.relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(item.content)
        (destination / "source-manifest.json").write_bytes(canonical_bytes({
            "schema_version": 1, "identity": self.identity, "files": self.manifest,
        }))

    def read(self, relative_path: str, start: int = 1, limit: int = 80) -> dict:
        safe_relative(relative_path)
        if type(start) is not int or type(limit) is not int or start < 1 or not 1 <= limit <= 120:
            raise ValueError("Invalid source line range")
        item = self._by_path.get(relative_path)
        if item is None:
            raise ValueError("Source path is not in this snapshot")
        lines = item.content.decode("utf-8-sig").splitlines()
        excerpt = [
            {"line": index + 1, "text": "[REDACTED CONFIGURATION]" if _SENSITIVE.search(line) else line[:1000]}
            for index, line in enumerate(lines) if start <= index + 1 < start + limit
        ]
        return {"snapshot_sha256": self.identity, "path": relative_path, "file_sha256": item.sha256,
                "total_lines": len(lines), "lines": excerpt, "redacted": True}

    def search(self, query: str, prefix: str = "back/app", limit: int = 30) -> dict:
        safe_relative(prefix)
        if not isinstance(query, str) or not 2 <= len(query) <= 120 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Invalid literal source search")
        hits = []
        for item in self.files:
            if not (item.relative_path == prefix or item.relative_path.startswith(prefix + "/")):
                continue
            for number, line in enumerate(item.content.decode("utf-8-sig").splitlines(), 1):
                if query.casefold() in line.casefold() and not _SENSITIVE.search(line):
                    hits.append({"path": item.relative_path, "line": number, "text": line[:600], "file_sha256": item.sha256})
                    if len(hits) == limit:
                        return {"snapshot_sha256": self.identity, "hits": hits, "truncated": True}
        return {"snapshot_sha256": self.identity, "hits": hits, "truncated": False}
