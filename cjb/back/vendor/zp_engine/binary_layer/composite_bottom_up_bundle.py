from __future__ import annotations

import csv
import os
import re
import stat as stat_module
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .bottom_up_schema import BOTTOM_UP_DDA_IDENTIFICATION_KIND
from .composite_bottom_up_exceptions import CompositeBottomUpConversionError


SOURCE_TYPE = "real_blueprint_bottom_up_bundle"
ADAPTER_FLAVOR = "maxquant_mzml_v1"
IDENTIFICATION_KIND = BOTTOM_UP_DDA_IDENTIFICATION_KIND

_MAX_BUNDLE_FILES = 10_000
_MAX_TABLE_BYTES = 256 * 1024 * 1024
_MAX_TABLE_ROWS = 500_000
_MAX_CELL_CHARACTERS = 1_000_000
_MAX_FASTA_BYTES = 512 * 1024 * 1024
_MAX_MQPAR_BYTES = 16 * 1024 * 1024

_REQUIRED_TABLE_COLUMNS = {
    "evidence.txt": (
        "Raw file",
        "Experiment",
        "Sequence",
        "Modifications",
        "Modified sequence",
        "Charge",
        "m/z",
        "Mass",
        "Retention time",
        "MS/MS scan number",
        "Proteins",
        "id",
        "Protein group IDs",
        "Score",
        "PEP",
        "Intensity",
    ),
    "proteinGroups.txt": (
        "Protein IDs",
        "Majority protein IDs",
        "Q-value",
        "Score",
        "Intensity",
        "Peptide sequences",
        "Potential contaminant",
        "id",
        "Evidence IDs",
    ),
}


@dataclass(frozen=True, slots=True)
class CompositeSourceFile:
    path: Path
    role: str
    processing_status: str


@dataclass(frozen=True, slots=True)
class CompositeBottomUpBundle:
    root: Path
    evidence: Path
    protein_groups: Path
    mqpar: Path
    spectrum_source: Path
    raw_source: Path | None
    fasta: Path | None
    summary: Path | None
    metadata_json: Path | None
    report_run_name: str
    evidence_columns: tuple[str, ...]
    protein_group_columns: tuple[str, ...]
    evidence_row_count: int
    protein_group_row_count: int
    source_files: tuple[CompositeSourceFile, ...]
    output_created_at_millis: int

    @property
    def identity_files(self) -> tuple[Path, ...]:
        return tuple(item.path for item in self.source_files)

    @property
    def detected_roles(self) -> tuple[str, ...]:
        return tuple(sorted(item.role for item in self.source_files))

    def relative_label(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return path.name


class CompositeBottomUpBundleInspector:
    def inspect_bundle(self, source: str | Path) -> CompositeBottomUpBundle:
        requested = Path(source)
        if _is_link_or_reparse(requested):
            raise CompositeBottomUpConversionError(
                "COMPOSITE_SOURCE_LINK_FORBIDDEN",
                "Composite bundle roots cannot be symbolic links or reparse points",
            )
        root = requested.resolve()
        if not root.is_dir():
            raise CompositeBottomUpConversionError(
                "COMPOSITE_BOTTOM_UP_BUNDLE_NOT_FOUND",
                "A composite Bottom-Up source must be a directory",
            )
        all_files = _bounded_bundle_files(root)
        top_level = {
            path.name.casefold(): path
            for path in all_files
            if path.parent == root
        }
        markers = {"evidence.txt", "proteingroups.txt", "mqpar.xml"}
        if not markers & set(top_level):
            raise CompositeBottomUpConversionError(
                "COMPOSITE_BOTTOM_UP_BUNDLE_NOT_FOUND",
                "No composite Bottom-Up result markers were found",
            )
        missing = sorted(markers - set(top_level))
        if missing:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_REQUIRED_FILE_MISSING",
                f"Required result files are missing: {', '.join(missing)}",
            )
        evidence = top_level["evidence.txt"]
        protein_groups = top_level["proteingroups.txt"]
        mqpar = top_level["mqpar.xml"]
        if mqpar.stat().st_size > _MAX_MQPAR_BYTES:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_RESOURCE_LIMIT_EXCEEDED",
                "mqpar.xml exceeds the controlled adapter size limit",
            )
        evidence_columns, evidence_count = _inspect_table(evidence, "evidence.txt")
        group_columns, group_count = _inspect_table(protein_groups, "proteinGroups.txt")
        for label, columns in (
            ("evidence.txt", evidence_columns),
            ("proteinGroups.txt", group_columns),
        ):
            missing_columns = [item for item in _REQUIRED_TABLE_COLUMNS[label] if item not in columns]
            if missing_columns:
                raise CompositeBottomUpConversionError(
                    "COMPOSITE_REQUIRED_COLUMN_MISSING",
                    f"{label} is missing columns: {', '.join(missing_columns)}",
                )
        run_names = _column_values(evidence, "Raw file")
        if len(run_names) != 1:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_MULTI_RUN_NOT_SUPPORTED",
                "The first composite adapter requires exactly one Raw file value",
                details={"run_count": len(run_names)},
            )
        run_name = next(iter(run_names))
        mzml_candidates = tuple(
            path for path in all_files if path.suffix.casefold() == ".mzml" and _stem(path) == run_name.casefold()
        )
        if len(mzml_candidates) != 1:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_SPECTRUM_SOURCE_INVALID",
                "Exactly one mzML whose basename matches evidence Raw file is required",
                details={"candidate_count": len(mzml_candidates)},
            )
        raw_candidates = tuple(
            path for path in all_files if path.suffix.casefold() == ".raw" and _stem(path) == run_name.casefold()
        )
        fasta_candidates = tuple(
            path for path in all_files if path.suffix.casefold() in {".fasta", ".fa", ".faa"}
        )
        if len(raw_candidates) != 1 or len(fasta_candidates) != 1:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_REQUIRED_SOURCE_ROLE_INVALID",
                "The maxquant_mzml_v1 adapter requires exactly one matching RAW and one FASTA",
                details={
                    "raw_candidate_count": len(raw_candidates),
                    "fasta_candidate_count": len(fasta_candidates),
                },
            )
        if fasta_candidates[0].stat().st_size > _MAX_FASTA_BYTES:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_RESOURCE_LIMIT_EXCEEDED",
                "The FASTA exceeds the controlled adapter size limit",
            )
        fasta_basename = _mqpar_fasta_basename(mqpar)
        if fasta_basename.casefold() != fasta_candidates[0].name.casefold():
            raise CompositeBottomUpConversionError(
                "COMPOSITE_FASTA_REFERENCE_MISMATCH",
                "mqpar.xml fastaFilePath basename does not match the bundled FASTA",
            )
        summary = top_level.get("summary.txt")
        if summary is not None:
            _inspect_table(summary, "summary.txt")
        metadata_candidates = tuple(
            path
            for path in all_files
            if path.name.casefold() == f"{run_name.casefold()}-metadata.json"
        )
        if len(metadata_candidates) > 1:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_SOURCE_ROLE_AMBIGUOUS",
                "Multiple vendor metadata JSON files match the run",
            )
        selected = [
            CompositeSourceFile(evidence, "evidence", "typed_and_preserved"),
            CompositeSourceFile(protein_groups, "protein_groups", "typed_and_preserved"),
            CompositeSourceFile(mqpar, "parameters", "selected_metadata"),
            CompositeSourceFile(mzml_candidates[0], "spectrum_source", "typed"),
        ]
        selected.append(CompositeSourceFile(raw_candidates[0], "vendor_raw", "hashed_not_embedded"))
        selected.append(CompositeSourceFile(fasta_candidates[0], "fasta", "referenced_sequences_only"))
        if summary is not None:
            selected.append(CompositeSourceFile(summary, "summary", "typed_and_preserved"))
        if metadata_candidates:
            selected.append(CompositeSourceFile(metadata_candidates[0], "vendor_metadata", "hashed_provenance_only"))
        selected.sort(key=lambda item: self._relative(root, item.path).encode("utf-8"))
        newest_mtime_ns = max(item.path.stat().st_mtime_ns for item in selected)
        return CompositeBottomUpBundle(
            root=root,
            evidence=evidence,
            protein_groups=protein_groups,
            mqpar=mqpar,
            spectrum_source=mzml_candidates[0],
            raw_source=raw_candidates[0] if raw_candidates else None,
            fasta=fasta_candidates[0] if fasta_candidates else None,
            summary=summary,
            metadata_json=metadata_candidates[0] if metadata_candidates else None,
            report_run_name=run_name,
            evidence_columns=evidence_columns,
            protein_group_columns=group_columns,
            evidence_row_count=evidence_count,
            protein_group_row_count=group_count,
            source_files=tuple(selected),
            output_created_at_millis=max(0, newest_mtime_ns // 1_000_000),
        )

    @staticmethod
    def _relative(root: Path, path: Path) -> str:
        return path.resolve().relative_to(root.resolve()).as_posix()


def _inspect_table(path: Path, label: str) -> tuple[tuple[str, ...], int]:
    if path.stat().st_size > _MAX_TABLE_BYTES:
        raise CompositeBottomUpConversionError(
            "COMPOSITE_RESOURCE_LIMIT_EXCEEDED",
            f"{label} exceeds the controlled table size limit",
        )
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter="\t")
        header = next(reader, None)
        if not header or len(header) != len(set(header)) or any(not item for item in header):
            raise CompositeBottomUpConversionError(
                "COMPOSITE_TABLE_HEADER_INVALID",
                f"{label} has an invalid header",
            )
        count = 0
        for line_no, row in enumerate(reader, start=2):
            if count >= _MAX_TABLE_ROWS:
                raise CompositeBottomUpConversionError(
                    "COMPOSITE_RESOURCE_LIMIT_EXCEEDED",
                    f"{label} exceeds the controlled row-count limit",
                )
            if len(row) != len(header):
                raise CompositeBottomUpConversionError(
                    "COMPOSITE_TABLE_ROW_INVALID",
                    f"{label} row {line_no} has an invalid field count",
                )
            if any(len(value) > _MAX_CELL_CHARACTERS for value in row):
                raise CompositeBottomUpConversionError(
                    "COMPOSITE_RESOURCE_LIMIT_EXCEEDED",
                    f"{label} row {line_no} contains an oversized field",
                )
            count += 1
    if count == 0:
        raise CompositeBottomUpConversionError("COMPOSITE_TABLE_EMPTY", f"{label} contains no rows")
    return tuple(header), count


def _column_values(path: Path, field: str) -> set[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        return {
            str(row.get(field) or "").strip()
            for row in reader
            if str(row.get(field) or "").strip()
        }


def _stem(path: Path) -> str:
    return re.sub(r"(?i)\.(?:mzml|raw)$", "", path.name).casefold()


def _mqpar_fasta_basename(path: Path) -> str:
    try:
        values = {
            Path((element.text or "").strip()).name
            for _event, element in ET.iterparse(path, events=("end",))
            if element.tag.rsplit("}", 1)[-1] == "fastaFilePath"
            and (element.text or "").strip()
        }
    except (ET.ParseError, OSError) as exc:
        raise CompositeBottomUpConversionError(
            "COMPOSITE_MQPAR_INVALID",
            "mqpar.xml cannot be parsed",
        ) from exc
    if len(values) != 1:
        raise CompositeBottomUpConversionError(
            "COMPOSITE_FASTA_REFERENCE_INVALID",
            "mqpar.xml must contain exactly one fastaFilePath basename",
        )
    return next(iter(values))


def _bounded_bundle_files(root: Path) -> tuple[Path, ...]:
    result: list[Path] = []
    pending = [root]
    reparse_flag = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    while pending:
        directory = pending.pop()
        try:
            entries = tuple(os.scandir(directory))
        except OSError as exc:
            raise CompositeBottomUpConversionError(
                "COMPOSITE_SOURCE_NOT_READABLE",
                "The composite bundle tree cannot be enumerated",
            ) from exc
        for entry in entries:
            try:
                attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
                if entry.is_symlink() or attributes & reparse_flag:
                    raise CompositeBottomUpConversionError(
                        "COMPOSITE_SOURCE_LINK_FORBIDDEN",
                        "Composite bundle trees cannot contain symbolic links or reparse points",
                    )
                path = Path(entry.path)
                path.resolve().relative_to(root)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    result.append(path)
                    if len(result) > _MAX_BUNDLE_FILES:
                        raise CompositeBottomUpConversionError(
                            "COMPOSITE_RESOURCE_LIMIT_EXCEEDED",
                            "The composite bundle contains too many files",
                        )
            except OSError as exc:
                raise CompositeBottomUpConversionError(
                    "COMPOSITE_SOURCE_NOT_READABLE",
                    "A composite bundle entry cannot be inspected",
                ) from exc
            except ValueError as exc:
                raise CompositeBottomUpConversionError(
                    "COMPOSITE_SOURCE_ESCAPE",
                    "A composite bundle entry resolves outside the bundle root",
                ) from exc
    return tuple(result)


def _is_link_or_reparse(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    reparse_flag = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)
