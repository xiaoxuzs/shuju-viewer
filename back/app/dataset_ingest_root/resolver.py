"""Locate the single dataset root under a possibly nested user-selected directory."""

from __future__ import annotations

from pathlib import Path


_BU_REPORT_NAMES = ("all_report.parquet", "target_report.parquet")


def has_dataset_layout(path: Path) -> bool:
    """Return True if *path* looks like a TopPIC HTML tree or PrSM bundle root."""
    return path.is_dir() and (
        (path / "toppic_prsm_cutoff").is_dir()
        or (path / "topfd").is_dir()
        or (path / "toppic_proteoform_cutoff").is_dir()
        or (path / "data").is_dir()
    )


def has_bu_diann_layout(path: Path) -> bool:
    """Return True if *path* looks like a DIA-NN Bottom-Up ingest root."""
    if not path.is_dir():
        return False
    has_report = any((p.name in _BU_REPORT_NAMES and p.is_file()) for p in path.rglob("*.parquet"))
    if not has_report:
        return False
    has_mzml = any(p.is_file() for p in path.rglob("*.mzML")) or any(p.is_file() for p in path.rglob("*.mzml"))
    if has_mzml:
        return True
    has_raw = any(p.is_file() and p.suffix.lower() == ".raw" for p in path.rglob("*"))
    if has_raw:
        return True
    return any(p.is_dir() for p in path.rglob("*.d"))


def _matching_layouts(path: Path) -> list[tuple[str, Path]]:
    matches: list[tuple[str, Path]] = []
    has_td = has_dataset_layout(path)
    has_bu = has_bu_diann_layout(path)
    if has_td and has_bu:
        raise ValueError(
            "The selected ingest root matches both TopPIC and DIA-NN layouts; keep exactly one dataset shape."
        )
    if has_td:
        matches.append(("TopPIC", path))
    if has_bu:
        matches.append(("DIA-NN", path))
    return matches


def find_ingest_root(extract_dir: Path) -> Path:
    """Return the dataset folder to pass to ``plan_zip_ingest`` / ingest adapters.

    If *extract_dir* itself matches :func:`has_dataset_layout`, it is returned.
    Otherwise exactly one direct subdirectory must match; multiple matches
    raise ``ValueError``.
    """
    extract_dir = extract_dir.resolve()
    root_matches = _matching_layouts(extract_dir)
    if len(root_matches) == 1:
        return extract_dir
    subdirs = [p for p in extract_dir.iterdir() if p.is_dir()]
    matches: list[tuple[str, Path]] = []
    for subdir in subdirs:
        matches.extend(_matching_layouts(subdir))
    if len(matches) == 1:
        return matches[0][1].resolve()
    if len(matches) > 1:
        raise ValueError(
            "Multiple dataset folders found under the selected path; keep a single TopPIC or DIA-NN output tree."
        )
    raise ValueError(
        "Could not find a TopPIC or DIA-NN dataset folder "
        "(expect TopPIC topfd/toppic_*_cutoff, or DIA-NN all_report.parquet plus mzML/.raw/.d)."
    )


def resolve_ingest_root(user_selected: Path | str) -> Path:
    """Resolve *user_selected* to an absolute path and locate the ingest root."""
    root = Path(user_selected).expanduser().resolve()
    if not root.exists():
        raise ValueError(f"path does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"path is not a directory: {root}")
    return find_ingest_root(root)
