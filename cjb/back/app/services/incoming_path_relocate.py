"""Recover absolute paths recorded under ``<slug>.incoming`` before atomic rename.

ZIP import extracts to ``{{slug}}.incoming`` and later renames that directory to
``{{slug}}``. If a stored path was never rewritten (slash mismatch, legacy row,
etc.), :func:`try_fix_stale_incoming_absolute_path` finds the same file under
the post-rename tree by stripping one ``*.incoming`` path segment.
"""

from __future__ import annotations

from pathlib import Path


def try_fix_stale_incoming_absolute_path(path: Path) -> Path | None:
    """Return a path to an existing file, or ``None``.

    If ``path`` already exists as a file, returns it resolved. Otherwise tries
    each path segment ending in ``.incoming``: strip that suffix and test
    whether the rebuilt path points to an existing file.
    """
    path = Path(path)
    if path.is_file():
        return path.resolve()
    parts_all = list(path.parts)
    for i, seg in enumerate(parts_all):
        if not seg.endswith(".incoming"):
            continue
        parts = list(parts_all)
        parts[i] = seg[: -len(".incoming")]
        rebuilt = Path(parts[0])
        for s in parts[1:]:
            rebuilt = rebuilt / s
        if rebuilt.is_file():
            return rebuilt.resolve()
    return None


def relocate_incoming_root(*, path: Path, incoming_root: Path, final_root: Path) -> str:
    """Map ``path`` under ``incoming_root`` to the same relative path under ``final_root``.

    Used at import finalize when paths were collected before the incoming→final
    directory rename. Falls back to ``str(path)`` if ``path`` is not under
    ``incoming_root``.
    """
    try:
        rel = path.resolve().relative_to(incoming_root.resolve())
    except ValueError:
        return str(path)
    return str((final_root.resolve() / rel).resolve())
