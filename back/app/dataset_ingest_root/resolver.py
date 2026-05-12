"""Locate the single dataset root under a possibly nested user-selected directory."""

from __future__ import annotations

from pathlib import Path


def has_dataset_layout(path: Path) -> bool:
    """Return True if *path* looks like a TopPIC HTML tree or PrSM bundle root."""
    return path.is_dir() and (
        (path / "toppic_prsm_cutoff").is_dir()
        or (path / "topfd").is_dir()
        or (path / "toppic_proteoform_cutoff").is_dir()
        or (path / "data").is_dir()
    )


def find_ingest_root(extract_dir: Path) -> Path:
    """Return the dataset folder to pass to ``plan_zip_ingest`` / ingest adapters.

    If *extract_dir* itself matches :func:`has_dataset_layout`, it is returned.
    Otherwise exactly one direct subdirectory must match; multiple matches
    raise ``ValueError``.
    """
    extract_dir = extract_dir.resolve()
    if has_dataset_layout(extract_dir):
        return extract_dir
    subdirs = [p for p in extract_dir.iterdir() if p.is_dir()]
    matches = [p for p in subdirs if has_dataset_layout(p)]
    if len(matches) == 1:
        return matches[0].resolve()
    if len(matches) > 1:
        raise ValueError(
            "Multiple dataset folders found under the selected path; keep a single TopPIC output tree."
        )
    raise ValueError(
        "Could not find a TopPIC dataset folder (expect topfd/ and/or toppic_*_cutoff/ under the path)."
    )


def resolve_ingest_root(user_selected: Path | str) -> Path:
    """Resolve *user_selected* to an absolute path and locate the ingest root."""
    root = Path(user_selected).expanduser().resolve()
    if not root.exists():
        raise ValueError(f"path does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"path is not a directory: {root}")
    return find_ingest_root(root)
