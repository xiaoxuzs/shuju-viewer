"""Discover Thermo RAW files and same-stem mzML candidates."""

from __future__ import annotations

from pathlib import Path

from app.raw_conversion.contracts import RAW_VENDOR_THERMO, RawFileCandidate


def collect_raw_files(root: Path) -> list[Path]:
    """Return Thermo RAW file candidates under *root*.

    P0 treats file suffix ``.raw`` case-insensitively as Thermo RAW. Bruker
    ``.d`` is a directory format and is intentionally ignored here.
    """
    base = root.resolve()
    out: list[Path] = []
    for path in base.rglob("*"):
        try:
            if path.is_file() and path.suffix.lower() == ".raw":
                out.append(path.resolve())
        except OSError:
            continue
    return sorted(out, key=lambda p: str(p))


def expected_converted_mzml_path(*, raw_path: Path, source_root: Path, output_dir: Path) -> Path:
    try:
        relative = raw_path.resolve().relative_to(source_root.resolve())
    except ValueError:
        relative = Path(raw_path.name)
    return (output_dir / relative).with_suffix(".mzML")


def _same_stem_mzml_candidates(path: Path) -> tuple[Path, Path]:
    return (
        path.with_name(f"{path.stem}.mzML"),
        path.with_name(f"{path.stem}.mzml"),
    )


def find_existing_mzml_for_raw(*, raw_path: Path, source_root: Path, output_dir: Path) -> Path | None:
    expected = expected_converted_mzml_path(
        raw_path=raw_path,
        source_root=source_root,
        output_dir=output_dir,
    )
    candidates = (
        *_same_stem_mzml_candidates(raw_path),
        *_same_stem_mzml_candidates(expected),
    )
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate.resolve()
        except OSError:
            continue
    return None


def discover_raw_file_candidates(*, source_root: Path, output_dir: Path) -> list[RawFileCandidate]:
    root = source_root.resolve()
    out_dir = output_dir.resolve()
    candidates: list[RawFileCandidate] = []
    for raw_path in collect_raw_files(root):
        expected = expected_converted_mzml_path(
            raw_path=raw_path,
            source_root=root,
            output_dir=out_dir,
        )
        candidates.append(
            RawFileCandidate(
                raw_path=raw_path,
                stem=raw_path.stem,
                vendor=RAW_VENDOR_THERMO,
                expected_mzml_path=expected,
                existing_mzml_path=find_existing_mzml_for_raw(
                    raw_path=raw_path,
                    source_root=root,
                    output_dir=out_dir,
                ),
            )
        )
    return candidates
