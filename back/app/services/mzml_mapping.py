"""Strict run ↔ mzML mapping for multi-file Top-down datasets.

This module runs at import time (after ZIP extraction) and MUST NOT read mzML
content into memory. It only discovers mzML files on disk and builds a strict
one-to-one mapping between:

- expected spectrum file names from PrSM detail JS files (ms_header.spectrum_file_name)
- actual *.mzML/*.mzml files extracted from the ZIP
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.js_parser import load_js_object


@dataclass(frozen=True)
class MzmlMappingResult:
    """Normalized key → unique mzML path mapping."""

    mapping: dict[str, Path]
    mzml_files: list[Path]
    spectrum_file_names: set[str]


class MzmlMappingError(RuntimeError):
    pass


def collect_mzml_files(extract_root: Path) -> list[Path]:
    root = extract_root.resolve()
    # Case-insensitive on Windows, but keep both patterns for portability.
    files = (
        list(root.rglob("*.mzML"))
        + list(root.rglob("*.mzml"))
        + list(root.rglob("*.mzML.gz"))
        + list(root.rglob("*.mzml.gz"))
    )
    # De-dup by resolved path.
    uniq: dict[str, Path] = {}
    for p in files:
        # rglob can match directory names; only keep actual files.
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        try:
            uniq[str(p.resolve())] = p.resolve()
        except OSError:
            uniq[str(p)] = p
    return sorted(uniq.values(), key=lambda x: str(x))


def normalize_spectrum_file_name(value: str) -> str:
    """Normalize spectrum file name for strict matching.

    Rules (fixed):
    - take basename (drop any directories)
    - drop one trailing .mzml (case-insensitive)
    - lowercase
    """
    name = (value or "").strip().replace("\\", "/").split("/")[-1]
    low = name.lower()
    if low.endswith(".gz"):
        low = low[: -len(".gz")]
    if low.endswith(".mzml"):
        low = low[: -len(".mzml")]
    return low


def extract_spectrum_file_names_from_prsms(prsms_dir: Path) -> set[str]:
    prsms_dir = prsms_dir.resolve()
    if not prsms_dir.exists() or not prsms_dir.is_dir():
        raise MzmlMappingError(f"missing prsms directory: {prsms_dir}")
    names: set[str] = set()
    files = sorted(prsms_dir.glob("prsm*.js"), key=lambda p: p.name)
    if not files:
        raise MzmlMappingError(f"no prsm*.js found under: {prsms_dir}")
    for path in files:
        doc = load_js_object(path)
        prsm_root = doc.get("prsm") or doc.get("prsm_data", {}).get("prsm") or doc
        ms = prsm_root.get("ms", {}) or {}
        header = ms.get("ms_header", {}) or {}
        raw_name = header.get("spectrum_file_name")
        if raw_name is None:
            raise MzmlMappingError(f"missing ms_header.spectrum_file_name in {path}")
        raw_text = str(raw_name).strip()
        if raw_text == "":
            raise MzmlMappingError(f"empty ms_header.spectrum_file_name in {path}")
        names.add(raw_text)
    return names


def build_one_to_one_mapping(
    *,
    spectrum_file_names: set[str],
    mzml_files: list[Path],
) -> dict[str, Path]:
    if not spectrum_file_names:
        raise MzmlMappingError("no spectrum_file_name extracted from prsm*.js")
    if not mzml_files:
        raise MzmlMappingError("no mzML files found in extracted archive")

    mzml_by_key: dict[str, list[Path]] = {}
    for p in mzml_files:
        key = normalize_spectrum_file_name(p.name)
        mzml_by_key.setdefault(key, []).append(p)

    out: dict[str, Path] = {}
    missing: list[str] = []
    conflicts: list[tuple[str, list[Path]]] = []
    for raw in sorted(spectrum_file_names):
        key = normalize_spectrum_file_name(raw)
        hits = mzml_by_key.get(key, [])
        if len(hits) == 0:
            missing.append(raw)
            continue
        if len(hits) > 1:
            # Common packaging issue: a duplicate mzML is nested in a wrapper
            # folder that shares the same name, e.g.:
            #   A.mzML
            #   A.mzML/A.mzML
            # Prefer the shallowest (shortest) path if it is uniquely best.
            ranked = sorted(hits, key=lambda p: (len(p.parts), len(str(p))))
            best = ranked[0]
            second = ranked[1]
            if (len(best.parts), len(str(best))) < (len(second.parts), len(str(second))):
                out[key] = best
                continue
            conflicts.append((raw, hits))
            continue
        out[key] = hits[0]

    if missing or conflicts:
        parts: list[str] = []
        if missing:
            parts.append("missing mzML for spectrum_file_name: " + ", ".join(missing[:10]))
            if len(missing) > 10:
                parts.append(f"... and {len(missing) - 10} more missing")
        if conflicts:
            for raw, hits in conflicts[:5]:
                parts.append(
                    "ambiguous mzML for spectrum_file_name={!r}: {}".format(
                        raw, "; ".join(str(p) for p in hits[:10])
                    )
                )
            if len(conflicts) > 5:
                parts.append(f"... and {len(conflicts) - 5} more ambiguous")
        raise MzmlMappingError(" | ".join(parts))

    return out


def build_mapping_from_extracted_dataset(*, ingest_root: Path) -> MzmlMappingResult:
    """Collect mzML files + spectrum_file_name set and build strict mapping."""
    mzml_files = collect_mzml_files(ingest_root)
    prsms_candidates = [
        ingest_root / "toppic_prsm_cutoff" / "data_js" / "prsms",
        ingest_root / "data",
    ]
    spectrum_file_names: set[str] | None = None
    last_error: Exception | None = None
    for cand in prsms_candidates:
        try:
            spectrum_file_names = extract_spectrum_file_names_from_prsms(cand)
            last_error = None
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
    if spectrum_file_names is None:
        raise MzmlMappingError(f"could not locate prsm*.js directory under ingest root: {last_error}")
    mapping = build_one_to_one_mapping(
        spectrum_file_names=spectrum_file_names,
        mzml_files=mzml_files,
    )
    return MzmlMappingResult(
        mapping=mapping,
        mzml_files=mzml_files,
        spectrum_file_names=spectrum_file_names,
    )

