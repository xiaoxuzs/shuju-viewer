from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..blocks import BlockCollection
from ..composite_bottom_up_adapter import (
    CompositeBottomUpAdapter,
    CompositeBottomUpAdapterReport,
    ExactSpectrumReference,
)
from ..composite_bottom_up_bundle import SOURCE_TYPE, CompositeBottomUpBundle
from ..composite_bottom_up_exceptions import CompositeBottomUpConversionError
from ..models import ConversionOptions, PipelineContext, SourceProfile
from .base import BaseBlockTool
from .real_mzml import RealMzmlExecutionReport, RealMzmlParseTool

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RealCompositeBottomUpExecutionReport:
    mzml_report: RealMzmlExecutionReport | None
    adapter_report: CompositeBottomUpAdapterReport
    spectrum_count: int
    precursor_count: int
    chromatogram_count: int
    peak_pair_count: int


class RealCompositeBottomUpTool(BaseBlockTool):
    """Compose a proven mzML core with exact-scan Bottom-Up result extensions."""

    name = "real_composite_bottom_up"
    input_kinds = ("validated_source", "input_sha256")
    output_kinds = ("core_blocks", "arrays", "extensions")

    def __init__(
        self,
        adapter: CompositeBottomUpAdapter | None = None,
        mzml_tool: RealMzmlParseTool | None = None,
    ) -> None:
        self.adapter = adapter or CompositeBottomUpAdapter()
        self.mzml_tool = mzml_tool or RealMzmlParseTool()
        self.last_report: RealCompositeBottomUpExecutionReport | None = None

    def build_blocks(self, context: PipelineContext) -> None:
        if context.blocks != BlockCollection():
            raise CompositeBottomUpConversionError(
                "COMPOSITE_BLOCK_COLLECTION_NOT_EMPTY",
                "Composite Bottom-Up conversion requires an empty BlockCollection",
            )
        profile = context.source_profile
        bundle = profile.composite_bottom_up_bundle
        if profile.source_type != SOURCE_TYPE or not isinstance(bundle, CompositeBottomUpBundle):
            raise CompositeBottomUpConversionError(
                "COMPOSITE_INVALID_SOURCE",
                "real_composite_bottom_up requires an inspected composite bundle",
            )
        aggregate_sha256 = context.metadata.get("input_sha256")
        source_file_hashes = context.metadata.get("source_file_hashes")
        if not isinstance(aggregate_sha256, str) or _SHA256.fullmatch(aggregate_sha256) is None:
            raise CompositeBottomUpConversionError(
                "MISSING_INPUT_SHA256",
                "hash_input must provide the bundle SHA-256",
            )
        if not isinstance(source_file_hashes, dict) or not all(
            isinstance(key, str)
            and isinstance(value, str)
            and _SHA256.fullmatch(value) is not None
            for key, value in source_file_hashes.items()
        ):
            raise CompositeBottomUpConversionError(
                "MISSING_INPUT_SHA256",
                "hash_input must provide per-file bundle SHA-256 values",
            )
        spectrum_label = bundle.relative_label(bundle.spectrum_source)
        spectrum_sha256 = source_file_hashes.get(spectrum_label)
        if not isinstance(spectrum_sha256, str) or _SHA256.fullmatch(spectrum_sha256) is None:
            raise CompositeBottomUpConversionError(
                "MISSING_INPUT_SHA256",
                "The mzML source SHA-256 is unavailable",
            )
        if bundle.raw_source is None:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_RAW_SOURCE_MISSING",
                "The controlled composite adapter requires the original RAW provenance file",
            )
        declared_raw_sha1 = _mzml_declared_raw_sha1(
            bundle.spectrum_source,
            expected_raw_name=bundle.raw_source.name,
        )
        actual_raw_sha1 = _sha1(bundle.raw_source)
        if declared_raw_sha1 != actual_raw_sha1:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_RAW_MZML_IDENTITY_MISMATCH",
                "The mzML-declared RAW SHA-1 does not match the bundled RAW content",
            )

        nested_context = self._build_core_context(
            context,
            bundle,
            spectrum_label=spectrum_label,
            spectrum_sha256=spectrum_sha256,
        )
        self.mzml_tool.run(nested_context)
        blocks = nested_context.blocks
        if len(blocks.runs) != 1:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_CORE_RUN_COUNT_INVALID",
                "The composite mzML core must contain exactly one run",
            )
        spectrum_by_scan = _exact_ms2_index(blocks)
        adapter_report = self.adapter.read(
            bundle,
            run_id=blocks.runs[0].run_id,
            spectrum_by_scan=spectrum_by_scan,
            source_file_hashes=source_file_hashes,
            raw_source_sha1=actual_raw_sha1,
        )
        blocks.extensions.extend(adapter_report.document.extension_blocks())
        meta = blocks.global_meta
        if meta is None:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_CORE_BLOCKS_MISSING",
                "The mzML tool did not produce GlobalMeta",
            )
        meta.source_type = SOURCE_TYPE
        meta.source_file_name = bundle.root.name
        meta.source_file_hash = aggregate_sha256
        meta.created_at = datetime.fromtimestamp(
            bundle.output_created_at_millis / 1000.0,
            timezone.utc,
        )
        meta.notes.extend(
            (
                "Real mzML MS1/MS2 peaks, selected precursors and BPC are preserved without recomputation.",
                "MaxQuant evidence is associated by exact MS/MS scan number; absent msms.txt fragment annotations are not fabricated.",
            )
        )
        context.blocks = blocks
        self.last_report = RealCompositeBottomUpExecutionReport(
            mzml_report=self.mzml_tool.last_report,
            adapter_report=adapter_report,
            spectrum_count=len(blocks.spectra),
            precursor_count=len(blocks.precursors),
            chromatogram_count=len(blocks.chromatograms),
            peak_pair_count=sum(
                len(item.values)
                for item in blocks.arrays
                if item.array_type == "mz"
            ),
        )

    @staticmethod
    def _build_core_context(
        context: PipelineContext,
        bundle: CompositeBottomUpBundle,
        *,
        spectrum_label: str,
        spectrum_sha256: str,
    ) -> PipelineContext:
        source = bundle.spectrum_source
        try:
            source_stat = source.stat()
        except OSError as exc:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_SPECTRUM_SOURCE_NOT_READABLE",
                "The selected mzML source cannot be read",
            ) from exc
        profile = SourceProfile(
            source_type="real_mzml",
            input_files=(source,),
            file_count=1,
            has_spectra=True,
            has_chromatograms=True,
            has_identification=False,
            has_quantification=False,
            requires_pre_conversion=False,
            path=source,
            suffix=source.suffix,
            file_size=source_stat.st_size,
        )
        metadata: dict[str, object] = {
            "file_validated": True,
            "input_sha256": spectrum_sha256,
            "block_created_at": datetime.fromtimestamp(
                bundle.output_created_at_millis / 1000.0,
                timezone.utc,
            ),
            "source_file_label": spectrum_label,
            "conversion_options": context.metadata.get(
                "conversion_options",
                ConversionOptions(),
            ),
            "format_version": context.metadata.get("format_version"),
        }
        return PipelineContext(profile, metadata=metadata)


def _exact_ms2_index(blocks: BlockCollection) -> dict[int, ExactSpectrumReference]:
    seen: set[int] = set()
    result: dict[int, ExactSpectrumReference] = {}
    for spectrum in blocks.spectra:
        if spectrum.scan_number in seen:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_SCAN_MAPPING_AMBIGUOUS",
                f"Core mzML contains duplicate scan number {spectrum.scan_number}",
            )
        seen.add(spectrum.scan_number)
        if spectrum.ms_level == 2:
            result[spectrum.scan_number] = ExactSpectrumReference(
                spectrum_id=spectrum.spectrum_id,
                native_id=spectrum.native_id,
                rt_seconds=spectrum.rt,
            )
    return result


def _mzml_declared_raw_sha1(path: Path, *, expected_raw_name: str) -> str:
    matches: list[str] = []
    try:
        for _event, element in ET.iterparse(path, events=("end",)):
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "sourceFileList":
                element.clear()
                break
            if tag != "sourceFile":
                continue
            expected_stem = _raw_stem(expected_raw_name)
            declared_name = element.attrib.get("name", "")
            location_name = element.attrib.get("location", "").replace("\\", "/").rsplit("/", 1)[-1]
            if (
                _raw_stem(declared_name) != expected_stem
                or _raw_stem(location_name) != expected_stem
            ):
                element.clear()
                continue
            for child in element.iter():
                if (
                    child.tag.rsplit("}", 1)[-1] == "cvParam"
                    and child.attrib.get("accession") == "MS:1000569"
                ):
                    value = child.attrib.get("value", "").strip().casefold()
                    if re.fullmatch(r"[0-9a-f]{40}", value):
                        matches.append(value)
            element.clear()
    except (ET.ParseError, OSError) as exc:
        raise CompositeBottomUpConversionError(
            "COMPOSITE_MZML_PROVENANCE_INVALID",
            "The mzML sourceFile provenance cannot be read",
        ) from exc
    if len(matches) != 1:
        raise CompositeBottomUpConversionError(
            "COMPOSITE_MZML_PROVENANCE_INVALID",
            "The mzML must declare exactly one SHA-1 for the matching RAW sourceFile",
        )
    return matches[0]


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CompositeBottomUpConversionError(
            "COMPOSITE_RAW_SOURCE_NOT_READABLE",
            "The bundled RAW source cannot be hashed",
        ) from exc
    return digest.hexdigest()


def _raw_stem(value: str) -> str:
    return re.sub(r"(?i)\.raw$", "", value.strip()).casefold()
