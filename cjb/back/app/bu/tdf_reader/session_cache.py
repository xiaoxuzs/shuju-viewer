"""Small LRU cache for Bruker TDF sessions."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class TdfpyUnavailable(RuntimeError):
    """Raised when the optional ``tdfpy`` dependency is not installed."""


@dataclass
class _Entry:
    session: Any
    path: Path
    mtime: float


_MAX_SESSIONS = 2
_CACHE: OrderedDict[tuple[int, int], _Entry] = OrderedDict()


def get_session(*, dataset_id: int, run_id: int, tdf_root: Path) -> Any:
    """Return an open ``tdfpy.DIA`` session for the run."""
    key = (dataset_id, run_id)
    root = tdf_root.resolve()
    mtime = _tdf_mtime(root)
    entry = _CACHE.get(key)
    if entry is not None and entry.path == root and entry.mtime == mtime:
        _CACHE.move_to_end(key)
        return entry.session
    if entry is not None:
        _close(entry.session)

    try:
        from tdfpy import DIA
    except ImportError as exc:
        raise TdfpyUnavailable("tdfpy_unavailable") from exc

    session = DIA(str(root))
    _CACHE[key] = _Entry(session=session, path=root, mtime=mtime)
    _CACHE.move_to_end(key)
    while len(_CACHE) > _MAX_SESSIONS:
        _old_key, old = _CACHE.popitem(last=False)
        _close(old.session)
    return session


def clear_cache() -> None:
    """Close and clear cached sessions; mostly useful for tests."""
    while _CACHE:
        _old_key, entry = _CACHE.popitem(last=False)
        _close(entry.session)


def _tdf_mtime(root: Path) -> float:
    mtimes = []
    for name in ("analysis.tdf", "analysis.tdf_bin"):
        try:
            mtimes.append((root / name).stat().st_mtime)
        except OSError:
            continue
    return max(mtimes) if mtimes else 0.0


def _close(session: Any) -> None:
    close = getattr(session, "close", None)
    if callable(close):
        close()
