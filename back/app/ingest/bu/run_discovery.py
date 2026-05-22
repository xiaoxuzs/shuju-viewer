"""Discover mzML and Bruker ``.d`` runs for DIA-NN Bottom-Up imports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.mzml_mapping import collect_mzml_files, normalize_spectrum_file_name


@dataclass(frozen=True)
class BuRunFile:
    file_path: Path
    file_name: str
    raw_format: str
    diann_run_name: str | None = None


def is_valid_bruker_tdf_root(path: Path) -> bool:
    """Return True for the effective Bruker TDF directory used at runtime."""
    tdf = path / "analysis.tdf"
    try:
        return tdf.is_file() and tdf.stat().st_size > 0 and (path / "analysis.tdf_bin").is_file()
    except OSError:
        return False


def resolve_bruker_tdf_root(path: Path) -> Path:
    """Resolve a possibly wrapped ``xxx.d`` folder to the inner valid TDF root."""
    root = path.resolve()
    if is_valid_bruker_tdf_root(root):
        return root
    inner = root / root.name
    if inner.is_dir() and is_valid_bruker_tdf_root(inner):
        return inner.resolve()
    raise ValueError(f"no valid Bruker TDF root under {root}")


def normalize_diann_run_name(value: str) -> str:
    """Normalize DIA-NN ``Run`` values and file names for matching."""
    name = (value or "").strip().replace("\\", "/").split("/")[-1]
    low = name.lower()
    for suffix in (".mzml.gz", ".mzml", ".d"):
        if low.endswith(suffix):
            low = low[: -len(suffix)]
            break
    return low


def discover_bu_runs(root: Path) -> list[BuRunFile]:
    """Return one run entry per mzML file and valid Bruker ``.d`` directory."""
    base = root.resolve()
    runs: list[BuRunFile] = []
    for mzml in collect_mzml_files(base):
        runs.append(
            BuRunFile(
                file_path=mzml.resolve(),
                file_name=mzml.name,
                raw_format="mzml",
                diann_run_name=normalize_spectrum_file_name(mzml.name),
            )
        )

    seen_tdf_roots: set[str] = set()
    for d_path in sorted((p for p in base.rglob("*.d") if p.is_dir()), key=lambda p: str(p)):
        try:
            tdf_root = resolve_bruker_tdf_root(d_path)
        except ValueError:
            continue
        key = str(tdf_root.resolve())
        if key in seen_tdf_roots:
            continue
        seen_tdf_roots.add(key)
        runs.append(
            BuRunFile(
                file_path=tdf_root,
                file_name=tdf_root.name,
                raw_format="bruker_d",
                diann_run_name=normalize_diann_run_name(tdf_root.name),
            )
        )
    return runs


def match_diann_runs_to_files(diann_run_names: set[str], run_files: list[BuRunFile]) -> dict[str, BuRunFile]:
    """Map DIA-NN report ``Run`` values to discovered files.

    If there is exactly one discovered run and report names do not match, use
    the single-run fallback from decision D11. With multiple discovered runs,
    every report run must match a file name.
    """
    by_key: dict[str, BuRunFile] = {}
    for run_file in run_files:
        if run_file.diann_run_name:
            by_key[run_file.diann_run_name] = run_file

    matched: dict[str, BuRunFile] = {}
    missing: list[str] = []
    for run_name in sorted(diann_run_names):
        hit = by_key.get(normalize_diann_run_name(run_name))
        if hit is None:
            missing.append(run_name)
            continue
        matched[run_name] = hit

    if missing:
        if len(run_files) == 1:
            fallback = run_files[0]
            for run_name in missing:
                matched[run_name] = fallback
        else:
            raise ValueError(
                "DIA-NN report Run values did not match discovered spectrum files: "
                + ", ".join(missing[:10])
            )
    return matched
