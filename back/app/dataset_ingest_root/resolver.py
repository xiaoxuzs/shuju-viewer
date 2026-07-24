"""Locate the single dataset root under a possibly nested user-selected directory."""

from __future__ import annotations

from pathlib import Path


_BU_REPORT_NAMES = ("all_report.parquet", "target_report.parquet")

_SPECTRA_ONLY_LABEL = "mzML/RAW spectra"
"""Weakest layout signal: recursive mzML/RAW file search, easily true for wrapper dirs."""


def _has_mzml_or_raw_file(path: Path) -> bool:
    for candidate in path.rglob("*"):
        try:
            if not candidate.is_file():
                continue
        except OSError:
            continue
        name = candidate.name.lower()
        if name.endswith(".mzml") or candidate.suffix.lower() == ".raw":
            return True
    return False


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
    has_report = any(
        p.name.casefold() in _BU_REPORT_NAMES and p.is_file()
        for p in path.rglob("*")
    )
    if not has_report:
        return False
    has_mzml = any(p.is_file() for p in path.rglob("*.mzML")) or any(p.is_file() for p in path.rglob("*.mzml"))
    if has_mzml:
        return True
    has_raw = any(p.is_file() and p.suffix.lower() == ".raw" for p in path.rglob("*"))
    if has_raw:
        return True
    return any(p.is_dir() for p in path.rglob("*.d"))


def has_spectra_only_layout(path: Path) -> bool:
    """Return True when *path* has standalone mzML or Thermo RAW spectra."""
    return path.is_dir() and _has_mzml_or_raw_file(path)


def _matching_layouts(path: Path) -> list[tuple[str, Path]]:
    matches: list[tuple[str, Path]] = []
    has_td = has_dataset_layout(path)
    has_bu = has_bu_diann_layout(path)
    has_spectra = has_spectra_only_layout(path)
    if has_td and has_bu:
        raise ValueError(
            "The selected ingest root matches both TopPIC and DIA-NN layouts; keep exactly one dataset shape."
        )
    if has_td:
        matches.append(("TopPIC", path))
    if has_bu:
        matches.append(("DIA-NN", path))
    if not has_td and not has_bu and has_spectra:
        matches.append((_SPECTRA_ONLY_LABEL, path))
    return matches


def find_ingest_root(extract_dir: Path) -> Path:
    """Return the dataset folder to pass to ``plan_zip_ingest`` / ingest adapters.

    If *extract_dir* itself matches TopPIC or DIA-NN layout, it is returned directly.
    ``mzML/RAW spectra`` is the weakest signal (recursive file search, easily true for a
    wrapper directory whose real dataset lives one level deeper), so a spectra-only match
    at *extract_dir* is only accepted once no direct subdirectory has a stronger TopPIC/DIA-NN
    match; otherwise exactly one direct subdirectory must match, and multiple matches raise
    ``ValueError``.
    """
    extract_dir = extract_dir.resolve()
    root_matches = _matching_layouts(extract_dir)
    root_is_spectra_only = len(root_matches) == 1 and root_matches[0][0] == _SPECTRA_ONLY_LABEL
    if len(root_matches) == 1 and not root_is_spectra_only:
        return extract_dir
    subdirs = [p for p in extract_dir.iterdir() if p.is_dir()]
    matches: list[tuple[str, Path]] = []
    for subdir in subdirs:
        matches.extend(_matching_layouts(subdir))
    if len(matches) == 1:
        return matches[0][1].resolve()
    if len(matches) > 1:
        raise ValueError(
            "Multiple dataset folders found under the selected path; keep a single TopPIC, DIA-NN, mzML-only, "
            "or Thermo RAW-only dataset folder."
        )
    if root_is_spectra_only:
        return extract_dir
    raise ValueError(
        "Could not find a supported dataset folder (expect TopPIC topfd/toppic_*_cutoff, DIA-NN "
        "all_report.parquet plus mzML/.raw/.d, mzML-only files, or Thermo RAW-only files)."
    )


def resolve_ingest_root(user_selected: Path | str) -> Path:
    """Resolve *user_selected* to an absolute path and locate the ingest root."""
    root = Path(user_selected).expanduser().resolve()
    if not root.exists():
        raise ValueError(f"path does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"path is not a directory: {root}")
    return find_ingest_root(root)
