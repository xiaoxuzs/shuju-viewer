"""Deterministic, paginated inventory for one Case source tree."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .contracts import InventoryItem, InventoryPage
from .paths import CasePathResolver, entry_is_link_or_junction


_CURSOR_VERSION = 1


class InvalidInventoryCursor(ValueError):
    pass


class StaleInventoryCursor(ValueError):
    pass


class InventoryService:
    """List Case-relative source entries without following links or junctions.

    The tree is rescanned on every page so ``total_count`` is the real count for
    the cursor snapshot, rather than the number retained for the current page.
    A changed tree invalidates the cursor instead of silently skipping entries.
    """

    def __init__(self, case_root: str | Path) -> None:
        self.paths = CasePathResolver(case_root)

    def list_files(self, *, limit: int = 100, cursor: str | None = None) -> InventoryPage:
        return self.list_directory(
            ".",
            recursive=True,
            include_directories=False,
            limit=limit,
            cursor=cursor,
        )

    def list_directory(
        self,
        relative_path: str = ".",
        *,
        recursive: bool = False,
        include_directories: bool = True,
        limit: int = 100,
        cursor: str | None = None,
    ) -> InventoryPage:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise ValueError("limit must be an integer between 1 and 1000")
        started = time.perf_counter()
        directory = self.paths.resolve_directory(relative_path)
        directory_label = self.paths.relative(directory)
        items, skipped_link_count = self._scan(
            directory,
            recursive=recursive,
            include_directories=include_directories,
        )
        items.sort(key=lambda item: (item.relative_path.casefold(), item.relative_path))
        snapshot = _snapshot_hash(items, skipped_link_count)
        query = {
            "directory": directory_label,
            "recursive": recursive,
            "include_directories": include_directories,
        }

        offset = 0
        if cursor is not None:
            payload = _decode_cursor(cursor)
            if payload.get("query") != query:
                raise InvalidInventoryCursor("inventory cursor belongs to a different query")
            if payload.get("snapshot") != snapshot:
                raise StaleInventoryCursor("source tree changed after the inventory cursor was issued")
            raw_offset = payload.get("offset")
            if isinstance(raw_offset, bool) or not isinstance(raw_offset, int) or raw_offset < 0:
                raise InvalidInventoryCursor("inventory cursor has an invalid offset")
            offset = raw_offset
        if offset > len(items):
            raise InvalidInventoryCursor("inventory cursor offset is outside the result set")

        page_items = items[offset : offset + limit]
        next_offset = offset + len(page_items)
        next_cursor = None
        if next_offset < len(items):
            next_cursor = _encode_cursor({"query": query, "snapshot": snapshot, "offset": next_offset})
        return InventoryPage(
            directory=directory_label,
            recursive=recursive,
            include_directories=include_directories,
            items=page_items,
            total_count=len(items),
            skipped_link_count=skipped_link_count,
            cursor=cursor,
            next_cursor=next_cursor,
            snapshot_sha256=snapshot,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    def _scan(
        self,
        directory: Path,
        *,
        recursive: bool,
        include_directories: bool,
    ) -> tuple[list[InventoryItem], int]:
        items: list[InventoryItem] = []
        skipped_links = 0
        pending = [directory]
        while pending:
            current = pending.pop()
            with os.scandir(current) as iterator:
                entries = list(iterator)
            for entry in entries:
                if entry_is_link_or_junction(entry):
                    skipped_links += 1
                    continue
                stat_result = entry.stat(follow_symlinks=False)
                path = Path(entry.path)
                relative = self.paths.relative(path)
                if entry.is_dir(follow_symlinks=False):
                    if include_directories:
                        items.append(
                            InventoryItem(
                                relative_path=relative,
                                kind="directory",
                                mtime_ns=int(stat_result.st_mtime_ns),
                            )
                        )
                    if recursive:
                        pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    items.append(
                        InventoryItem(
                            relative_path=relative,
                            kind="file",
                            size_bytes=int(stat_result.st_size),
                            mtime_ns=int(stat_result.st_mtime_ns),
                            extension=path.suffix.casefold(),
                        )
                    )
        return items, skipped_links


def _snapshot_hash(items: list[InventoryItem], skipped_link_count: int) -> str:
    digest = hashlib.sha256()
    for item in items:
        digest.update(
            (
                f"{item.relative_path}|{item.kind}|{item.size_bytes}|{item.mtime_ns}|{item.extension}\n"
            ).encode("utf-8")
        )
    digest.update(f"skipped-links|{skipped_link_count}".encode("ascii"))
    return digest.hexdigest()


def _encode_cursor(payload: dict[str, Any]) -> str:
    value = {"version": _CURSOR_VERSION, **payload}
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> dict[str, Any]:
    if not isinstance(cursor, str) or not cursor or len(cursor) > 4_096:
        raise InvalidInventoryCursor("inventory cursor is invalid")
    try:
        padding = "=" * (-len(cursor) % 4)
        value = json.loads(base64.b64decode(cursor + padding, altchars=b"-_", validate=True))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidInventoryCursor("inventory cursor is invalid") from exc
    if not isinstance(value, dict) or value.get("version") != _CURSOR_VERSION:
        raise InvalidInventoryCursor("inventory cursor version is unsupported")
    return value
