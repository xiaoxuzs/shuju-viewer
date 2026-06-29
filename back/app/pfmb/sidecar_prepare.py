"""Prepare PFMB sidecars for Bottom-Up imports."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.pfmb.index_builder import (
    build_index_json_from_pos_pkl,
    count_pos_pkl_expansion,
    read_pfmb_record_count,
)
from app.pfmb.locator import detect_sidecar
from app.pfmb.reference_sidecar import (
    find_reference_v2_sidecar,
    is_v2_sidecar_for_pos_pkl,
    materialize_v2_sidecar,
)


@dataclass(frozen=True, slots=True)
class PfmbSidecarPreparation:
    sidecar_dir: Path | None
    status: str
    message: str | None = None
    generated: bool = False
    pos_pkl_path: Path | None = None


def prepare_bu_pfmb_sidecar(
    ingest_root: Path | str,
    *,
    slug: str,
    output_root: Path | str | None = None,
    bridge_exe: Path | str | None = None,
    disable_jit: bool | None = None,
) -> PfmbSidecarPreparation:
    """Find or generate a PFMB sidecar for a BU dataset.

    Missing ``*.pos.pkl`` or generation failures do not fail the BU import; they
    simply return ``sidecar_dir=None`` so the dataset imports without module 4.
    """

    root = Path(ingest_root).resolve()
    output_base = Path(output_root or settings.bu_fragment_match_root).resolve()
    bridge = Path(bridge_exe or settings.resolved_pfmb_bridge_exe()).resolve()
    disable_jit = settings.pfmb_bridge_disable_jit if disable_jit is None else disable_jit

    pos_pkls = find_pos_pkl_files(root)

    existing = find_existing_sidecar_dir(root)
    if existing is not None:
        if pos_pkls and not is_v2_sidecar_for_pos_pkl(existing, pos_pkls[0]):
            return PfmbSidecarPreparation(
                sidecar_dir=None,
                status="skipped_legacy_v1_sidecar",
                message=(
                    f"Ignoring legacy v1 PFMB sidecar under {existing}; "
                    "v2 full-RT sidecar required."
                ),
            )
        return PfmbSidecarPreparation(
            sidecar_dir=existing,
            status="existing",
            message=f"Using existing PFMB sidecar: {existing}",
        )

    if not pos_pkls:
        return PfmbSidecarPreparation(
            sidecar_dir=None,
            status="skipped_no_pos_pkl",
            message="No PFMB sidecar or *.pos.pkl found; importing BU data without Fragment Match.",
        )
    if len(pos_pkls) > 1:
        return PfmbSidecarPreparation(
            sidecar_dir=None,
            status="skipped_multiple_pos_pkl",
            message=(
                "Multiple *.pos.pkl files found; importing BU data without Fragment Match: "
                + ", ".join(str(p) for p in pos_pkls[:5])
            ),
        )
    generated = find_generated_sidecar_dir(
        slug=slug,
        output_root=output_base,
        pos_pkl=pos_pkls[0],
    )
    if generated is not None:
        return PfmbSidecarPreparation(
            sidecar_dir=generated,
            status="existing_generated",
            message=f"Using existing generated PFMB sidecar: {generated}",
            pos_pkl_path=pos_pkls[0],
        )

    output_dir = output_base / _safe_slug(slug)
    reference = find_reference_v2_sidecar(pos_pkls[0], settings.pfmb_v2_reference_root_list)
    if reference is not None:
        try:
            materialize_v2_sidecar(
                reference_dir=reference,
                output_dir=output_dir,
                pos_pkl=pos_pkls[0],
            )
            _write_generation_manifest(
                output_dir / "generation_manifest.json",
                pos_pkl=pos_pkls[0],
                cache_path=output_dir / "prsm.cache",
                pfmb_path=output_dir / "results.pfmb",
                index_path=output_dir / "index.json",
                item_count=count_pos_pkl_expansion(pos_pkls[0])[1],
                source_row_count=count_pos_pkl_expansion(pos_pkls[0])[0],
                bridge_exe=bridge,
                disable_jit=disable_jit,
                pfmb_schema_version=2,
                materialized_from=reference,
            )
        except Exception as exc:  # noqa: BLE001
            return PfmbSidecarPreparation(
                sidecar_dir=None,
                status="skipped_reference_materialize_failed",
                message=f"Could not materialize v2 PFMB sidecar from {reference}: {exc}",
                pos_pkl_path=pos_pkls[0],
            )
        return PfmbSidecarPreparation(
            sidecar_dir=output_dir.resolve(),
            status="materialized_v2_reference",
            message=f"Materialized v2 PFMB sidecar from reference: {reference}",
            generated=True,
            pos_pkl_path=pos_pkls[0],
        )

    if not bridge.is_file():
        return PfmbSidecarPreparation(
            sidecar_dir=None,
            status="skipped_bridge_missing",
            message=f"PFMB bridge executable not found: {bridge}",
            pos_pkl_path=pos_pkls[0],
        )

    output_dir = output_base / _safe_slug(slug)
    try:
        generated = generate_pfmb_sidecar(
            pos_pkl=pos_pkls[0],
            output_dir=output_dir,
            bridge_exe=bridge,
            disable_jit=disable_jit,
        )
    except Exception as exc:  # noqa: BLE001 - import should continue without module 4
        return PfmbSidecarPreparation(
            sidecar_dir=None,
            status="skipped_generation_failed",
            message=f"PFMB generation failed; importing BU data without Fragment Match: {exc}",
            pos_pkl_path=pos_pkls[0],
        )

    return PfmbSidecarPreparation(
        sidecar_dir=generated,
        status="generated",
        message=f"Generated PFMB sidecar: {generated}",
        generated=True,
        pos_pkl_path=pos_pkls[0],
    )


def find_existing_sidecar_dir(root: Path) -> Path | None:
    """Return the first existing sidecar directory supplied with this dataset."""

    candidates = [
        root,
        root / "data",
        root / "pfmb",
        root / "PFMB",
    ]
    try:
        children = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        children = []
    for child in children:
        name = child.name.lower()
        if "pfmb" in name or "fragment" in name:
            candidates.append(child)

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if detect_sidecar(resolved) is not None:
            return resolved
    return None


def find_generated_sidecar_dir(*, slug: str, output_root: Path, pos_pkl: Path) -> Path | None:
    """Return a previously generated sidecar only when it matches this pos.pkl."""

    candidate = output_root / _safe_slug(slug)
    if detect_sidecar(candidate) is None:
        return None

    manifest = candidate / "generation_manifest.json"
    if not manifest.is_file():
        return None
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        source_info = payload.get("source", {})
        source = Path(source_info.get("pos_pkl", "")).resolve()
        pos_stat = pos_pkl.stat()
    except (OSError, TypeError, ValueError):
        return None
    if source != pos_pkl.resolve():
        return None
    if source_info.get("size") != pos_stat.st_size:
        return None
    if source_info.get("mtime_ns") != pos_stat.st_mtime_ns:
        return None
    if not is_v2_sidecar_for_pos_pkl(candidate, pos_pkl):
        return None
    return candidate.resolve()


def find_pos_pkl_files(root: Path | str) -> list[Path]:
    """Find DIA-NN ``*.pos.pkl`` files under *root*."""

    base = Path(root).resolve()
    return sorted(
        (
            p.resolve()
            for p in base.rglob("*")
            if p.is_file() and p.name.lower().endswith(".pos.pkl")
        ),
        key=lambda p: str(p),
    )


def generate_pfmb_sidecar(
    *,
    pos_pkl: Path,
    output_dir: Path,
    bridge_exe: Path,
    disable_jit: bool,
) -> Path:
    """Run ``pfmb_bridge`` and build the missing Viewer ``index.json``."""

    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / "prsm.cache"
    ingest_manifest = output_dir / "ingest_manifest.json"

    env = os.environ.copy()
    if disable_jit:
        env["NUMBA_DISABLE_JIT"] = "1"

    try:
        _run_generation_commands(
            bridge_exe=bridge_exe,
            pos_pkl=pos_pkl,
            cache_path=cache_path,
            ingest_manifest=ingest_manifest,
            output_dir=output_dir,
            env=env,
        )
    except RuntimeError as exc:
        if disable_jit or not _looks_like_numba_cache_failure(str(exc)):
            raise
        retry_env = os.environ.copy()
        retry_env["NUMBA_DISABLE_JIT"] = "1"
        _run_generation_commands(
            bridge_exe=bridge_exe,
            pos_pkl=pos_pkl,
            cache_path=cache_path,
            ingest_manifest=ingest_manifest,
            output_dir=output_dir,
            env=retry_env,
        )
        disable_jit = True

    pfmb_path = output_dir / "results.pfmb"
    source_rows, expanded = count_pos_pkl_expansion(pos_pkl)
    pfmb_count = read_pfmb_record_count(pfmb_path)
    if pfmb_count != expanded:
        reference = find_reference_v2_sidecar(pos_pkl, settings.pfmb_v2_reference_root_list)
        if reference is not None:
            shutil.rmtree(output_dir, ignore_errors=True)
            output_dir.mkdir(parents=True, exist_ok=True)
            materialize_v2_sidecar(
                reference_dir=reference,
                output_dir=output_dir,
                pos_pkl=pos_pkl,
            )
            pfmb_path = output_dir / "results.pfmb"
            pfmb_count = read_pfmb_record_count(pfmb_path)
        if pfmb_count != expanded:
            raise ValueError(
                "PFMB bridge produced a v1 sidecar "
                f"({pfmb_count} records) but this pos.pkl expands to {expanded} RT slots. "
                "Provide a v2 reference sidecar under PFMB_V2_REFERENCE_ROOTS or set "
                "PFMB_V2_BRIDGE_EXE when a full_rt-capable bridge is available."
            )

    built = build_index_json_from_pos_pkl(
        pos_pkl,
        output_dir / "index.json",
        expected_record_count=source_rows,
        expected_expanded_record_count=expanded,
    )
    _write_generation_manifest(
        output_dir / "generation_manifest.json",
        pos_pkl=pos_pkl,
        cache_path=cache_path,
        pfmb_path=pfmb_path,
        index_path=built.index_path,
        item_count=built.item_count,
        source_row_count=built.source_row_count,
        bridge_exe=bridge_exe,
        disable_jit=disable_jit,
        pfmb_schema_version=2,
    )
    if detect_sidecar(output_dir) is None:
        raise RuntimeError(f"generated PFMB sidecar is incomplete under {output_dir}")
    return output_dir.resolve()


def _run_generation_commands(
    *,
    bridge_exe: Path,
    pos_pkl: Path,
    cache_path: Path,
    ingest_manifest: Path,
    output_dir: Path,
    env: dict[str, str],
) -> None:
    _run_bridge(
        [
            str(bridge_exe),
            "ingest",
            "--source",
            "diann_pos_pkl",
            "--pos-pkl",
            str(pos_pkl),
            "--cache",
            str(cache_path),
            "--manifest",
            str(ingest_manifest),
        ],
        cwd=bridge_exe.parent,
        env=env,
    )
    _run_bridge(
        [
            str(bridge_exe),
            "run",
            "--cache",
            str(cache_path),
            "--output",
            str(output_dir),
            "--preset",
            "dia_extended",
        ],
        cwd=bridge_exe.parent,
        env=env,
    )


def _run_bridge(args: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    result = subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(stderr[-2000:] if stderr else f"pfmb_bridge exited with {result.returncode}")


def _looks_like_numba_cache_failure(message: str) -> bool:
    lowered = message.lower()
    return "numba" in lowered and "cache" in lowered


def _safe_slug(slug: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", slug.strip())
    return safe.strip("._") or "dataset"


def _write_generation_manifest(
    path: Path,
    *,
    pos_pkl: Path,
    cache_path: Path,
    pfmb_path: Path,
    index_path: Path,
    item_count: int,
    source_row_count: int,
    bridge_exe: Path,
    disable_jit: bool,
    pfmb_schema_version: int = 2,
    materialized_from: Path | None = None,
) -> None:
    source_stat = pos_pkl.stat()
    payload: dict[str, object] = {
        "pfmb_schema_version": pfmb_schema_version,
        "source": {
            "pos_pkl": str(pos_pkl.resolve()),
            "size": source_stat.st_size,
            "mtime_ns": source_stat.st_mtime_ns,
        },
        "outputs": {
            "cache": str(cache_path.resolve()),
            "pfmb": str(pfmb_path.resolve()),
            "index": str(index_path.resolve()),
        },
        "counts": {
            "expanded_records": item_count,
            "source_rows": source_row_count,
        },
        "bridge": {
            "exe": str(bridge_exe.resolve()),
            "numba_disable_jit": disable_jit,
            "preset": "dia_extended",
        },
    }
    if materialized_from is not None:
        payload["materialized_from"] = str(materialized_from.resolve())
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
