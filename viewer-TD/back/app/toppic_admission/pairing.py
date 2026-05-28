"""Pair TopPIC pipeline PrSM XML, MS2 msalign, and mzML files by run key."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .types import RunTriple

_XML_SUFFIXES = ("_ms2_toppic_prsm.xml", "_toppic_prsm.xml")
_MS2_MSALIGN_SUFFIX = "_ms2.msalign"


@dataclass(frozen=True)
class PairingResult:
    triples: tuple[RunTriple, ...]
    reject_code: str | None = None
    reject_detail: str | None = None


def _normalize_key(value: str) -> str:
    return value.strip().lower()


def run_key_from_prsm_xml(path: Path) -> str | None:
    name = path.name
    lower = name.lower()
    for suffix in _XML_SUFFIXES:
        if lower.endswith(suffix):
            return _normalize_key(name[: -len(suffix)])
    return None


def run_key_from_ms2_msalign(path: Path) -> str | None:
    name = path.name
    lower = name.lower()
    if lower.endswith(_MS2_MSALIGN_SUFFIX):
        return _normalize_key(name[: -len(_MS2_MSALIGN_SUFFIX)])
    return None


def run_key_from_mzml(path: Path) -> str:
    name = path.name
    lower = name.lower()
    if lower.endswith(".mzml.gz"):
        stem = name[: -len(".mzML.gz")]
    elif lower.endswith(".mzml"):
        stem = name[: -len(".mzML")]
    else:
        stem = path.stem
    return _normalize_key(stem)


def _index_by_key(paths: tuple[Path, ...], key_fn) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for path in paths:
        key = key_fn(path)
        if key is None:
            continue
        out.setdefault(key, []).append(path)
    return out


def pair_pipeline_runs(
    *,
    prsm_xml_files: tuple[Path, ...],
    ms2_msalign_files: tuple[Path, ...],
    mzml_files: tuple[Path, ...],
) -> PairingResult:
    """Return paired runs or a pairing failure code."""
    if not prsm_xml_files:
        return PairingResult(())

    xml_by_key = _index_by_key(prsm_xml_files, run_key_from_prsm_xml)
    msalign_by_key = _index_by_key(ms2_msalign_files, run_key_from_ms2_msalign)
    mzml_by_key = {run_key_from_mzml(p): p for p in mzml_files}

    for key, paths in xml_by_key.items():
        if len(paths) > 1:
            names = ", ".join(p.name for p in paths)
            return PairingResult(
                (),
                reject_code="ambiguous_pairing",
                reject_detail=f"Duplicate PrSM XML for run key '{key}': {names}.",
            )
    for key, paths in msalign_by_key.items():
        if len(paths) > 1:
            names = ", ".join(p.name for p in paths)
            return PairingResult(
                (),
                reject_code="ambiguous_pairing",
                reject_detail=f"Duplicate MS2 msalign for run key '{key}': {names}.",
            )

    triples: list[RunTriple] = []
    for key in sorted(xml_by_key):
        xml_paths = xml_by_key[key]
        msalign_paths = msalign_by_key.get(key, [])
        mzml = mzml_by_key.get(key)
        if not msalign_paths:
            return PairingResult(
                (),
                reject_code="unpaired_run",
                reject_detail=(
                    f"PrSM XML '{xml_paths[0].name}' has no matching *_ms2.msalign for run key '{key}'."
                ),
            )
        if mzml is None:
            return PairingResult(
                (),
                reject_code="unpaired_run",
                reject_detail=(
                    f"PrSM XML '{xml_paths[0].name}' has no matching mzML for run key '{key}'."
                ),
            )
        triples.append(
            RunTriple(
                prsm_xml=xml_paths[0],
                ms2_msalign=msalign_paths[0],
                mzml=mzml,
                run_key=key,
            )
        )

    return PairingResult(tuple(triples))
