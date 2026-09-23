"""Small process cache for .zp reader instances."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.zp_runtime.package import BinaryLayerUnavailableError, zp_reader_class


class ZpReaderCacheError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ZpFileIdentity:
    path: str
    size: int
    mtime_ns: int


@dataclass(slots=True)
class ZpReaderHandle:
    identity: ZpFileIdentity
    reader: Any
    lock: threading.RLock


_CACHE_LOCK = threading.RLock()
_READER_CACHE: dict[str, ZpReaderHandle] = {}


def get_reader_handle(path: Path) -> ZpReaderHandle:
    try:
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
    except OSError as exc:
        raise ZpReaderCacheError("binary_zp_not_found") from exc

    identity = ZpFileIdentity(
        path=str(resolved),
        size=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
    )
    with _CACHE_LOCK:
        cached = _READER_CACHE.get(identity.path)
        if cached is not None and cached.identity == identity:
            return cached
        try:
            reader = zp_reader_class()(resolved)
        except BinaryLayerUnavailableError as exc:
            raise ZpReaderCacheError("binary_layer_unavailable") from exc
        handle = ZpReaderHandle(identity=identity, reader=reader, lock=threading.RLock())
        _READER_CACHE[identity.path] = handle
        return handle


def clear_reader_cache() -> None:
    with _CACHE_LOCK:
        _READER_CACHE.clear()
