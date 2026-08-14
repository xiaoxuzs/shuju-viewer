from __future__ import annotations

import base64
import math
import mmap
import re
import zlib
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from lxml import etree
from pyteomics import mzml

from .exceptions import MzmlParseError, MzmlSchemaError
from .mzml_admission import (
    AuxiliaryArrayFeature,
    ChromatogramFeature,
    MzmlFeatureProfile,
    SpectrumFeature,
    normalize_time_seconds,
    time_unit_scale,
)
from .mzml_schema import (
    ArrayCompression,
    ChromatogramMetadataV1,
    ChromatogramType,
    CvParamV1,
    MzmlMetadataV1,
    MzmlRunMetadataV1,
    MzmlSourceMetadataV1,
    NumericDtype,
    Polarity,
    SpectrumMetadataV1,
    SpectrumRepresentation,
    TraceableEntityV1,
)
from .native_mzml import (
    NativeMzmlSpectrumRecord,
    fixed_native_mzml_executable,
    read_native_mzml_records,
)

THERMO_NATIVE_ID_ACCESSION = "MS:1000768"
_SCAN_PATTERN = re.compile(r"(?<!\S)scan=(\d+)(?!\S)")

_DTYPE_ACCESSIONS = {
    "MS:1000521": "float32",
    "MS:1000523": "float64",
    "MS:1000519": "int32",
    "MS:1000522": "int64",
}
_COMPRESSION_ACCESSIONS = {
    "MS:1000576": "none",
    "MS:1000574": "zlib",
}
_ARRAY_ACCESSIONS = {
    "MS:1000514": "mz",
    "MS:1000515": "intensity",
    "MS:1000595": "time",
}
_CHROMATOGRAM_ACCESSIONS = {
    "MS:1000235": "tic",
    "MS:1000628": "bpc",
}
_UNIT_ACCESSIONS = {
    "electronvolt": "UO:0000266",
}


@dataclass(frozen=True, slots=True)
class ParsedMzmlRun:
    run_id: str
    default_instrument_configuration_ref: str | None
    default_source_file_ref: str | None
    sample_ref: str | None
    start_time_stamp: str | None


@dataclass(frozen=True, slots=True)
class ParsedMzmlPrecursor:
    selected_ion_count: int
    source_spectrum_ref: str | None
    selected_ion_mz: float | None
    charge: int | None
    charge_present: bool
    charge_explicit_zero: bool
    intensity: float | None
    isolation_target_mz: float | None
    isolation_lower_offset: float | None
    isolation_upper_offset: float | None
    activation_methods: tuple[CvParamV1, ...]
    collision_energy: float | None
    collision_energy_unit_accession: str | None
    collision_energy_unit_name: str | None


@dataclass(frozen=True, slots=True)
class ParsedMzmlSpectrum:
    source_index: int
    native_id: str
    scan_number: int | None
    scan_number_proven: bool
    ms_level: int
    rt_seconds: float | None
    source_rt_value: float | None
    source_rt_unit_accession: str | None
    source_rt_unit_name: str | None
    mz_values: Sequence[float]
    intensity_values: Sequence[float]
    source_mz_dtype: str | None
    source_intensity_dtype: str | None
    source_mz_compression: str | None
    source_intensity_compression: str | None
    representation: str
    polarity: str | None
    default_array_length: int
    precursors: tuple[ParsedMzmlPrecursor, ...]
    auxiliary_arrays: tuple[AuxiliaryArrayFeature, ...]
    has_dia_semantics: bool
    has_ion_mobility: bool
    total_ion_current: float | None
    base_peak_mz: float | None
    base_peak_intensity: float | None
    lowest_observed_mz: float | None
    highest_observed_mz: float | None
    scan_window_lower: float | None
    scan_window_upper: float | None
    filter_string: str | None
    instrument_configuration_ref: str | None
    data_processing_ref: str | None

    @property
    def precursor_count(self) -> int:
        return len(self.precursors)

    @property
    def selected_ion_count(self) -> int:
        return sum(item.selected_ion_count for item in self.precursors)

    @property
    def selected_ion_mz(self) -> float | None:
        return self.precursors[0].selected_ion_mz if len(self.precursors) == 1 else None

    @property
    def charge(self) -> int | None:
        return self.precursors[0].charge if len(self.precursors) == 1 else None

    @property
    def selected_ion_intensity(self) -> float | None:
        return self.precursors[0].intensity if len(self.precursors) == 1 else None

    def to_feature(self) -> SpectrumFeature:
        mz_values = np.asarray(self.mz_values)
        intensity_values = np.asarray(self.intensity_values)
        return SpectrumFeature(
            native_id=self.native_id,
            scan_number=self.scan_number,
            scan_number_proven=self.scan_number_proven,
            ms_level=self.ms_level,
            rt_value=self.source_rt_value,
            rt_unit_accession=self.source_rt_unit_accession,
            rt_unit_name=self.source_rt_unit_name,
            representation=self.representation,
            polarity=self.polarity,
            precursor_count=self.precursor_count,
            selected_ion_count=self.selected_ion_count,
            selected_ion_mz=self.selected_ion_mz,
            charge=self.charge,
            selected_ion_intensity=self.selected_ion_intensity,
            has_mz_array=self.source_mz_dtype is not None,
            has_intensity_array=self.source_intensity_dtype is not None,
            mz_array_length=len(self.mz_values) if self.source_mz_dtype is not None else None,
            intensity_array_length=len(self.intensity_values) if self.source_intensity_dtype is not None else None,
            mz_dtype=self.source_mz_dtype,
            intensity_dtype=self.source_intensity_dtype,
            mz_compression=self.source_mz_compression,
            intensity_compression=self.source_intensity_compression,
            arrays_are_finite=bool(
                np.all(np.isfinite(mz_values))
                and np.all(np.isfinite(intensity_values))
            ),
            minimum_mz=float(np.min(mz_values)) if mz_values.size else None,
            auxiliary_arrays=self.auxiliary_arrays,
            has_dia_semantics=self.has_dia_semantics,
            has_ion_mobility=self.has_ion_mobility,
        )


@dataclass(frozen=True, slots=True)
class ParsedMzmlAuxiliaryArray:
    accession: str
    name: str
    dtype: str | None
    compression: str | None
    unit_accession: str | None
    unit_name: str | None
    values: Sequence[int | float]

    def to_feature(self) -> AuxiliaryArrayFeature:
        return AuxiliaryArrayFeature(
            self.accession,
            self.name,
            self.dtype or "unknown",
            self.unit_accession,
            self.unit_name,
        )


@dataclass(frozen=True, slots=True)
class ParsedMzmlChromatogram:
    source_index: int
    native_id: str
    chromatogram_type: str
    time_values_seconds: Sequence[float]
    intensity_values: Sequence[float]
    source_time_values: Sequence[float]
    source_time_unit_accession: str | None
    source_time_unit_name: str | None
    source_time_dtype: str | None
    source_intensity_dtype: str | None
    source_time_compression: str | None
    source_intensity_compression: str | None
    default_array_length: int
    data_processing_ref: str | None
    auxiliary_arrays: tuple[ParsedMzmlAuxiliaryArray, ...]
    has_precursor_semantics: bool
    has_product_semantics: bool

    def to_feature(self) -> ChromatogramFeature:
        return ChromatogramFeature(
            chromatogram_id=self.native_id,
            chromatogram_type=self.chromatogram_type,
            time_array_length=len(self.source_time_values) if self.source_time_dtype is not None else None,
            intensity_array_length=len(self.intensity_values) if self.source_intensity_dtype is not None else None,
            time_dtype=self.source_time_dtype,
            intensity_dtype=self.source_intensity_dtype,
            time_compression=self.source_time_compression,
            intensity_compression=self.source_intensity_compression,
            time_unit_accession=self.source_time_unit_accession,
            time_unit_name=self.source_time_unit_name,
            auxiliary_arrays=tuple(item.to_feature() for item in self.auxiliary_arrays),
            has_precursor_semantics=self.has_precursor_semantics,
            has_product_semantics=self.has_product_semantics,
        )


@dataclass(frozen=True, slots=True)
class ParsedMzmlDocument:
    source_path: Path
    run: ParsedMzmlRun
    spectra: tuple[ParsedMzmlSpectrum, ...]
    chromatograms: tuple[ParsedMzmlChromatogram, ...]
    feature_profile: MzmlFeatureProfile
    metadata_schema: MzmlMetadataV1 | None


@dataclass(frozen=True, slots=True)
class _DocumentStructure:
    indexed: bool
    mzml_version: str
    native_id_format_accession: str | None
    native_id_format_name: str | None
    runs: tuple[ParsedMzmlRun, ...]
    chromatograms: tuple["_ChromatogramStructure", ...]
    spectrum_auxiliaries: tuple[tuple[int, tuple[AuxiliaryArrayFeature, ...]], ...]
    instruments: tuple[TraceableEntityV1, ...]
    software: tuple[TraceableEntityV1, ...]
    data_processing: tuple[TraceableEntityV1, ...]


@dataclass(frozen=True, slots=True)
class _ArrayDescriptor:
    kind: str
    accession: str
    name: str
    dtype: str | None
    compression: str | None
    unit_accession: str | None
    unit_name: str | None


@dataclass(frozen=True, slots=True)
class _ChromatogramStructure:
    source_index: int
    native_id: str
    chromatogram_type: str
    default_array_length: int
    data_processing_ref: str | None
    arrays: tuple[_ArrayDescriptor, ...]
    has_precursor_semantics: bool
    has_product_semantics: bool


def parse_mzml(
    file_path: str | Path,
    *,
    worker_threads: int = 6,
) -> ParsedMzmlDocument:
    path = Path(file_path)
    if type(worker_threads) is not int or not 1 <= worker_threads <= 32:
        raise ValueError("worker_threads must be an integer from 1 to 32")
    try:
        use_fast_path = path.stat().st_size >= 64 * 1024 * 1024
    except OSError as exc:
        raise MzmlParseError("MZML_READ_FAILED", str(exc), str(path)) from exc
    if use_fast_path:
        executable = fixed_native_mzml_executable()
        if executable is not None:
            try:
                return _parse_mzml_native(
                    path,
                    worker_threads=worker_threads,
                    executable=executable,
                )
            except MzmlParseError:
                pass
        return _parse_mzml_fast(path, worker_threads=worker_threads)
    return _parse_mzml_legacy(path)


def _parse_mzml_legacy(file_path: str | Path) -> ParsedMzmlDocument:
    path = Path(file_path)
    try:
        structure = _inspect_document_structure(path)
        auxiliaries = dict(structure.spectrum_auxiliaries)
        parsed_spectra: list[ParsedMzmlSpectrum] = []
        with mzml.MzML(str(path), use_index=True, decode_binary=False) as reader:
            for record in reader:
                parsed_spectra.append(
                    _parse_spectrum(
                        record,
                        structure.native_id_format_accession,
                        auxiliaries.get(int(record.get("index", len(parsed_spectra))), ()),
                    )
                )
        parsed_chromatograms: list[ParsedMzmlChromatogram] = []
        if structure.chromatograms:
            by_index = {item.source_index: item for item in structure.chromatograms}
            with mzml.MzML(str(path), use_index=True, decode_binary=False) as reader:
                for position, record in enumerate(reader.iterfind("chromatogram")):
                    source_index = _plain_int(record.get("index"), position)
                    descriptor = by_index.get(source_index)
                    if descriptor is None:
                        raise MzmlParseError(
                            "CHROMATOGRAM_STRUCTURE_MISMATCH",
                            "Pyteomics chromatogram has no matching XML structure record",
                            f"chromatogram[{position}]",
                        )
                    parsed_chromatograms.append(_parse_chromatogram(record, descriptor))
    except MzmlParseError:
        raise
    except Exception as exc:
        raise MzmlParseError("MZML_READ_FAILED", str(exc), str(path)) from exc

    run = structure.runs[0] if structure.runs else ParsedMzmlRun("", None, None, None, None)
    spectra = tuple(parsed_spectra)
    chromatograms = tuple(parsed_chromatograms)
    profile = MzmlFeatureProfile(
        indexed=structure.indexed,
        run_count=len(structure.runs),
        mzml_version=structure.mzml_version,
        native_id_format_accession=structure.native_id_format_accession,
        native_id_format_name=structure.native_id_format_name,
        spectra=tuple(item.to_feature() for item in spectra),
        chromatograms=tuple(item.to_feature() for item in chromatograms),
    )
    metadata_schema = _build_metadata_if_representable(structure, run, spectra, chromatograms)
    return ParsedMzmlDocument(path, run, spectra, chromatograms, profile, metadata_schema)


@dataclass(frozen=True, slots=True)
class _FastArrayRequest:
    kind: str
    dtype: str | None
    compression: str | None
    encoded: str


@dataclass(frozen=True, slots=True)
class _FastSpectrumPending:
    fields: dict[str, object]
    future: Future[dict[str, np.ndarray]]


def _parse_mzml_native(
    path: Path,
    *,
    worker_threads: int,
    executable: Path,
) -> ParsedMzmlDocument:
    try:
        with path.open("rb") as stream:
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
                header = _read_fast_mzml_header(source)
                if header is None:
                    raise MzmlParseError(
                        "NATIVE_MZML_UNSUPPORTED",
                        "mzML structure is outside the native fast-path contract",
                        str(path),
                    )
                (
                    indexed,
                    mzml_version,
                    native_formats,
                    runs,
                    instruments,
                    software,
                    data_processing,
                    _spectrum_list_start,
                    spectrum_list_end,
                    expected_spectra,
                ) = header
                native_format_accession = (
                    native_formats[0][0]
                    if len(native_formats) == 1
                    else None
                )
                native_records = read_native_mzml_records(
                    path,
                    worker_threads=worker_threads,
                    executable=executable,
                )
                if len(native_records) != expected_spectra:
                    raise MzmlParseError(
                        "NATIVE_PROTOCOL_ERROR",
                        "native spectrum count does not match spectrumList.count",
                        "native_stream.spectrum_count",
                    )
                spectra = [
                    _native_spectrum(item, native_format_accession)
                    for item in native_records
                ]
                spectrum_auxiliaries = [
                    (item.source_index, item.auxiliary_arrays)
                    for item in spectra
                ]
                chromatogram_structures: list[_ChromatogramStructure] = []
                chromatograms: list[ParsedMzmlChromatogram] = []
                position = spectrum_list_end
                while True:
                    start = source.find(b"<chromatogram ", position)
                    if start < 0:
                        break
                    closing = source.find(b"</chromatogram>", start)
                    if closing < 0:
                        raise MzmlParseError(
                            "MZML_READ_FAILED",
                            "chromatogram closing tag is missing",
                            "chromatogram",
                        )
                    end = closing + len(b"</chromatogram>")
                    element = etree.fromstring(source[start:end])
                    structure = _chromatogram_structure(element)
                    chromatogram_structures.append(structure)
                    chromatograms.append(
                        _parse_fast_chromatogram(element, structure)
                    )
                    position = end
    except MzmlParseError:
        raise
    except Exception as exc:
        raise MzmlParseError(
            "NATIVE_MZML_FAILED",
            str(exc),
            str(path),
        ) from exc
    return _build_fast_document(
        path=path,
        indexed=indexed,
        mzml_version=mzml_version,
        native_formats=native_formats,
        runs=runs,
        chromatogram_structures=chromatogram_structures,
        spectrum_auxiliaries=spectrum_auxiliaries,
        instruments=instruments,
        software=software,
        data_processing=data_processing,
        spectra=spectra,
        chromatograms=chromatograms,
    )


def _native_spectrum(
    record: NativeMzmlSpectrumRecord,
    native_id_format_accession: str | None,
) -> ParsedMzmlSpectrum:
    fields = record.fields
    source_index = _plain_int(fields.get("source_index"), -1)
    native_id = _native_optional_string(
        fields.get("native_id"),
        f"spectrum[{source_index}].native_id",
    ) or ""
    scan_number, scan_number_proven = _extract_scan_number(
        native_id,
        native_id_format_accession,
    )
    source_rt_value = _plain_optional_float(fields.get("source_rt_value"))
    source_rt_unit_accession = _native_optional_string(
        fields.get("source_rt_unit_accession"),
        f"spectrum[{source_index}].source_rt_unit_accession",
    )
    source_rt_unit_name = _native_optional_string(
        fields.get("source_rt_unit_name"),
        f"spectrum[{source_index}].source_rt_unit_name",
    )
    rt_seconds = None
    if (
        source_rt_value is not None
        and time_unit_scale(
            source_rt_unit_accession,
            source_rt_unit_name,
        )
        is not None
    ):
        rt_seconds = normalize_time_seconds(
            source_rt_value,
            source_rt_unit_accession,
            source_rt_unit_name,
        )
    raw_precursors = fields.get("precursors")
    if not isinstance(raw_precursors, list):
        raise MzmlParseError(
            "NATIVE_PROTOCOL_ERROR",
            "native precursor metadata must be a list",
            f"spectrum[{source_index}].precursors",
        )
    precursors = tuple(
        _native_precursor(item, source_index, position)
        for position, item in enumerate(raw_precursors)
    )
    raw_auxiliaries = fields.get("auxiliary_arrays")
    if not isinstance(raw_auxiliaries, list):
        raise MzmlParseError(
            "NATIVE_PROTOCOL_ERROR",
            "native auxiliary-array metadata must be a list",
            f"spectrum[{source_index}].auxiliary_arrays",
        )
    auxiliaries = tuple(
        _native_auxiliary(item, source_index, position)
        for position, item in enumerate(raw_auxiliaries)
    )
    return ParsedMzmlSpectrum(
        source_index=source_index,
        native_id=native_id,
        scan_number=scan_number,
        scan_number_proven=scan_number_proven,
        ms_level=_plain_int(fields.get("ms_level"), 0),
        rt_seconds=rt_seconds,
        source_rt_value=source_rt_value,
        source_rt_unit_accession=source_rt_unit_accession,
        source_rt_unit_name=source_rt_unit_name,
        mz_values=record.mz_values,
        intensity_values=record.intensity_values,
        source_mz_dtype=_native_optional_string(
            fields.get("source_mz_dtype"),
            f"spectrum[{source_index}].source_mz_dtype",
        ),
        source_intensity_dtype=_native_optional_string(
            fields.get("source_intensity_dtype"),
            f"spectrum[{source_index}].source_intensity_dtype",
        ),
        source_mz_compression=_native_optional_string(
            fields.get("source_mz_compression"),
            f"spectrum[{source_index}].source_mz_compression",
        ),
        source_intensity_compression=_native_optional_string(
            fields.get("source_intensity_compression"),
            f"spectrum[{source_index}].source_intensity_compression",
        ),
        representation=_native_optional_string(
            fields.get("representation"),
            f"spectrum[{source_index}].representation",
        )
        or "unknown",
        polarity=_native_optional_string(
            fields.get("polarity"),
            f"spectrum[{source_index}].polarity",
        ),
        default_array_length=_plain_int(
            fields.get("default_array_length"),
            -1,
        ),
        precursors=precursors,
        auxiliary_arrays=auxiliaries,
        has_dia_semantics=_native_bool(
            fields.get("has_dia_semantics"),
            f"spectrum[{source_index}].has_dia_semantics",
        ),
        has_ion_mobility=_native_bool(
            fields.get("has_ion_mobility"),
            f"spectrum[{source_index}].has_ion_mobility",
        ),
        total_ion_current=_plain_optional_float(
            fields.get("total_ion_current")
        ),
        base_peak_mz=_plain_optional_float(fields.get("base_peak_mz")),
        base_peak_intensity=_plain_optional_float(
            fields.get("base_peak_intensity")
        ),
        lowest_observed_mz=_plain_optional_float(
            fields.get("lowest_observed_mz")
        ),
        highest_observed_mz=_plain_optional_float(
            fields.get("highest_observed_mz")
        ),
        scan_window_lower=_plain_optional_float(
            fields.get("scan_window_lower")
        ),
        scan_window_upper=_plain_optional_float(
            fields.get("scan_window_upper")
        ),
        filter_string=_native_optional_string(
            fields.get("filter_string"),
            f"spectrum[{source_index}].filter_string",
        ),
        instrument_configuration_ref=_native_optional_string(
            fields.get("instrument_configuration_ref"),
            f"spectrum[{source_index}].instrument_configuration_ref",
        ),
        data_processing_ref=_native_optional_string(
            fields.get("data_processing_ref"),
            f"spectrum[{source_index}].data_processing_ref",
        ),
    )


def _native_precursor(
    value: object,
    source_index: int,
    position: int,
) -> ParsedMzmlPrecursor:
    location = f"spectrum[{source_index}].precursor[{position}]"
    if not isinstance(value, dict):
        raise MzmlParseError(
            "NATIVE_PROTOCOL_ERROR",
            "native precursor metadata must be an object",
            location,
        )
    charge_present = _native_bool(
        value.get("charge_present"),
        f"{location}.charge_present",
    )
    parsed_charge = _plain_optional_int(value.get("charge"))
    charge = None if parsed_charge == 0 else parsed_charge
    activation = value.get("activation_methods")
    if not isinstance(activation, list):
        raise MzmlParseError(
            "NATIVE_PROTOCOL_ERROR",
            "native activation methods must be a list",
            f"{location}.activation_methods",
        )
    activation_methods = tuple(
        _native_cv_param(item, f"{location}.activation_methods[{index}]")
        for index, item in enumerate(activation)
    )
    result = ParsedMzmlPrecursor(
        selected_ion_count=_plain_int(
            value.get("selected_ion_count"),
            0,
        ),
        source_spectrum_ref=_native_optional_string(
            value.get("source_spectrum_ref"),
            f"{location}.source_spectrum_ref",
        ),
        selected_ion_mz=_plain_optional_float(
            value.get("selected_ion_mz")
        ),
        charge=charge,
        charge_present=charge_present,
        charge_explicit_zero=charge_present and charge is None,
        intensity=_plain_optional_float(value.get("intensity")),
        isolation_target_mz=_plain_optional_float(
            value.get("isolation_target_mz")
        ),
        isolation_lower_offset=_plain_optional_float(
            value.get("isolation_lower_offset")
        ),
        isolation_upper_offset=_plain_optional_float(
            value.get("isolation_upper_offset")
        ),
        activation_methods=activation_methods,
        collision_energy=_plain_optional_float(
            value.get("collision_energy")
        ),
        collision_energy_unit_accession=_native_optional_string(
            value.get("collision_energy_unit_accession"),
            f"{location}.collision_energy_unit_accession",
        ),
        collision_energy_unit_name=_native_optional_string(
            value.get("collision_energy_unit_name"),
            f"{location}.collision_energy_unit_name",
        ),
    )
    for field_name, nonnegative in (
        ("selected_ion_mz", True),
        ("intensity", False),
        ("isolation_target_mz", False),
        ("isolation_lower_offset", True),
        ("isolation_upper_offset", True),
        ("collision_energy", False),
    ):
        _validate_precursor_number(
            getattr(result, field_name),
            f"{location}.{field_name}",
            nonnegative=nonnegative,
        )
    return result


def _native_cv_param(value: object, location: str) -> CvParamV1:
    if not isinstance(value, dict):
        raise MzmlParseError(
            "NATIVE_PROTOCOL_ERROR",
            "native CV parameter must be an object",
            location,
        )
    return CvParamV1(
        accession=_native_optional_string(
            value.get("accession"),
            f"{location}.accession",
        )
        or "",
        name=_native_optional_string(
            value.get("name"),
            f"{location}.name",
        )
        or "",
        value=_native_optional_string(
            value.get("value"),
            f"{location}.value",
        ),
        unit_accession=_native_optional_string(
            value.get("unit_accession"),
            f"{location}.unit_accession",
        ),
        unit_name=_native_optional_string(
            value.get("unit_name"),
            f"{location}.unit_name",
        ),
    )


def _native_auxiliary(
    value: object,
    source_index: int,
    position: int,
) -> AuxiliaryArrayFeature:
    location = f"spectrum[{source_index}].auxiliary_arrays[{position}]"
    if not isinstance(value, dict):
        raise MzmlParseError(
            "NATIVE_PROTOCOL_ERROR",
            "native auxiliary-array metadata must be an object",
            location,
        )
    return AuxiliaryArrayFeature(
        accession=_native_optional_string(
            value.get("accession"),
            f"{location}.accession",
        )
        or "",
        name=_native_optional_string(
            value.get("name"),
            f"{location}.name",
        )
        or "",
        dtype=_native_optional_string(
            value.get("dtype"),
            f"{location}.dtype",
        )
        or "unknown",
        unit_accession=_native_optional_string(
            value.get("unit_accession"),
            f"{location}.unit_accession",
        ),
        unit_name=_native_optional_string(
            value.get("unit_name"),
            f"{location}.unit_name",
        ),
    )


def _native_optional_string(value: object, location: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MzmlParseError(
            "NATIVE_PROTOCOL_ERROR",
            "native metadata field must be a string or null",
            location,
        )
    return value


def _native_bool(value: object, location: str) -> bool:
    if type(value) is not bool:
        raise MzmlParseError(
            "NATIVE_PROTOCOL_ERROR",
            "native metadata field must be a boolean",
            location,
        )
    return value


def _parse_mzml_fast(
    path: Path,
    *,
    worker_threads: int,
) -> ParsedMzmlDocument:
    try:
        with path.open("rb") as stream:
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
                header = _read_fast_mzml_header(source)
                if header is None:
                    return _parse_mzml_fast_iterparse(
                        path,
                        worker_threads=worker_threads,
                    )
                (
                    indexed,
                    mzml_version,
                    native_formats,
                    runs,
                    instruments,
                    software,
                    data_processing,
                    spectrum_list_start,
                    spectrum_list_end,
                    expected_spectra,
                ) = header
                native_format_accession = (
                    native_formats[0][0]
                    if len(native_formats) == 1
                    else None
                )
                spectra: list[ParsedMzmlSpectrum] = []
                spectrum_auxiliaries: list[
                    tuple[int, tuple[AuxiliaryArrayFeature, ...]]
                ] = []
                pending: deque[
                    Future[
                        tuple[
                            ParsedMzmlSpectrum,
                            tuple[AuxiliaryArrayFeature, ...],
                        ]
                    ]
                ] = deque()
                max_pending = max(worker_threads * 8, 8)
                position = spectrum_list_start
                scanned = 0
                with ThreadPoolExecutor(
                    max_workers=worker_threads,
                    thread_name_prefix="zp-mzml-spectrum",
                ) as executor:
                    while True:
                        start = source.find(b"<spectrum ", position)
                        if start < 0 or start >= spectrum_list_end:
                            break
                        closing = source.find(b"</spectrum>", start)
                        if closing < 0 or closing >= spectrum_list_end:
                            break
                        end = closing + len(b"</spectrum>")
                        pending.append(
                            executor.submit(
                                _parse_fast_spectrum_bytes,
                                source[start:end],
                                native_format_accession,
                            )
                        )
                        scanned += 1
                        position = end
                        if len(pending) >= max_pending:
                            spectrum, auxiliaries = pending.popleft().result()
                            spectra.append(spectrum)
                            spectrum_auxiliaries.append(
                                (spectrum.source_index, auxiliaries)
                            )
                    while pending:
                        spectrum, auxiliaries = pending.popleft().result()
                        spectra.append(spectrum)
                        spectrum_auxiliaries.append(
                            (spectrum.source_index, auxiliaries)
                        )
                if scanned != expected_spectra:
                    del spectra
                    return _parse_mzml_fast_iterparse(
                        path,
                        worker_threads=worker_threads,
                    )
                chromatogram_structures: list[_ChromatogramStructure] = []
                chromatograms: list[ParsedMzmlChromatogram] = []
                position = spectrum_list_end
                while True:
                    start = source.find(b"<chromatogram ", position)
                    if start < 0:
                        break
                    closing = source.find(b"</chromatogram>", start)
                    if closing < 0:
                        break
                    end = closing + len(b"</chromatogram>")
                    element = etree.fromstring(source[start:end])
                    structure = _chromatogram_structure(element)
                    chromatogram_structures.append(structure)
                    chromatograms.append(
                        _parse_fast_chromatogram(element, structure)
                    )
                    position = end
    except MzmlParseError:
        raise
    except Exception:
        return _parse_mzml_fast_iterparse(
            path,
            worker_threads=worker_threads,
        )
    return _build_fast_document(
        path=path,
        indexed=indexed,
        mzml_version=mzml_version,
        native_formats=native_formats,
        runs=runs,
        chromatogram_structures=chromatogram_structures,
        spectrum_auxiliaries=spectrum_auxiliaries,
        instruments=instruments,
        software=software,
        data_processing=data_processing,
        spectra=spectra,
        chromatograms=chromatograms,
    )


def _parse_mzml_fast_iterparse(
    path: Path,
    *,
    worker_threads: int,
) -> ParsedMzmlDocument:
    indexed = False
    mzml_version = ""
    native_formats: list[tuple[str, str]] = []
    runs: list[ParsedMzmlRun] = []
    chromatogram_structures: list[_ChromatogramStructure] = []
    spectrum_auxiliaries: list[
        tuple[int, tuple[AuxiliaryArrayFeature, ...]]
    ] = []
    instruments: list[TraceableEntityV1] = []
    software: list[TraceableEntityV1] = []
    data_processing: list[TraceableEntityV1] = []
    spectra: list[ParsedMzmlSpectrum] = []
    chromatograms: list[ParsedMzmlChromatogram] = []
    pending: deque[_FastSpectrumPending] = deque()
    first_element = True
    native_format_accession: str | None = None
    max_pending = max(worker_threads * 8, 8)

    try:
        with ThreadPoolExecutor(
            max_workers=worker_threads,
            thread_name_prefix="zp-mzml-decode",
        ) as executor:
            for event, element in etree.iterparse(
                str(path),
                events=("start", "end"),
                huge_tree=True,
            ):
                tag = _local_name(element.tag)
                if event == "start":
                    if first_element:
                        indexed = tag == "indexedmzML"
                        first_element = False
                    if tag == "mzML":
                        mzml_version = element.attrib.get("version", "")
                    elif tag == "run":
                        runs.append(
                            ParsedMzmlRun(
                                run_id=element.attrib.get("id", ""),
                                default_instrument_configuration_ref=element.attrib.get(
                                    "defaultInstrumentConfigurationRef"
                                ),
                                default_source_file_ref=element.attrib.get(
                                    "defaultSourceFileRef"
                                ),
                                sample_ref=element.attrib.get("sampleRef"),
                                start_time_stamp=element.attrib.get(
                                    "startTimeStamp"
                                ),
                            )
                        )
                    continue

                if tag == "sourceFile":
                    for cv_param in _cv_params(element):
                        if cv_param.name.endswith("nativeID format"):
                            native_formats.append(
                                (cv_param.accession, cv_param.name)
                            )
                    _release_lxml_element(element)
                    if len(native_formats) == 1:
                        native_format_accession = native_formats[0][0]
                elif tag == "instrumentConfiguration":
                    instruments.append(_entity(element))
                    _release_lxml_element(element)
                elif tag == "software":
                    software.append(_entity(element))
                    _release_lxml_element(element)
                elif tag == "dataProcessing":
                    data_processing.append(_entity(element))
                    _release_lxml_element(element)
                elif tag == "spectrum":
                    fields, requests, auxiliaries = _fast_spectrum_fields(
                        element,
                        native_format_accession,
                    )
                    source_index = int(fields["source_index"])
                    spectrum_auxiliaries.append((source_index, auxiliaries))
                    pending.append(
                        _FastSpectrumPending(
                            fields,
                            executor.submit(_decode_fast_arrays, requests),
                        )
                    )
                    _release_lxml_element(element)
                    if len(pending) >= max_pending:
                        spectra.append(_finish_fast_spectrum(pending.popleft()))
                elif tag == "chromatogram":
                    structure = _chromatogram_structure(element)
                    chromatogram_structures.append(structure)
                    chromatograms.append(
                        _parse_fast_chromatogram(element, structure)
                    )
                    _release_lxml_element(element)
            while pending:
                spectra.append(_finish_fast_spectrum(pending.popleft()))
    except MzmlParseError:
        raise
    except Exception as exc:
        raise MzmlParseError("MZML_READ_FAILED", str(exc), str(path)) from exc

    return _build_fast_document(
        path=path,
        indexed=indexed,
        mzml_version=mzml_version,
        native_formats=native_formats,
        runs=runs,
        chromatogram_structures=chromatogram_structures,
        spectrum_auxiliaries=spectrum_auxiliaries,
        instruments=instruments,
        software=software,
        data_processing=data_processing,
        spectra=spectra,
        chromatograms=chromatograms,
    )


def _read_fast_mzml_header(source: mmap.mmap) -> tuple[Any, ...] | None:
    mzml_start = source.find(b"<mzML ")
    run_start = source.find(b"<run ", mzml_start)
    spectrum_list_start = source.find(b"<spectrumList ", run_start)
    if min(mzml_start, run_start, spectrum_list_start) < 0:
        return None
    spectrum_list_tag_end = source.find(b">", spectrum_list_start)
    spectrum_list_end = source.find(
        b"</spectrumList>",
        spectrum_list_tag_end,
    )
    run_tag_end = source.find(b">", run_start)
    if min(spectrum_list_tag_end, spectrum_list_end, run_tag_end) < 0:
        return None
    try:
        metadata_root = etree.fromstring(
            source[mzml_start:run_start] + b"</mzML>"
        )
        run_element = etree.fromstring(
            source[run_start:run_tag_end] + b"/>"
        )
        spectrum_list_element = etree.fromstring(
            source[spectrum_list_start:spectrum_list_tag_end] + b"/>"
        )
    except etree.XMLSyntaxError:
        return None
    native_formats: list[tuple[str, str]] = []
    instruments: list[TraceableEntityV1] = []
    software: list[TraceableEntityV1] = []
    data_processing: list[TraceableEntityV1] = []
    for element in metadata_root.iter():
        tag = _local_name(element.tag)
        if tag == "sourceFile":
            for cv_param in _cv_params(element):
                if cv_param.name.endswith("nativeID format"):
                    native_formats.append(
                        (cv_param.accession, cv_param.name)
                    )
        elif tag == "instrumentConfiguration":
            instruments.append(_entity(element))
        elif tag == "software":
            software.append(_entity(element))
        elif tag == "dataProcessing":
            data_processing.append(_entity(element))
    runs = [
        ParsedMzmlRun(
            run_id=run_element.attrib.get("id", ""),
            default_instrument_configuration_ref=run_element.attrib.get(
                "defaultInstrumentConfigurationRef"
            ),
            default_source_file_ref=run_element.attrib.get(
                "defaultSourceFileRef"
            ),
            sample_ref=run_element.attrib.get("sampleRef"),
            start_time_stamp=run_element.attrib.get("startTimeStamp"),
        )
    ]
    expected_spectra = _plain_int(
        spectrum_list_element.attrib.get("count"),
        -1,
    )
    if expected_spectra < 0:
        return None
    return (
        source.find(b"<indexedmzML", 0, mzml_start) >= 0,
        metadata_root.attrib.get("version", ""),
        native_formats,
        runs,
        instruments,
        software,
        data_processing,
        spectrum_list_tag_end,
        spectrum_list_end,
        expected_spectra,
    )


def _parse_fast_spectrum_bytes(
    payload: bytes,
    native_id_format_accession: str | None,
) -> tuple[ParsedMzmlSpectrum, tuple[AuxiliaryArrayFeature, ...]]:
    try:
        element = etree.fromstring(payload)
    except etree.XMLSyntaxError as exc:
        raise MzmlParseError(
            "MZML_READ_FAILED",
            str(exc),
            "spectrum",
        ) from exc
    fields, requests, auxiliaries = _fast_spectrum_fields(
        element,
        native_id_format_accession,
    )
    arrays = _decode_fast_arrays(requests)
    return (
        ParsedMzmlSpectrum(
            **fields,
            mz_values=arrays.get("mz", np.empty(0, dtype="<f8")),
            intensity_values=arrays.get(
                "intensity",
                np.empty(0, dtype="<f8"),
            ),
        ),
        auxiliaries,
    )


def _build_fast_document(
    *,
    path: Path,
    indexed: bool,
    mzml_version: str,
    native_formats: list[tuple[str, str]],
    runs: list[ParsedMzmlRun],
    chromatogram_structures: list[_ChromatogramStructure],
    spectrum_auxiliaries: list[
        tuple[int, tuple[AuxiliaryArrayFeature, ...]]
    ],
    instruments: list[TraceableEntityV1],
    software: list[TraceableEntityV1],
    data_processing: list[TraceableEntityV1],
    spectra: list[ParsedMzmlSpectrum],
    chromatograms: list[ParsedMzmlChromatogram],
) -> ParsedMzmlDocument:
    native_format = (
        native_formats[0]
        if len(native_formats) == 1
        else (None, None)
    )
    structure = _DocumentStructure(
        indexed=indexed,
        mzml_version=mzml_version,
        native_id_format_accession=native_format[0],
        native_id_format_name=native_format[1],
        runs=tuple(runs),
        chromatograms=tuple(chromatogram_structures),
        spectrum_auxiliaries=tuple(spectrum_auxiliaries),
        instruments=tuple(instruments),
        software=tuple(software),
        data_processing=tuple(data_processing),
    )
    run = runs[0] if runs else ParsedMzmlRun("", None, None, None, None)
    spectrum_tuple = tuple(spectra)
    chromatogram_tuple = tuple(chromatograms)
    profile = MzmlFeatureProfile(
        indexed=indexed,
        run_count=len(runs),
        mzml_version=mzml_version,
        native_id_format_accession=native_format[0],
        native_id_format_name=native_format[1],
        spectra=tuple(item.to_feature() for item in spectrum_tuple),
        chromatograms=tuple(
            item.to_feature() for item in chromatogram_tuple
        ),
    )
    metadata_schema = _build_metadata_if_representable(
        structure,
        run,
        spectrum_tuple,
        chromatogram_tuple,
    )
    return ParsedMzmlDocument(
        path,
        run,
        spectrum_tuple,
        chromatogram_tuple,
        profile,
        metadata_schema,
    )


def _direct_children(element: Any, name: str) -> list[Any]:
    return [item for item in element if _is_tag(item.tag, name)]


def _nested_children(
    element: Any,
    container_name: str,
    item_name: str,
) -> list[Any]:
    containers = _direct_children(element, container_name)
    if len(containers) != 1:
        return []
    return _direct_children(containers[0], item_name)


def _fast_array_descriptor(binary_array: Any) -> _ArrayDescriptor:
    params = [
        child.attrib
        for child in binary_array
        if _is_tag(child.tag, "cvParam")
    ]
    dtype = next(
        (
            _DTYPE_ACCESSIONS[value.get("accession", "")]
            for value in params
            if value.get("accession") in _DTYPE_ACCESSIONS
        ),
        None,
    )
    compression = next(
        (
            _COMPRESSION_ACCESSIONS[value.get("accession", "")]
            for value in params
            if value.get("accession") in _COMPRESSION_ACCESSIONS
        ),
        None,
    )
    semantic = next(
        (
            value
            for value in params
            if value.get("accession") in _ARRAY_ACCESSIONS
            or value.get("accession") == "MS:1000786"
        ),
        None,
    )
    if semantic is None:
        return _ArrayDescriptor(
            "auxiliary",
            "",
            "unknown",
            dtype,
            compression,
            None,
            None,
        )
    accession = semantic.get("accession", "")
    return _ArrayDescriptor(
        _ARRAY_ACCESSIONS.get(accession, "auxiliary"),
        accession,
        semantic.get("value") or semantic.get("name", ""),
        dtype,
        compression,
        semantic.get("unitAccession"),
        semantic.get("unitName"),
    )


def _fast_spectrum_fields(
    element: Any,
    native_id_format_accession: str | None,
) -> tuple[
    dict[str, object],
    tuple[_FastArrayRequest, ...],
    tuple[AuxiliaryArrayFeature, ...],
]:
    source_index = _plain_int(element.attrib.get("index"), -1)
    native_id = element.attrib.get("id", "")
    scan_number, scan_number_proven = _extract_scan_number(
        native_id,
        native_id_format_accession,
    )
    top_params = [
        item.attrib
        for item in element
        if _is_tag(item.tag, "cvParam")
    ]
    top_by_name = {
        str(item.get("name", "")): item for item in top_params
    }
    all_param_names = [
        str(item.get("name", "")).lower() for item in top_params
    ]
    scans = _nested_children(element, "scanList", "scan")
    scan = scans[0] if len(scans) == 1 else None
    scan_params = (
        [
            item.attrib
            for item in scan
            if _is_tag(item.tag, "cvParam")
        ]
        if scan is not None
        else []
    )
    scan_by_name = {
        str(item.get("name", "")): item for item in scan_params
    }
    all_param_names.extend(
        str(item.get("name", "")).lower() for item in scan_params
    )
    rt_param = scan_by_name.get("scan start time")
    source_rt_value = _plain_optional_float(
        rt_param.get("value") if rt_param is not None else None
    )
    rt_unit_accession = (
        rt_param.get("unitAccession") if rt_param is not None else None
    )
    rt_unit_name = (
        rt_param.get("unitName") if rt_param is not None else None
    )
    rt_seconds = None
    if (
        source_rt_value is not None
        and time_unit_scale(rt_unit_accession, rt_unit_name) is not None
    ):
        rt_seconds = normalize_time_seconds(
            source_rt_value,
            rt_unit_accession,
            rt_unit_name,
        )
    scan_windows = (
        _nested_children(scan, "scanWindowList", "scanWindow")
        if scan is not None
        else []
    )
    window_params = (
        {
            str(item.attrib.get("name", "")): item.attrib
            for item in scan_windows[0]
            if _is_tag(item.tag, "cvParam")
        }
        if len(scan_windows) == 1
        else {}
    )
    requests: list[_FastArrayRequest] = []
    auxiliaries: list[AuxiliaryArrayFeature] = []
    descriptors_by_kind: dict[str, _ArrayDescriptor] = {}
    for binary_array in _nested_children(
        element,
        "binaryDataArrayList",
        "binaryDataArray",
    ):
        descriptor = _fast_array_descriptor(binary_array)
        all_param_names.append(descriptor.name.lower())
        if descriptor.kind in {"mz", "intensity"}:
            if descriptor.kind in descriptors_by_kind:
                raise MzmlParseError(
                    "MULTIPLE_CORE_ARRAYS",
                    f"multiple {descriptor.kind} arrays are not supported",
                    f"spectrum[{source_index}]",
                )
            descriptors_by_kind[descriptor.kind] = descriptor
            binary = next(
                (
                    item
                    for item in binary_array
                    if _is_tag(item.tag, "binary")
                ),
                None,
            )
            requests.append(
                _FastArrayRequest(
                    descriptor.kind,
                    descriptor.dtype,
                    descriptor.compression,
                    binary.text if binary is not None and binary.text else "",
                )
            )
        else:
            auxiliaries.append(_descriptor_to_auxiliary(descriptor))
    precursor_elements = _nested_children(
        element,
        "precursorList",
        "precursor",
    )
    for precursor in precursor_elements:
        all_param_names.extend(
            str(item.attrib.get("name", "")).lower()
            for item in precursor.iter()
            if _is_tag(item.tag, "cvParam")
        )
    precursors = tuple(
        _parse_fast_precursor(
            item,
            f"spectrum[{source_index}].precursor[{position}]",
        )
        for position, item in enumerate(precursor_elements)
    )
    mz_descriptor = descriptors_by_kind.get("mz")
    intensity_descriptor = descriptors_by_kind.get("intensity")
    fields: dict[str, object] = {
        "source_index": source_index,
        "native_id": native_id,
        "scan_number": scan_number,
        "scan_number_proven": scan_number_proven,
        "ms_level": _plain_int(
            top_by_name.get("ms level", {}).get("value"),
            0,
        ),
        "rt_seconds": rt_seconds,
        "source_rt_value": source_rt_value,
        "source_rt_unit_accession": rt_unit_accession,
        "source_rt_unit_name": rt_unit_name,
        "source_mz_dtype": mz_descriptor.dtype if mz_descriptor else None,
        "source_intensity_dtype": (
            intensity_descriptor.dtype if intensity_descriptor else None
        ),
        "source_mz_compression": (
            mz_descriptor.compression if mz_descriptor else None
        ),
        "source_intensity_compression": (
            intensity_descriptor.compression
            if intensity_descriptor
            else None
        ),
        "representation": (
            "centroid"
            if "centroid spectrum" in top_by_name
            else "profile"
            if "profile spectrum" in top_by_name
            else "unknown"
        ),
        "polarity": (
            "positive"
            if "positive scan" in top_by_name
            else "negative"
            if "negative scan" in top_by_name
            else None
        ),
        "default_array_length": _plain_int(
            element.attrib.get("defaultArrayLength"),
            -1,
        ),
        "precursors": precursors,
        "auxiliary_arrays": tuple(auxiliaries),
        "has_dia_semantics": any(
            "data independent acquisition" in name
            for name in all_param_names
        ),
        "has_ion_mobility": any(
            "ion mobility" in name or "drift time" in name
            for name in all_param_names
        ),
        "total_ion_current": _fast_param_float(
            top_by_name,
            "total ion current",
        ),
        "base_peak_mz": _fast_param_float(top_by_name, "base peak m/z"),
        "base_peak_intensity": _fast_param_float(
            top_by_name,
            "base peak intensity",
        ),
        "lowest_observed_mz": _fast_param_float(
            top_by_name,
            "lowest observed m/z",
        ),
        "highest_observed_mz": _fast_param_float(
            top_by_name,
            "highest observed m/z",
        ),
        "scan_window_lower": _fast_param_float(
            window_params,
            "scan window lower limit",
        ),
        "scan_window_upper": _fast_param_float(
            window_params,
            "scan window upper limit",
        ),
        "filter_string": (
            scan_by_name.get("filter string", {}).get("value")
            if "filter string" in scan_by_name
            else None
        ),
        "instrument_configuration_ref": (
            scan.attrib.get("instrumentConfigurationRef")
            if scan is not None
            else None
        ),
        "data_processing_ref": element.attrib.get("dataProcessingRef"),
    }
    return fields, tuple(requests), tuple(auxiliaries)


def _finish_fast_spectrum(
    pending: _FastSpectrumPending,
) -> ParsedMzmlSpectrum:
    arrays = pending.future.result()
    return ParsedMzmlSpectrum(
        **pending.fields,
        mz_values=arrays.get("mz", np.empty(0, dtype="<f8")),
        intensity_values=arrays.get(
            "intensity",
            np.empty(0, dtype="<f8"),
        ),
    )


def _decode_fast_arrays(
    requests: tuple[_FastArrayRequest, ...],
) -> dict[str, np.ndarray]:
    return {
        request.kind: _decode_fast_array(request)
        for request in requests
    }


def _decode_fast_array(request: _FastArrayRequest) -> np.ndarray:
    dtype_by_name = {
        "float32": "<f4",
        "float64": "<f8",
        "int32": "<i4",
        "int64": "<i8",
    }
    dtype = dtype_by_name.get(request.dtype or "")
    if dtype is None or request.compression not in {"none", "zlib"}:
        return np.empty(0, dtype="<f8")
    try:
        raw = base64.b64decode(request.encoded)
        if request.compression == "zlib":
            raw = zlib.decompress(raw)
        values = np.frombuffer(raw, dtype=dtype)
    except (ValueError, zlib.error) as exc:
        raise MzmlParseError(
            "BINARY_ARRAY_DECODE_FAILED",
            str(exc),
            f"binaryDataArray[{request.kind}]",
        ) from exc
    target_dtype = (
        "<i8"
        if request.dtype in {"int32", "int64"}
        else "<f8"
    )
    return np.ascontiguousarray(values, dtype=target_dtype)


def _parse_fast_precursor(
    element: Any,
    location: str,
) -> ParsedMzmlPrecursor:
    selected_ions = _nested_children(
        element,
        "selectedIonList",
        "selectedIon",
    )
    ion_params = (
        {
            str(item.attrib.get("name", "")): item.attrib
            for item in selected_ions[0]
            if _is_tag(item.tag, "cvParam")
        }
        if len(selected_ions) == 1
        else {}
    )
    charge_param = ion_params.get("charge state")
    selected_ion_mz = _fast_param_float(
        ion_params,
        "selected ion m/z",
    )
    intensity = _fast_param_float(ion_params, "peak intensity")
    parsed_charge = _plain_optional_int(
        charge_param.get("value") if charge_param is not None else None
    )
    charge = None if parsed_charge == 0 else parsed_charge
    isolation_elements = _direct_children(element, "isolationWindow")
    isolation_params = (
        {
            str(item.attrib.get("name", "")): item.attrib
            for item in isolation_elements[0]
            if _is_tag(item.tag, "cvParam")
        }
        if len(isolation_elements) == 1
        else {}
    )
    isolation_target = _fast_param_float(
        isolation_params,
        "isolation window target m/z",
    )
    isolation_lower = _fast_param_float(
        isolation_params,
        "isolation window lower offset",
    )
    isolation_upper = _fast_param_float(
        isolation_params,
        "isolation window upper offset",
    )
    activation_elements = _direct_children(element, "activation")
    activation_params = (
        [
            item.attrib
            for item in activation_elements[0]
            if _is_tag(item.tag, "cvParam")
        ]
        if len(activation_elements) == 1
        else []
    )
    activation_methods: list[CvParamV1] = []
    collision_energy = None
    collision_unit_accession = None
    collision_unit_name = None
    for item in activation_params:
        if (
            item.get("accession") == "MS:1000045"
            or item.get("name") == "collision energy"
        ):
            collision_energy = _plain_optional_float(item.get("value"))
            collision_unit_accession = item.get("unitAccession")
            collision_unit_name = item.get("unitName")
        else:
            activation_methods.append(
                CvParamV1(
                    accession=item.get("accession", ""),
                    name=item.get("name", ""),
                    value=item.get("value") or None,
                    unit_accession=item.get("unitAccession"),
                    unit_name=item.get("unitName"),
                )
            )
    _validate_precursor_number(
        selected_ion_mz,
        f"{location}.selected_ion_mz",
        nonnegative=True,
    )
    _validate_precursor_number(
        intensity,
        f"{location}.selected_ion_intensity",
    )
    _validate_precursor_number(
        isolation_target,
        f"{location}.isolation_target_mz",
    )
    _validate_precursor_number(
        isolation_lower,
        f"{location}.isolation_lower_offset",
        nonnegative=True,
    )
    _validate_precursor_number(
        isolation_upper,
        f"{location}.isolation_upper_offset",
        nonnegative=True,
    )
    _validate_precursor_number(
        collision_energy,
        f"{location}.collision_energy",
    )
    return ParsedMzmlPrecursor(
        selected_ion_count=len(selected_ions),
        source_spectrum_ref=element.attrib.get("spectrumRef"),
        selected_ion_mz=selected_ion_mz,
        charge=charge,
        charge_present=charge_param is not None,
        charge_explicit_zero=charge_param is not None and charge is None,
        intensity=intensity,
        isolation_target_mz=isolation_target,
        isolation_lower_offset=isolation_lower,
        isolation_upper_offset=isolation_upper,
        activation_methods=tuple(activation_methods),
        collision_energy=collision_energy,
        collision_energy_unit_accession=collision_unit_accession,
        collision_energy_unit_name=collision_unit_name,
    )


def _parse_fast_chromatogram(
    element: Any,
    structure: _ChromatogramStructure,
) -> ParsedMzmlChromatogram:
    requests: list[_FastArrayRequest] = []
    descriptors: list[_ArrayDescriptor] = []
    for binary_array in _nested_children(
        element,
        "binaryDataArrayList",
        "binaryDataArray",
    ):
        descriptor = _fast_array_descriptor(binary_array)
        descriptors.append(descriptor)
        binary = next(
            (
                item
                for item in binary_array
                if _is_tag(item.tag, "binary")
            ),
            None,
        )
        requests.append(
            _FastArrayRequest(
                descriptor.kind,
                descriptor.dtype,
                descriptor.compression,
                binary.text if binary is not None and binary.text else "",
            )
        )
    decoded: dict[str, np.ndarray] = {}
    auxiliary_values: list[tuple[_ArrayDescriptor, np.ndarray]] = []
    for descriptor, request in zip(descriptors, requests):
        values = _decode_fast_array(request)
        if descriptor.kind in {"time", "intensity"}:
            decoded[descriptor.kind] = values
        else:
            auxiliary_values.append((descriptor, values))
    source_time_values = decoded.get("time", np.empty(0, dtype="<f8"))
    intensity_values = decoded.get(
        "intensity",
        np.empty(0, dtype="<f8"),
    )
    time_descriptor = next(
        (item for item in descriptors if item.kind == "time"),
        None,
    )
    intensity_descriptor = next(
        (item for item in descriptors if item.kind == "intensity"),
        None,
    )
    time_unit_accession = (
        time_descriptor.unit_accession if time_descriptor else None
    )
    time_unit_name = time_descriptor.unit_name if time_descriptor else None
    scale = time_unit_scale(time_unit_accession, time_unit_name)
    time_values_seconds = (
        np.ascontiguousarray(source_time_values * scale, dtype="<f8")
        if scale is not None
        else np.empty(0, dtype="<f8")
    )
    if np.any(~np.isfinite(source_time_values)) or np.any(
        source_time_values < 0
    ):
        raise MzmlParseError(
            "INVALID_CHROMATOGRAM_TIME_VALUE",
            "chromatogram time values must be finite and non-negative",
            f"chromatogram[{structure.source_index}].time_array",
        )
    if np.any(~np.isfinite(intensity_values)):
        raise MzmlParseError(
            "NONFINITE_CHROMATOGRAM_INTENSITY",
            "chromatogram intensity values must be finite",
            f"chromatogram[{structure.source_index}].intensity_array",
        )
    auxiliaries = tuple(
        ParsedMzmlAuxiliaryArray(
            accession=descriptor.accession,
            name=descriptor.name,
            dtype=descriptor.dtype,
            compression=descriptor.compression,
            unit_accession=descriptor.unit_accession,
            unit_name=descriptor.unit_name,
            values=tuple(values.tolist()),
        )
        for descriptor, values in auxiliary_values
    )
    return ParsedMzmlChromatogram(
        source_index=structure.source_index,
        native_id=structure.native_id,
        chromatogram_type=structure.chromatogram_type,
        time_values_seconds=time_values_seconds,
        intensity_values=intensity_values,
        source_time_values=source_time_values,
        source_time_unit_accession=time_unit_accession,
        source_time_unit_name=time_unit_name,
        source_time_dtype=(
            time_descriptor.dtype if time_descriptor else None
        ),
        source_intensity_dtype=(
            intensity_descriptor.dtype if intensity_descriptor else None
        ),
        source_time_compression=(
            time_descriptor.compression if time_descriptor else None
        ),
        source_intensity_compression=(
            intensity_descriptor.compression
            if intensity_descriptor
            else None
        ),
        default_array_length=structure.default_array_length,
        data_processing_ref=structure.data_processing_ref,
        auxiliary_arrays=auxiliaries,
        has_precursor_semantics=structure.has_precursor_semantics,
        has_product_semantics=structure.has_product_semantics,
    )


def _fast_param_float(
    values: dict[str, Any],
    name: str,
) -> float | None:
    item = values.get(name)
    return _plain_optional_float(
        item.get("value") if item is not None else None
    )


def _release_lxml_element(element: Any) -> None:
    parent = element.getparent()
    element.clear()
    if parent is not None:
        parent.remove(element)


def _parse_spectrum(
    record: dict[str, Any],
    native_id_format_accession: str | None,
    auxiliary_arrays: tuple[AuxiliaryArrayFeature, ...],
) -> ParsedMzmlSpectrum:
    source_index = int(record.get("index", -1))
    native_id = str(record.get("id", ""))
    scan_number, scan_number_proven = _extract_scan_number(native_id, native_id_format_accession)
    source_rt_value, unit_accession, unit_name, rt_seconds, scan = _extract_rt(record)
    mz_values, mz_dtype, mz_compression = _decode_array(record.get("m/z array"))
    intensity_values, intensity_dtype, intensity_compression = _decode_array(record.get("intensity array"))
    precursors = _extract_precursors(record, source_index)
    keys = tuple(str(key).lower() for key in record)
    scan_window = scan.get("scanWindowList", {}).get("scanWindow", []) if isinstance(scan, dict) else []
    first_window = scan_window[0] if isinstance(scan_window, list) and len(scan_window) == 1 else {}
    return ParsedMzmlSpectrum(
        source_index=source_index,
        native_id=native_id,
        scan_number=scan_number,
        scan_number_proven=scan_number_proven,
        ms_level=_plain_int(record.get("ms level"), 0),
        rt_seconds=rt_seconds,
        source_rt_value=source_rt_value,
        source_rt_unit_accession=unit_accession,
        source_rt_unit_name=unit_name,
        mz_values=mz_values,
        intensity_values=intensity_values,
        source_mz_dtype=mz_dtype,
        source_intensity_dtype=intensity_dtype,
        source_mz_compression=mz_compression,
        source_intensity_compression=intensity_compression,
        representation="centroid" if "centroid spectrum" in record else "profile" if "profile spectrum" in record else "unknown",
        polarity="positive" if "positive scan" in record else "negative" if "negative scan" in record else None,
        default_array_length=_plain_int(record.get("defaultArrayLength"), -1),
        precursors=precursors,
        auxiliary_arrays=auxiliary_arrays,
        has_dia_semantics=any("data independent acquisition" in key for key in keys),
        has_ion_mobility=any("ion mobility" in key or "drift time" in key for key in keys),
        total_ion_current=_plain_optional_float(record.get("total ion current")),
        base_peak_mz=_plain_optional_float(record.get("base peak m/z")),
        base_peak_intensity=_plain_optional_float(record.get("base peak intensity")),
        lowest_observed_mz=_plain_optional_float(record.get("lowest observed m/z")),
        highest_observed_mz=_plain_optional_float(record.get("highest observed m/z")),
        scan_window_lower=_plain_optional_float(first_window.get("scan window lower limit")) if isinstance(first_window, dict) else None,
        scan_window_upper=_plain_optional_float(first_window.get("scan window upper limit")) if isinstance(first_window, dict) else None,
        filter_string=str(scan["filter string"]) if isinstance(scan, dict) and "filter string" in scan else None,
        instrument_configuration_ref=str(scan["instrumentConfigurationRef"]) if isinstance(scan, dict) and "instrumentConfigurationRef" in scan else None,
        data_processing_ref=str(record["dataProcessingRef"]) if "dataProcessingRef" in record else None,
    )


def _decode_array(value: object) -> tuple[tuple[float, ...], str | None, str | None]:
    if value is None or not callable(getattr(value, "decode", None)):
        return (), None, None
    dtype = np.dtype(getattr(value, "dtype")).name
    compression_text = str(getattr(value, "compression", ""))
    compression = "zlib" if compression_text == "zlib compression" else "none" if compression_text == "no compression" else compression_text
    decoded = value.decode()  # type: ignore[union-attr]
    normalized = np.asarray(decoded, dtype=np.float64)
    return tuple(normalized.tolist()), dtype, compression


def _decode_numeric_array(value: object) -> tuple[tuple[int | float, ...], str | None, str | None]:
    if value is None or not callable(getattr(value, "decode", None)):
        return (), None, None
    dtype = np.dtype(getattr(value, "dtype")).name
    compression_text = str(getattr(value, "compression", ""))
    compression = "zlib" if compression_text == "zlib compression" else "none" if compression_text == "no compression" else compression_text
    decoded = value.decode()  # type: ignore[union-attr]
    if dtype in {"int32", "int64"}:
        return tuple(np.asarray(decoded, dtype=np.int64).tolist()), dtype, compression
    return tuple(np.asarray(decoded, dtype=np.float64).tolist()), dtype, compression


def _parse_chromatogram(record: dict[str, Any], structure: _ChromatogramStructure) -> ParsedMzmlChromatogram:
    time_descriptors = [item for item in structure.arrays if item.kind == "time"]
    intensity_descriptors = [item for item in structure.arrays if item.kind == "intensity"]
    if len(time_descriptors) > 1 or len(intensity_descriptors) > 1:
        raise MzmlParseError(
            "MULTIPLE_CHROMATOGRAM_ARRAYS",
            "a supported chromatogram requires exactly one time and one intensity array",
            f"chromatogram[{structure.source_index}]",
        )
    time_descriptor = time_descriptors[0] if time_descriptors else None
    intensity_descriptor = intensity_descriptors[0] if intensity_descriptors else None
    source_time_values, decoded_time_dtype, decoded_time_compression = _decode_array(record.get("time array"))
    intensity_values, decoded_intensity_dtype, decoded_intensity_compression = _decode_array(record.get("intensity array"))
    time_unit_accession = time_descriptor.unit_accession if time_descriptor else None
    time_unit_name = time_descriptor.unit_name if time_descriptor else None
    scale = time_unit_scale(time_unit_accession, time_unit_name)
    time_values_seconds = tuple(value * scale for value in source_time_values) if scale is not None else ()
    if any(not math.isfinite(value) or value < 0 for value in source_time_values):
        raise MzmlParseError(
            "INVALID_CHROMATOGRAM_TIME_VALUE",
            "chromatogram time values must be finite and non-negative",
            f"chromatogram[{structure.source_index}].time_array",
        )
    if any(not math.isfinite(value) for value in intensity_values):
        raise MzmlParseError(
            "NONFINITE_CHROMATOGRAM_INTENSITY",
            "chromatogram intensity values must be finite",
            f"chromatogram[{structure.source_index}].intensity_array",
        )
    if (decoded_time_dtype is not None and not source_time_values) or (
        decoded_intensity_dtype is not None and not intensity_values
    ):
        raise MzmlParseError(
            "EMPTY_CHROMATOGRAM_ARRAY",
            "supported chromatogram arrays must be nonempty",
            f"chromatogram[{structure.source_index}]",
        )

    auxiliaries: list[ParsedMzmlAuxiliaryArray] = []
    for descriptor in (item for item in structure.arrays if item.kind not in {"time", "intensity"}):
        values, dtype, compression = _decode_numeric_array(record.get(descriptor.name))
        auxiliaries.append(
            ParsedMzmlAuxiliaryArray(
                accession=descriptor.accession,
                name=descriptor.name,
                dtype=dtype or descriptor.dtype,
                compression=compression or descriptor.compression,
                unit_accession=descriptor.unit_accession,
                unit_name=descriptor.unit_name,
                values=values,
            )
        )
    return ParsedMzmlChromatogram(
        source_index=structure.source_index,
        native_id=structure.native_id,
        chromatogram_type=structure.chromatogram_type,
        time_values_seconds=time_values_seconds,
        intensity_values=intensity_values,
        source_time_values=source_time_values,
        source_time_unit_accession=time_unit_accession,
        source_time_unit_name=time_unit_name,
        source_time_dtype=decoded_time_dtype or (time_descriptor.dtype if time_descriptor else None),
        source_intensity_dtype=decoded_intensity_dtype or (intensity_descriptor.dtype if intensity_descriptor else None),
        source_time_compression=decoded_time_compression or (time_descriptor.compression if time_descriptor else None),
        source_intensity_compression=decoded_intensity_compression or (intensity_descriptor.compression if intensity_descriptor else None),
        default_array_length=structure.default_array_length,
        data_processing_ref=structure.data_processing_ref,
        auxiliary_arrays=tuple(auxiliaries),
        has_precursor_semantics=structure.has_precursor_semantics,
        has_product_semantics=structure.has_product_semantics,
    )


def _extract_scan_number(native_id: str, native_id_format_accession: str | None) -> tuple[int | None, bool]:
    if native_id_format_accession != THERMO_NATIVE_ID_ACCESSION:
        return None, False
    matches = _SCAN_PATTERN.findall(native_id)
    if len(matches) != 1:
        return None, False
    value = int(matches[0])
    return value, value > 0


def _extract_rt(record: dict[str, Any]) -> tuple[float | None, str | None, str | None, float | None, dict[str, Any]]:
    scan_list = record.get("scanList", {})
    scans = scan_list.get("scan", []) if isinstance(scan_list, dict) else []
    if not isinstance(scans, list) or len(scans) != 1 or not isinstance(scans[0], dict):
        return None, None, None, None, {}
    scan = scans[0]
    value = scan.get("scan start time")
    source_value = _plain_optional_float(value)
    unit_name_value = getattr(value, "unit_info", None)
    unit_name = str(unit_name_value) if unit_name_value else None
    normalized_name = unit_name.lower() if unit_name else None
    if normalized_name in {"second", "seconds"}:
        unit_accession = "UO:0000010"
    elif normalized_name in {"minute", "minutes"}:
        unit_accession = "UO:0000031"
    else:
        unit_accession = None
    rt_seconds = None
    if source_value is not None and time_unit_scale(unit_accession, unit_name) is not None:
        rt_seconds = normalize_time_seconds(source_value, unit_accession, unit_name)
    return source_value, unit_accession, unit_name, rt_seconds, scan


def _extract_precursors(record: dict[str, Any], source_index: int) -> tuple[ParsedMzmlPrecursor, ...]:
    precursor_list = record.get("precursorList", {})
    precursors = precursor_list.get("precursor", []) if isinstance(precursor_list, dict) else []
    if not isinstance(precursors, list):
        return ()
    return tuple(
        _parse_precursor(item, f"spectrum[{source_index}].precursor[{position}]")
        for position, item in enumerate(precursors)
        if isinstance(item, dict)
    )


def _parse_precursor(value: dict[str, Any], location: str) -> ParsedMzmlPrecursor:
    selected_list = value.get("selectedIonList", {})
    selected_ions = selected_list.get("selectedIon", []) if isinstance(selected_list, dict) else []
    if not isinstance(selected_ions, list):
        selected_ions = []
    ion = selected_ions[0] if len(selected_ions) == 1 and isinstance(selected_ions[0], dict) else None
    charge_present = ion is not None and "charge state" in ion
    raw_charge = ion.get("charge state") if ion is not None else None
    selected_ion_mz = _plain_optional_float(ion.get("selected ion m/z")) if ion is not None else None
    intensity = _plain_optional_float(ion.get("peak intensity")) if ion is not None else None

    isolation = value.get("isolationWindow", {})
    if not isinstance(isolation, dict):
        isolation = {}
    isolation_target = _plain_optional_float(isolation.get("isolation window target m/z"))
    isolation_lower = _plain_optional_float(isolation.get("isolation window lower offset"))
    isolation_upper = _plain_optional_float(isolation.get("isolation window upper offset"))

    activation = value.get("activation", {})
    if not isinstance(activation, dict):
        activation = {}
    activation_methods: list[CvParamV1] = []
    collision_energy: float | None = None
    collision_unit_accession: str | None = None
    collision_unit_name: str | None = None
    for key, item in activation.items():
        accession = getattr(key, "accession", None)
        name = str(key)
        if accession == "MS:1000045" or name == "collision energy":
            collision_energy = _plain_optional_float(item)
            unit_info = getattr(item, "unit_info", None)
            collision_unit_name = str(unit_info) if unit_info else None
            collision_unit_accession = _UNIT_ACCESSIONS.get(collision_unit_name) if collision_unit_name else None
            continue
        if accession:
            activation_methods.append(
                CvParamV1(
                    accession=str(accession),
                    name=name,
                    value=str(item) if str(item) else None,
                )
            )

    _validate_precursor_number(selected_ion_mz, f"{location}.selected_ion_mz", nonnegative=True)
    _validate_precursor_number(intensity, f"{location}.selected_ion_intensity")
    _validate_precursor_number(isolation_target, f"{location}.isolation_target_mz")
    _validate_precursor_number(isolation_lower, f"{location}.isolation_lower_offset", nonnegative=True)
    _validate_precursor_number(isolation_upper, f"{location}.isolation_upper_offset", nonnegative=True)
    _validate_precursor_number(collision_energy, f"{location}.collision_energy")

    return ParsedMzmlPrecursor(
        selected_ion_count=len(selected_ions),
        source_spectrum_ref=str(value["spectrumRef"]) if "spectrumRef" in value else None,
        selected_ion_mz=selected_ion_mz,
        charge=_plain_optional_int(raw_charge),
        charge_present=charge_present,
        charge_explicit_zero=charge_present and raw_charge is None,
        intensity=intensity,
        isolation_target_mz=isolation_target,
        isolation_lower_offset=isolation_lower,
        isolation_upper_offset=isolation_upper,
        activation_methods=tuple(activation_methods),
        collision_energy=collision_energy,
        collision_energy_unit_accession=collision_unit_accession,
        collision_energy_unit_name=collision_unit_name,
    )


def _validate_precursor_number(value: float | None, location: str, *, nonnegative: bool = False) -> None:
    if value is None:
        return
    if not math.isfinite(value):
        raise MzmlParseError("NONFINITE_PRECURSOR_VALUE", "precursor values must be finite", location)
    if nonnegative and value < 0:
        code = "NEGATIVE_ISOLATION_OFFSET" if "offset" in location else "NEGATIVE_PRECURSOR_MZ"
        raise MzmlParseError(code, "precursor m/z values and isolation offsets must not be negative", location)


def _inspect_document_structure(path: Path) -> _DocumentStructure:
    indexed = False
    mzml_version = ""
    native_formats: list[tuple[str, str]] = []
    runs: list[ParsedMzmlRun] = []
    chromatograms: list[_ChromatogramStructure] = []
    spectrum_auxiliaries: list[tuple[int, tuple[AuxiliaryArrayFeature, ...]]] = []
    instruments: list[TraceableEntityV1] = []
    software: list[TraceableEntityV1] = []
    data_processing: list[TraceableEntityV1] = []
    first_element = True

    for event, element in ET.iterparse(path, events=("start", "end")):
        tag = _local_name(element.tag)
        if event == "start":
            if first_element:
                indexed = tag == "indexedmzML"
                first_element = False
            if tag == "mzML":
                mzml_version = element.attrib.get("version", "")
            elif tag == "run":
                runs.append(
                    ParsedMzmlRun(
                        run_id=element.attrib.get("id", ""),
                        default_instrument_configuration_ref=element.attrib.get("defaultInstrumentConfigurationRef"),
                        default_source_file_ref=element.attrib.get("defaultSourceFileRef"),
                        sample_ref=element.attrib.get("sampleRef"),
                        start_time_stamp=element.attrib.get("startTimeStamp"),
                    )
                )
            continue

        if tag == "sourceFile":
            for cv_param in _cv_params(element):
                if cv_param.name.endswith("nativeID format"):
                    native_formats.append((cv_param.accession, cv_param.name))
            element.clear()
        elif tag == "instrumentConfiguration":
            instruments.append(_entity(element))
            element.clear()
        elif tag == "software":
            software.append(_entity(element))
            element.clear()
        elif tag == "dataProcessing":
            data_processing.append(_entity(element))
            element.clear()
        elif tag == "spectrum":
            source_index = _plain_int(element.attrib.get("index"), len(spectrum_auxiliaries))
            auxiliaries = tuple(
                _descriptor_to_auxiliary(item)
                for item in _array_descriptors(element)
                if item.kind not in {"mz", "intensity"}
            )
            spectrum_auxiliaries.append((source_index, auxiliaries))
            element.clear()
        elif tag == "chromatogram":
            chromatograms.append(_chromatogram_structure(element))
            element.clear()

    native_format = native_formats[0] if len(native_formats) == 1 else (None, None)
    return _DocumentStructure(
        indexed=indexed,
        mzml_version=mzml_version,
        native_id_format_accession=native_format[0],
        native_id_format_name=native_format[1],
        runs=tuple(runs),
        chromatograms=tuple(chromatograms),
        spectrum_auxiliaries=tuple(spectrum_auxiliaries),
        instruments=tuple(instruments),
        software=tuple(software),
        data_processing=tuple(data_processing),
    )


def _array_descriptors(element: ET.Element) -> tuple[_ArrayDescriptor, ...]:
    descriptors: list[_ArrayDescriptor] = []
    for item in element.iter():
        if _local_name(item.tag) != "binaryDataArray":
            continue
        params = [child.attrib for child in item.iter() if _local_name(child.tag) == "cvParam"]
        dtype = next((_DTYPE_ACCESSIONS[value.get("accession", "")] for value in params if value.get("accession") in _DTYPE_ACCESSIONS), None)
        compression = next((_COMPRESSION_ACCESSIONS[value.get("accession", "")] for value in params if value.get("accession") in _COMPRESSION_ACCESSIONS), None)
        semantic = next((value for value in params if value.get("accession") in _ARRAY_ACCESSIONS or value.get("accession") == "MS:1000786"), None)
        if semantic is None:
            descriptors.append(_ArrayDescriptor("auxiliary", "", "unknown", dtype, compression, None, None))
            continue
        accession = semantic.get("accession", "")
        kind = _ARRAY_ACCESSIONS.get(accession, "auxiliary")
        name = semantic.get("value") or semantic.get("name", "")
        descriptors.append(
            _ArrayDescriptor(
                kind,
                accession,
                name,
                dtype,
                compression,
                semantic.get("unitAccession"),
                semantic.get("unitName"),
            )
        )
    return tuple(descriptors)


def _descriptor_to_auxiliary(item: _ArrayDescriptor) -> AuxiliaryArrayFeature:
    return AuxiliaryArrayFeature(item.accession, item.name, item.dtype or "unknown", item.unit_accession, item.unit_name)


def _chromatogram_structure(element: ET.Element) -> _ChromatogramStructure:
    params = [item.attrib for item in element if _local_name(item.tag) == "cvParam"]
    chromatogram_type = next((_CHROMATOGRAM_ACCESSIONS[item.get("accession", "")] for item in params if item.get("accession") in _CHROMATOGRAM_ACCESSIONS), "unknown")
    descriptors = _array_descriptors(element)
    descendant_tags = {_local_name(item.tag) for item in element.iter()}
    return _ChromatogramStructure(
        source_index=_plain_int(element.attrib.get("index"), -1),
        native_id=element.attrib.get("id", ""),
        chromatogram_type=chromatogram_type,
        default_array_length=_plain_int(element.attrib.get("defaultArrayLength"), -1),
        data_processing_ref=element.attrib.get("dataProcessingRef"),
        arrays=descriptors,
        has_precursor_semantics="precursor" in descendant_tags,
        has_product_semantics="product" in descendant_tags,
    )


def _entity(element: ET.Element) -> TraceableEntityV1:
    params = _cv_params(element)
    first = params[0] if params else None
    return TraceableEntityV1(
        id=element.attrib.get("id", ""),
        accession=first.accession if first else None,
        name=first.name if first else None,
        version=element.attrib.get("version"),
        cv_params=params,
    )


def _cv_params(element: ET.Element) -> tuple[CvParamV1, ...]:
    values: list[CvParamV1] = []
    for item in element.iter():
        if _local_name(item.tag) != "cvParam":
            continue
        unit_accession = item.attrib.get("unitAccession")
        unit_name = item.attrib.get("unitName")
        if (unit_accession is None) != (unit_name is None):
            unit_accession = unit_name = None
        values.append(
            CvParamV1(
                accession=item.attrib.get("accession", ""),
                name=item.attrib.get("name", ""),
                value=item.attrib.get("value"),
                unit_accession=unit_accession,
                unit_name=unit_name,
            )
        )
    return tuple(values)


def _build_metadata_if_representable(
    structure: _DocumentStructure,
    run: ParsedMzmlRun,
    spectra: tuple[ParsedMzmlSpectrum, ...],
    chromatograms: tuple[ParsedMzmlChromatogram, ...],
) -> MzmlMetadataV1 | None:
    if not structure.native_id_format_accession or not structure.native_id_format_name or not run.run_id:
        return None
    if any(
        item.source_rt_value is None
        or item.source_rt_unit_accession is None
        or item.source_rt_unit_name is None
        or item.source_mz_dtype not in {"float32", "float64"}
        or item.source_intensity_dtype not in {"float32", "float64"}
        or item.source_mz_compression not in {"none", "zlib"}
        or item.source_intensity_compression not in {"none", "zlib"}
        or item.representation not in {"centroid", "profile"}
        or item.default_array_length < 0
        or (item.ms_level == 1 and item.precursors != ())
        or (item.ms_level == 2 and (len(item.precursors) != 1 or item.precursors[0].selected_ion_count != 1))
        for item in spectra
    ):
        return None
    if any(
        item.chromatogram_type not in {"tic", "bpc"}
        or item.source_time_dtype not in {"float32", "float64"}
        or item.source_intensity_dtype not in {"float32", "float64"}
        or item.source_time_compression not in {"none", "zlib"}
        or item.source_intensity_compression not in {"none", "zlib"}
        or item.source_time_unit_accession is None
        or item.source_time_unit_name is None
        for item in chromatograms
    ):
        return None
    try:
        spectrum_metadata = tuple(_spectrum_metadata(item, index) for index, item in enumerate(spectra, 1))
        chromatogram_metadata = tuple(_chromatogram_metadata(item, index) for index, item in enumerate(chromatograms, 1))
        return MzmlMetadataV1(
            source=MzmlSourceMetadataV1(
                indexed=structure.indexed,
                mzml_version=structure.mzml_version,
                native_id_format_accession=structure.native_id_format_accession,
                native_id_format_name=structure.native_id_format_name,
            ),
            run=MzmlRunMetadataV1(
                run_id=run.run_id,
                default_instrument_configuration_ref=run.default_instrument_configuration_ref,
                default_source_file_ref=run.default_source_file_ref,
                sample_ref=run.sample_ref,
                start_time_stamp=run.start_time_stamp,
            ),
            spectra=spectrum_metadata,
            chromatograms=chromatogram_metadata,
            instruments=structure.instruments,
            software=structure.software,
            data_processing=structure.data_processing,
        )
    except (ValueError, MzmlSchemaError) as exc:
        raise MzmlParseError("MZML_METADATA_BUILD_FAILED", str(exc), "mzml_metadata") from exc


def _spectrum_metadata(item: ParsedMzmlSpectrum, position: int) -> SpectrumMetadataV1:
    precursor = item.precursors[0] if len(item.precursors) == 1 else None
    return SpectrumMetadataV1(
        spectrum_id=f"spectrum_{position:06d}",
        polarity=Polarity(item.polarity) if item.polarity else None,
        representation=SpectrumRepresentation(item.representation),
        default_array_length=item.default_array_length,
        total_ion_current=item.total_ion_current,
        base_peak_mz=item.base_peak_mz,
        base_peak_intensity=item.base_peak_intensity,
        lowest_observed_mz=item.lowest_observed_mz,
        highest_observed_mz=item.highest_observed_mz,
        scan_window_lower=item.scan_window_lower,
        scan_window_upper=item.scan_window_upper,
        filter_string=item.filter_string,
        instrument_configuration_ref=item.instrument_configuration_ref,
        data_processing_ref=item.data_processing_ref,
        precursor_source_spectrum_ref=precursor.source_spectrum_ref if precursor else None,
        isolation_window_target_mz=precursor.isolation_target_mz if precursor else None,
        isolation_window_lower_offset=precursor.isolation_lower_offset if precursor else None,
        isolation_window_upper_offset=precursor.isolation_upper_offset if precursor else None,
        activation_methods=precursor.activation_methods if precursor else (),
        collision_energy=precursor.collision_energy if precursor else None,
        collision_energy_unit_accession=precursor.collision_energy_unit_accession if precursor else None,
        collision_energy_unit_name=precursor.collision_energy_unit_name if precursor else None,
        source_mz_dtype=NumericDtype(item.source_mz_dtype),
        source_intensity_dtype=NumericDtype(item.source_intensity_dtype),
        source_mz_compression=ArrayCompression(item.source_mz_compression),
        source_intensity_compression=ArrayCompression(item.source_intensity_compression),
        source_rt_value=float(item.source_rt_value),
        source_rt_unit_accession=str(item.source_rt_unit_accession),
        source_rt_unit_name=str(item.source_rt_unit_name),
    )


def _chromatogram_metadata(item: ParsedMzmlChromatogram, position: int) -> ChromatogramMetadataV1:
    return ChromatogramMetadataV1(
        chromatogram_id=f"chromatogram_{position:06d}",
        chromatogram_type=ChromatogramType(item.chromatogram_type),
        default_array_length=item.default_array_length,
        data_processing_ref=item.data_processing_ref,
        source_time_dtype=NumericDtype(item.source_time_dtype),
        source_intensity_dtype=NumericDtype(item.source_intensity_dtype),
        source_time_compression=ArrayCompression(item.source_time_compression),
        source_intensity_compression=ArrayCompression(item.source_intensity_compression),
        source_time_unit_accession=str(item.source_time_unit_accession),
        source_time_unit_name=str(item.source_time_unit_name),
    )


def _plain_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _plain_optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _plain_optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _local_name(tag: str) -> str:
    position = tag.rfind("}")
    return tag if position < 0 else tag[position + 1 :]


def _is_tag(tag: str, name: str) -> bool:
    if tag == name:
        return True
    boundary = len(tag) - len(name) - 1
    return boundary >= 0 and tag[boundary] == "}" and tag.endswith(name)
