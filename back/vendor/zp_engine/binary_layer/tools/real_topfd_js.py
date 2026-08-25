from __future__ import annotations

import json
import math
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from ..blocks import (
    ISOLATION_WINDOW_KIND,
    ArrayBlock,
    BlockCollection,
    ExtensionBlock,
    GlobalMetaBlock,
    NormalizedFloat64List,
    PrecursorBlock,
    RunBlock,
    SpectrumBlock,
)
from ..constants import ZP_VERSION
from ..exceptions import InvalidSourceError
from ..models import ConversionOptions, PipelineContext
from ..native_mzml import NativeFloat64Array
from .base import BaseBlockTool


TOPFD_JS_METADATA_EXTENSION_TYPE = "topfd_js_metadata"
_ASSIGNMENT = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*", re.DOTALL)
_SPECTRUM_NAME = re.compile(r"^spectrum(\d+)\.js$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RealTopfdJsExecutionReport:
    spectrum_count: int
    ms1_count: int
    ms2_count: int


@dataclass(frozen=True, slots=True)
class _TopfdSpectrum:
    source_path: Path
    source_index: int
    ms_level: int
    source_id: int
    scan: int
    rt_seconds: float
    target_mz: float | None
    lower_mz: float | None
    upper_mz: float | None
    mz: Sequence[float]
    intensity: Sequence[float]
    tic: float
    bpc: float


class RealTopfdJsParseTool(BaseBlockTool):
    name = "real_topfd_js_parse"
    input_kinds = ("validated_source", "input_sha256")
    output_kinds = ("core_blocks", "arrays", "extensions")

    def __init__(self) -> None:
        self.last_report: RealTopfdJsExecutionReport | None = None

    def build_blocks(self, context: PipelineContext) -> None:
        if context.source_profile.source_type != "real_topfd_js_bundle":
            raise InvalidSourceError("real_topfd_js_parse requires a real_topfd_js_bundle source")
        if context.blocks != BlockCollection():
            raise InvalidSourceError("real_topfd_js_parse requires an empty BlockCollection")
        digest = context.metadata.get("input_sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise InvalidSourceError("hash_input must run before real_topfd_js_parse")

        options = context.metadata.get("conversion_options", ConversionOptions())
        compact = (
            isinstance(options, ConversionOptions)
            and context.metadata.get("format_version") == 3
        )
        root = context.source_profile.input_files[0]
        spectra = _load_topfd_spectra(
            root,
            compact=compact,
            temporary_directory=(options.temporary_directory if isinstance(options, ConversionOptions) else None),
        )
        if not spectra:
            raise InvalidSourceError(f"TopFD JS bundle contains no spectra: {root}")

        run_id = "run_1"
        created_at = context.metadata.get("block_created_at")
        if not isinstance(created_at, datetime):
            created_at = datetime.now(timezone.utc)

        spectrum_blocks: list[SpectrumBlock] = []
        precursor_blocks: list[PrecursorBlock] = []
        arrays: list[ArrayBlock] = []
        metadata_records: list[dict[str, Any]] = []

        for position, spectrum in enumerate(spectra, 1):
            spectrum_id = f"spectrum_{position:06d}"
            mz_array_id = f"{spectrum_id}:mz"
            intensity_array_id = f"{spectrum_id}:intensity"
            precursor_id: str | None = None
            if spectrum.ms_level == 2:
                precursor_id = f"{spectrum_id}:precursor"
                precursor_blocks.append(_precursor_block(precursor_id, spectrum_id, spectrum))
            spectrum_blocks.append(
                SpectrumBlock(
                    spectrum_id=spectrum_id,
                    run_id=run_id,
                    ms_level=spectrum.ms_level,
                    scan_number=spectrum.scan,
                    native_id=f"scan={spectrum.scan}",
                    rt=spectrum.rt_seconds,
                    precursor_id=precursor_id,
                    mz_array_id=mz_array_id,
                    intensity_array_id=intensity_array_id,
                )
            )
            arrays.extend(
                (
                    ArrayBlock(mz_array_id, "mz", "float64", _values(spectrum.mz, compact=compact)),
                    ArrayBlock(
                        intensity_array_id,
                        "intensity",
                        "float64",
                        _values(spectrum.intensity, compact=compact),
                    ),
                )
            )
            metadata_records.append(
                {
                    "spectrum_id": spectrum_id,
                    "source_index": spectrum.source_index,
                    "source_id": spectrum.source_id,
                    "source_file": _relative_label(root, spectrum.source_path),
                    "total_ion_current": spectrum.tic,
                    "base_peak_intensity": spectrum.bpc,
                    "isolation_window_target_mz": spectrum.target_mz,
                    "isolation_window_lower_mz": spectrum.lower_mz,
                    "isolation_window_upper_mz": spectrum.upper_mz,
                }
            )

        rt_values = [item.rt for item in spectrum_blocks]
        ms1_count = sum(1 for item in spectrum_blocks if item.ms_level == 1)
        ms2_count = sum(1 for item in spectrum_blocks if item.ms_level == 2)
        context.blocks = BlockCollection(
            global_meta=GlobalMetaBlock(
                format_version=ZP_VERSION,
                source_type="real_topfd_js_bundle",
                source_file_name=root.name,
                source_file_hash=digest,
                run_count=1,
                spectrum_count=len(spectrum_blocks),
                chromatogram_count=0,
                array_count=len(arrays),
                created_at=created_at,
                generator_name="zp-binary-layer",
                generator_version="0.1.0",
                notes=[
                    "Viewer TopFD JS conversion: spectra are normalized from topfd/ms1_json and topfd/ms2_json."
                ],
            ),
            runs=[
                RunBlock(
                    run_id=run_id,
                    source_file=root.name,
                    run_name=root.name,
                    spectrum_count=len(spectrum_blocks),
                    chromatogram_count=0,
                    start_rt=min(rt_values),
                    end_rt=max(rt_values),
                )
            ],
            spectra=spectrum_blocks,
            precursors=precursor_blocks,
            arrays=arrays,
            extensions=[
                ExtensionBlock(
                    TOPFD_JS_METADATA_EXTENSION_TYPE,
                    "1",
                    {
                        "owner": "topfd_js",
                        "schema_name": TOPFD_JS_METADATA_EXTENSION_TYPE,
                        "schema_version": 1,
                        "record_count": len(metadata_records),
                        "spectra": metadata_records,
                    },
                )
            ],
        )
        self.last_report = RealTopfdJsExecutionReport(
            spectrum_count=len(spectrum_blocks),
            ms1_count=ms1_count,
            ms2_count=ms2_count,
        )


def _load_topfd_spectra(
    root: Path,
    *,
    compact: bool,
    temporary_directory: Path | None,
) -> tuple[_TopfdSpectrum, ...]:
    spool: _ArraySpool | None = None
    if compact and temporary_directory is not None:
        spool = _ArraySpool(temporary_directory / "topfd-js-arrays.bin")
    records: list[_TopfdSpectrum] = []
    try:
        for ms_level, subdir in ((1, "ms1_json"), (2, "ms2_json")):
            directory = root / "topfd" / subdir
            files = sorted(
                (path for path in directory.glob("spectrum*.js") if path.is_file()),
                key=_spectrum_sort_key,
            )
            for source_index, path in enumerate(files):
                records.append(
                    _load_spectrum(
                        path,
                        ms_level=ms_level,
                        source_index=source_index,
                        spool=spool,
                    )
                )
    finally:
        if spool is not None:
            spool.close()
    return tuple(sorted(records, key=lambda item: (item.scan, item.ms_level, item.source_id)))


def _load_spectrum(
    path: Path,
    *,
    ms_level: int,
    source_index: int,
    spool: "_ArraySpool | None",
) -> _TopfdSpectrum:
    raw = _load_js_object(path)
    peaks = raw.get("peaks")
    if not isinstance(peaks, list):
        raise InvalidSourceError(f"TopFD spectrum has invalid peaks: {path.name}")
    mz: list[float] = []
    intensity: list[float] = []
    for peak in peaks:
        if not isinstance(peak, dict):
            continue
        parsed_mz = _finite_float(peak.get("mz"))
        parsed_intensity = _finite_float(peak.get("intensity"))
        if parsed_mz is None or parsed_intensity is None:
            continue
        mz.append(parsed_mz)
        intensity.append(max(0.0, parsed_intensity))
    tic = float(sum(intensity))
    bpc = float(max(intensity)) if intensity else 0.0
    mz_values: Sequence[float]
    intensity_values: Sequence[float]
    if spool is None:
        mz_values = tuple(mz)
        intensity_values = tuple(intensity)
    else:
        mz_values = spool.write(mz)
        intensity_values = spool.write(intensity)
    scan = _required_int(raw.get("scan"), f"{path.name}.scan")
    rt = _required_float(raw.get("retention_time"), f"{path.name}.retention_time")
    return _TopfdSpectrum(
        source_path=path,
        source_index=source_index,
        ms_level=ms_level,
        source_id=_required_int(raw.get("id"), f"{path.name}.id"),
        scan=scan,
        rt_seconds=max(0.0, rt),
        target_mz=_finite_float(raw.get("target_mz")),
        lower_mz=_finite_float(raw.get("min_mz")),
        upper_mz=_finite_float(raw.get("max_mz")),
        mz=mz_values,
        intensity=intensity_values,
        tic=tic,
        bpc=bpc,
    )


def _precursor_block(precursor_id: str, spectrum_id: str, spectrum: _TopfdSpectrum) -> PrecursorBlock:
    if (
        spectrum.lower_mz is not None
        and spectrum.upper_mz is not None
        and spectrum.lower_mz >= 0
        and spectrum.lower_mz < spectrum.upper_mz
    ):
        return PrecursorBlock(
            precursor_id=precursor_id,
            spectrum_id=spectrum_id,
            precursor_mz=None,
            charge=None,
            intensity=None,
            precursor_kind=ISOLATION_WINDOW_KIND,
            isolation_lower_mz=spectrum.lower_mz,
            isolation_upper_mz=spectrum.upper_mz,
        )
    target = spectrum.target_mz if spectrum.target_mz is not None and spectrum.target_mz >= 0 else 0.0
    return PrecursorBlock(
        precursor_id=precursor_id,
        spectrum_id=spectrum_id,
        precursor_mz=target,
        charge=1,
        intensity=0.0,
    )


def _load_js_object(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig")
        body = _ASSIGNMENT.sub("", text, count=1).strip()
        if body.endswith(";"):
            body = body[:-1].rstrip()
        value = json.loads(body)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidSourceError(f"Cannot parse TopFD spectrum JS {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise InvalidSourceError(f"TopFD spectrum JS must contain an object: {path.name}")
    return value


def _spectrum_sort_key(path: Path) -> tuple[int, str]:
    match = _SPECTRUM_NAME.fullmatch(path.name)
    return (int(match.group(1)) if match else 2**31, path.name)


def _values(values: Sequence[float], *, compact: bool) -> NormalizedFloat64List | np.ndarray:
    if isinstance(values, NativeFloat64Array):
        return values
    if compact:
        return np.asarray(values, dtype="<f8")
    return NormalizedFloat64List(values)


class _ArraySpool:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w+b")
        self._closed = False

    def write(self, values: Sequence[float]) -> NativeFloat64Array:
        array = np.asarray(values, dtype="<f8")
        if array.ndim != 1:
            raise InvalidSourceError("TopFD array must be one-dimensional")
        offset = self._handle.tell()
        raw = array.tobytes()
        checksum = hashlib.sha256(raw).hexdigest()
        self._handle.write(raw)
        self._handle.flush()
        mapped = np.memmap(
            self.path,
            dtype="<f8",
            mode="r",
            offset=offset,
            shape=(array.size,),
        )
        return NativeFloat64Array(mapped, checksum=checksum)

    def close(self) -> None:
        if not self._closed:
            self._handle.close()
            self._closed = True


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _required_float(value: Any, label: str) -> float:
    parsed = _finite_float(value)
    if parsed is None:
        raise InvalidSourceError(f"TopFD spectrum is missing finite {label}")
    return parsed


def _required_int(value: Any, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidSourceError(f"TopFD spectrum is missing integer {label}") from exc
    return parsed


def _relative_label(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name
