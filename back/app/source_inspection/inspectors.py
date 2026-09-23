"""Format-neutral, streaming source inspectors."""

from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
import math
import re
import xml.parsers.expat as expat
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .budget import BudgetTracker, BudgetedReader, InspectionBudgetExceeded
from .contracts import SniffResult
from .observation import InspectionOutcome


_ABSOLUTE_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_INTEGER = re.compile(r"^[+-]?(?:0|[1-9]\d*)$")


@dataclass(frozen=True)
class InspectionContext:
    path: Path
    relative_path: str
    sniff: SniffResult
    tracker: BudgetTracker


class SourceInspector(Protocol):
    inspector_id: str
    inspector_version: str
    formats: frozenset[str]

    def inspect(self, context: InspectionContext) -> InspectionOutcome: ...


def _encoding(context: InspectionContext) -> str | None:
    value = context.sniff.encoding
    return value if value in {"utf-8", "utf-8-sig", "utf-16"} else None


def _open_text(context: InspectionContext) -> io.TextIOWrapper:
    encoding = _encoding(context)
    if encoding is None:
        raise ValueError(f"text encoding is ambiguous or unsupported: {context.sniff.encoding or 'binary'}")
    raw = context.path.open("rb")
    metered = BudgetedReader(raw, context.tracker, file_size=context.path.stat().st_size)
    return io.TextIOWrapper(metered, encoding=encoding, errors="strict", newline="")


def _partial_reasons(context: InspectionContext, extra: list[str] | None = None) -> list[str]:
    values = list(extra or [])
    values.extend(f"budget_{item}" for item in context.tracker.exhausted)
    return list(dict.fromkeys(values))


def _status_for_stream(context: InspectionContext, reasons: list[str]) -> str:
    return "PARTIAL" if reasons or context.tracker.exhausted else "COMPLETE"


class DelimitedInspector:
    inspector_id = "generic-delimited-table"
    inspector_version = "1.0.0"
    formats = frozenset({"csv", "tsv", "delimited_text"})

    def inspect(self, context: InspectionContext) -> InspectionOutcome:
        if _encoding(context) is None:
            return InspectionOutcome(
                status="UNSUPPORTED",
                facts={"encoding": context.sniff.encoding},
                warnings=["Delimited text inspection requires UTF-8 or a BOM-declared UTF-16 encoding."],
            )
        delimiter = _delimiter(context)
        rows_seen = 0
        header: list[str] = []
        tracked_header: list[str] = []
        stats: dict[str, dict[str, Any]] = {}
        reasons: list[str] = []
        invalid: str | None = None
        try:
            with _open_text(context) as stream:
                reader = csv.reader(stream, delimiter=delimiter)
                try:
                    header = list(next(reader))
                except StopIteration:
                    invalid = "Delimited table is empty."
                if invalid is None and (not header or any(not item for item in header)):
                    invalid = "Delimited table header contains an empty field name."
                if invalid is None and len(set(header)) != len(header):
                    invalid = "Delimited table header contains duplicate field names."
                if invalid is None:
                    tracked_header = header[: context.tracker.limits.max_fields]
                    if len(header) > len(tracked_header):
                        reasons.append("field_limit")
                    stats = {name: _new_column_stats() for name in tracked_header}
                    for row in reader:
                        context.tracker.take_row()
                        rows_seen += 1
                        if len(row) != len(header):
                            invalid = (
                                f"Row {rows_seen + 1} has {len(row)} fields; the header has {len(header)}."
                            )
                            break
                        for index, name in enumerate(tracked_header):
                            _update_column_stats(stats[name], row[index], context.tracker.limits.max_sample_values)
        except InspectionBudgetExceeded:
            pass
        except (UnicodeDecodeError, csv.Error, OSError) as exc:
            invalid = f"Delimited table could not be parsed: {str(exc)[:300]}"

        facts = {
            "delimiter": delimiter,
            "encoding": context.sniff.encoding,
            "column_count": len(header),
            "columns": [_finish_column_stats(name, stats[name]) for name in tracked_header],
            "uninspected_column_count": max(0, len(header) - len(tracked_header)),
            "rows_observed": rows_seen,
            "row_count": rows_seen if not context.tracker.exhausted and invalid is None else None,
            "row_count_exact": not context.tracker.exhausted and invalid is None,
            "raw_rows_returned": False,
        }
        if invalid is not None:
            return InspectionOutcome(status="INVALID", facts=facts, warnings=[invalid])
        reasons = _partial_reasons(context, reasons)
        return InspectionOutcome(
            status=_status_for_stream(context, reasons),
            facts=facts,
            truncation_reasons=reasons,
        )


class JsonLinesInspector:
    inspector_id = "generic-json-lines"
    inspector_version = "1.0.0"
    formats = frozenset({"jsonl"})

    def inspect(self, context: InspectionContext) -> InspectionOutcome:
        if _encoding(context) is None:
            return InspectionOutcome(
                status="UNSUPPORTED",
                facts={"encoding": context.sniff.encoding},
                warnings=["JSON Lines inspection requires UTF-8 or a BOM-declared UTF-16 encoding."],
            )
        fields: list[str] = []
        stats: dict[str, dict[str, Any]] = {}
        rows_seen = 0
        untracked_field_occurrences = 0
        reasons: list[str] = []
        invalid: str | None = None
        try:
            with _open_text(context) as stream:
                for line_number, line in enumerate(stream, start=1):
                    if not line.strip():
                        continue
                    context.tracker.take_row()
                    rows_seen += 1
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError as exc:
                        invalid = f"JSON Lines record at physical line {line_number} is invalid: {exc.msg}."
                        break
                    if not isinstance(value, dict):
                        invalid = f"JSON Lines record at physical line {line_number} is not an object."
                        break
                    for raw_name in value:
                        name = str(raw_name)
                        if name in stats:
                            continue
                        if len(fields) >= context.tracker.limits.max_fields:
                            if "field_limit" not in reasons:
                                reasons.append("field_limit")
                            continue
                        fields.append(name)
                        stats[name] = _new_column_stats(null_count=rows_seen - 1)
                    for name in fields:
                        _update_column_stats(
                            stats[name],
                            value.get(name),
                            context.tracker.limits.max_sample_values,
                            native=True,
                        )
                    untracked_field_occurrences += sum(1 for raw_name in value if str(raw_name) not in stats)
        except InspectionBudgetExceeded:
            pass
        except (UnicodeDecodeError, OSError) as exc:
            invalid = f"JSON Lines file could not be parsed: {str(exc)[:300]}"

        facts = {
            "encoding": context.sniff.encoding,
            "tracked_field_count": len(fields),
            "field_count_lower_bound": len(fields),
            "field_count_exact": "field_limit" not in reasons,
            "fields": [_finish_column_stats(name, stats[name]) for name in fields],
            "untracked_field_occurrences": untracked_field_occurrences,
            "rows_observed": rows_seen,
            "row_count": rows_seen if not context.tracker.exhausted and invalid is None else None,
            "row_count_exact": not context.tracker.exhausted and invalid is None,
            "raw_rows_returned": False,
        }
        if invalid is not None:
            return InspectionOutcome(status="INVALID", facts=facts, warnings=[invalid])
        reasons = _partial_reasons(context, reasons)
        return InspectionOutcome(
            status=_status_for_stream(context, reasons),
            facts=facts,
            truncation_reasons=reasons,
        )


class ParquetInspector:
    inspector_id = "generic-parquet-metadata"
    inspector_version = "1.0.0"
    formats = frozenset({"parquet"})

    def inspect(self, context: InspectionContext) -> InspectionOutcome:
        try:
            import pyarrow.parquet as pq
        except ImportError:
            return InspectionOutcome(
                status="UNSUPPORTED",
                warnings=["Parquet metadata inspection requires the optional pyarrow dependency."],
            )

        reasons: list[str] = []
        try:
            raw = context.path.open("rb")
            with BudgetedReader(raw, context.tracker, file_size=context.path.stat().st_size) as stream:
                parquet = pq.ParquetFile(stream)
                metadata = parquet.metadata
                arrow_schema = parquet.schema_arrow
                fields = []
                for field in list(arrow_schema)[: context.tracker.limits.max_fields]:
                    fields.append(
                        {
                            "name": field.name,
                            "type": str(field.type),
                            "nullable": bool(field.nullable),
                        }
                    )
                if len(arrow_schema) > len(fields):
                    reasons.append("field_limit")
                row_groups = []
                for index in range(min(metadata.num_row_groups, context.tracker.limits.max_sample_values)):
                    group = metadata.row_group(index)
                    row_groups.append(
                        {
                            "index": index,
                            "row_count": int(group.num_rows),
                            "total_byte_size": int(group.total_byte_size),
                        }
                    )
                facts = {
                    "row_count": int(metadata.num_rows),
                    "row_count_exact": True,
                    "row_group_count": int(metadata.num_row_groups),
                    "column_count": len(arrow_schema),
                    "fields": fields,
                    "uninspected_column_count": max(0, len(arrow_schema) - len(fields)),
                    "created_by": str(metadata.created_by) if metadata.created_by else None,
                    "format_version": str(metadata.format_version),
                    "serialized_metadata_size": int(metadata.serialized_size),
                    "sampled_row_groups": row_groups,
                    "data_pages_read": False,
                }
        except InspectionBudgetExceeded:
            facts = {"metadata_complete": False, "data_pages_read": False}
        except Exception as exc:  # pyarrow exposes version-specific exception classes
            if context.tracker.exhausted:
                facts = {"metadata_complete": False, "data_pages_read": False}
            else:
                return InspectionOutcome(
                    status="INVALID",
                    facts={"data_pages_read": False},
                    warnings=[f"Parquet metadata could not be parsed: {str(exc)[:300]}"],
                )
        reasons = _partial_reasons(context, reasons)
        return InspectionOutcome(
            status=_status_for_stream(context, reasons),
            facts=facts,
            truncation_reasons=reasons,
        )


class JsonInspector:
    inspector_id = "generic-json-structure"
    inspector_version = "1.0.0"
    formats = frozenset({"json"})

    def inspect(self, context: InspectionContext) -> InspectionOutcome:
        if _encoding(context) is None:
            return InspectionOutcome(
                status="UNSUPPORTED",
                facts={"encoding": context.sniff.encoding},
                warnings=["JSON inspection requires UTF-8 or a BOM-declared UTF-16 encoding."],
            )
        file_size = context.path.stat().st_size
        data = b""
        try:
            raw = context.path.open("rb")
            with BudgetedReader(raw, context.tracker, file_size=file_size) as stream:
                data = stream.read()
        except InspectionBudgetExceeded:
            pass
        if len(data) != file_size:
            prefix = data.lstrip()
            root_hint = "object" if prefix.startswith(b"{") else "array" if prefix.startswith(b"[") else "unknown"
            return InspectionOutcome(
                status="PARTIAL",
                facts={
                    "encoding": context.sniff.encoding,
                    "parsed": False,
                    "root_type_hint": root_hint,
                    "raw_value_returned": False,
                },
                warnings=["JSON exceeded the byte budget; an incomplete prefix was not presented as parsed JSON."],
                truncation_reasons=_partial_reasons(context, ["incomplete_json_prefix"]),
            )
        try:
            text = data.decode(_encoding(context) or "utf-8")
            value = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return InspectionOutcome(
                status="INVALID",
                facts={"encoding": context.sniff.encoding, "parsed": False, "raw_value_returned": False},
                warnings=[f"JSON could not be parsed: {str(exc)[:300]}"],
            )
        reasons: list[str] = []
        structure = _summarize_json(value, context, depth=0, reasons=reasons)
        reasons = _partial_reasons(context, reasons)
        return InspectionOutcome(
            status=_status_for_stream(context, reasons),
            facts={
                "encoding": context.sniff.encoding,
                "parsed": True,
                "structure": structure,
                "raw_value_returned": False,
            },
            truncation_reasons=reasons,
            source_content_sha256=hashlib.sha256(data).hexdigest(),
        )


class XmlInspector:
    inspector_id = "generic-xml-structure"
    inspector_version = "1.0.0"
    formats = frozenset({"xml"})

    def inspect(self, context: InspectionContext) -> InspectionOutcome:
        summary = _stream_xml(context)
        return summary


class MzmlInspector:
    inspector_id = "mzml-metadata-stream"
    inspector_version = "1.0.0"
    formats = frozenset({"mzml"})

    def inspect(self, context: InspectionContext) -> InspectionOutcome:
        return _stream_mzml(context)


class FastaInspector:
    inspector_id = "fasta-metadata-stream"
    inspector_version = "1.0.0"
    formats = frozenset({"fasta"})

    def inspect(self, context: InspectionContext) -> InspectionOutcome:
        if _encoding(context) is None:
            return InspectionOutcome(
                status="UNSUPPORTED",
                facts={"encoding": context.sniff.encoding, "sequences_returned": False},
                warnings=["FASTA inspection requires UTF-8 or a BOM-declared UTF-16 encoding."],
            )
        return _stream_fasta(context)


def _delimiter(context: InspectionContext) -> str:
    if context.sniff.detected_format == "csv":
        return ","
    return "\t"


def _new_column_stats(*, null_count: int = 0) -> dict[str, Any]:
    return {
        "null_count": null_count,
        "non_null_count": 0,
        "type_counts": Counter(),
        "samples": [],
        "minimum": None,
        "maximum": None,
    }


def _update_column_stats(
    stats: dict[str, Any],
    raw: Any,
    max_samples: int,
    *,
    native: bool = False,
) -> None:
    value_type, value, sample = _classify_value(raw, native=native)
    if value_type == "null":
        stats["null_count"] += 1
        return
    stats["non_null_count"] += 1
    stats["type_counts"][value_type] += 1
    if value_type in {"integer", "float"} and isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        stats["minimum"] = numeric if stats["minimum"] is None else min(stats["minimum"], numeric)
        stats["maximum"] = numeric if stats["maximum"] is None else max(stats["maximum"], numeric)
    samples: list[Any] = stats["samples"]
    if len(samples) < max_samples and sample not in samples:
        samples.append(sample)


def _classify_value(raw: Any, *, native: bool) -> tuple[str, Any, Any]:
    if raw is None:
        return "null", None, None
    if native:
        if isinstance(raw, bool):
            return "boolean", raw, raw
        if isinstance(raw, int):
            return "integer", raw, raw
        if isinstance(raw, float):
            if not math.isfinite(raw):
                return "null", None, str(raw)
            return "float", raw, raw
        if isinstance(raw, dict):
            return "object", raw, "<object>"
        if isinstance(raw, list):
            return "array", raw, "<array>"
        text = str(raw).strip()
        return ("null", None, None) if not text else ("string", text, _redact_text(text)[:160])

    text = str(raw).strip()
    if not text:
        return "null", None, None
    folded = text.casefold()
    if folded in {"true", "false"}:
        value = folded == "true"
        return "boolean", value, value
    if _INTEGER.fullmatch(text):
        try:
            value = int(text)
        except ValueError:
            pass
        else:
            return "integer", value, value
    try:
        value = float(text)
    except ValueError:
        value = None
    if value is not None and math.isfinite(value):
        return "float", value, value
    return "string", text, _redact_text(text)[:160]


def _finish_column_stats(name: str, stats: dict[str, Any]) -> dict[str, Any]:
    type_counts = dict(sorted(stats["type_counts"].items()))
    non_null_types = set(type_counts)
    if not non_null_types:
        inferred = "null"
    elif non_null_types <= {"integer"}:
        inferred = "integer"
    elif non_null_types <= {"integer", "float"}:
        inferred = "float"
    elif len(non_null_types) == 1:
        inferred = next(iter(non_null_types))
    else:
        inferred = "mixed"
    return {
        "name": name,
        "inferred_type": inferred,
        "null_count": stats["null_count"],
        "non_null_count": stats["non_null_count"],
        "type_counts": type_counts,
        "samples": stats["samples"],
        "minimum": stats["minimum"],
        "maximum": stats["maximum"],
    }


def _summarize_json(
    value: Any,
    context: InspectionContext,
    *,
    depth: int,
    reasons: list[str],
) -> dict[str, Any]:
    if depth >= context.tracker.limits.max_depth:
        if "depth_limit" not in reasons:
            reasons.append("depth_limit")
        return {"type": "truncated", "reason": "depth_limit"}
    try:
        context.tracker.take_element()
    except InspectionBudgetExceeded:
        return {"type": "truncated", "reason": "element_or_time_budget"}
    if isinstance(value, dict):
        entries = []
        field_count = len(value)
        for raw_name, child in itertools.islice(value.items(), context.tracker.limits.max_fields):
            entries.append(
                {
                    "name": str(raw_name)[:300],
                    "value": _summarize_json(child, context, depth=depth + 1, reasons=reasons),
                }
            )
        if field_count > len(entries) and "field_limit" not in reasons:
            reasons.append("field_limit")
        return {"type": "object", "field_count": field_count, "fields": entries}
    if isinstance(value, list):
        sample_count = min(len(value), context.tracker.limits.max_sample_values)
        samples = [
            _summarize_json(item, context, depth=depth + 1, reasons=reasons)
            for item in value[:sample_count]
        ]
        if len(value) > sample_count and "array_sample_limit" not in reasons:
            reasons.append("array_sample_limit")
        return {"type": "array", "length": len(value), "sample_items": samples}
    value_type, _value, sample = _classify_value(value, native=True)
    return {"type": value_type, "sample": sample}


class _UnsafeXml(ValueError):
    pass


def _safe_expat_parser() -> expat.xmlparser:
    parser = expat.ParserCreate(namespace_separator="}")

    def reject_doctype(*_args: Any) -> None:
        raise _UnsafeXml("XML DTD and entity declarations are not allowed during inspection")

    parser.StartDoctypeDeclHandler = reject_doctype
    parser.ExternalEntityRefHandler = lambda *_args: 0
    return parser


def _local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _stream_xml(context: InspectionContext) -> InspectionOutcome:
    parser = _safe_expat_parser()
    tag_counts: dict[str, int] = {}
    untracked_tags = 0
    leaf_samples: list[dict[str, str]] = []
    stack: list[dict[str, Any]] = []
    root_name: str | None = None
    reasons: list[str] = []
    invalid: str | None = None
    stream_complete = False

    def start(name: str, _attributes: dict[str, str]) -> None:
        nonlocal root_name, untracked_tags
        context.tracker.take_element()
        local = _local_name(name)
        root_name = root_name or local
        if len(stack) >= context.tracker.limits.max_depth:
            if "depth_limit" not in reasons:
                reasons.append("depth_limit")
            raise InspectionBudgetExceeded("elements")
        if stack:
            stack[-1]["has_child"] = True
        stack.append({"name": local, "text": "", "has_child": False})
        if local in tag_counts:
            tag_counts[local] += 1
        elif len(tag_counts) < context.tracker.limits.max_fields:
            tag_counts[local] = 1
        else:
            untracked_tags += 1
            if "field_limit" not in reasons:
                reasons.append("field_limit")

    def characters(value: str) -> None:
        if len(leaf_samples) >= context.tracker.limits.max_sample_values and value.strip():
            if "leaf_sample_limit" not in reasons:
                reasons.append("leaf_sample_limit")
            return
        if not stack or stack[-1]["has_child"]:
            return
        current = stack[-1]
        remaining = 160 - len(current["text"])
        if remaining > 0:
            current["text"] += value[:remaining]

    def end(_name: str) -> None:
        if not stack:
            return
        current = stack.pop()
        text = str(current["text"]).strip()
        if text and not current["has_child"] and len(leaf_samples) < context.tracker.limits.max_sample_values:
            leaf_samples.append({"tag": current["name"], "value": _redact_text(text)[:160]})

    parser.StartElementHandler = start
    parser.CharacterDataHandler = characters
    parser.EndElementHandler = end
    try:
        raw = context.path.open("rb")
        with BudgetedReader(raw, context.tracker, file_size=context.path.stat().st_size) as stream:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    parser.Parse(b"", True)
                    stream_complete = True
                    break
                parser.Parse(chunk, False)
    except InspectionBudgetExceeded:
        pass
    except (_UnsafeXml, expat.ExpatError, OSError) as exc:
        invalid = str(exc)[:300]

    facts = {
        "root_element": root_name,
        "elements_observed": context.tracker.elements_read,
        "element_count": context.tracker.elements_read if stream_complete and invalid is None else None,
        "element_count_exact": stream_complete and invalid is None,
        "unique_tags_observed": len(tag_counts),
        "tag_counts": tag_counts,
        "untracked_tag_occurrences": untracked_tags,
        "leaf_value_samples": leaf_samples,
        "raw_document_returned": False,
    }
    if invalid is not None and not context.tracker.exhausted:
        return InspectionOutcome(status="INVALID", facts=facts, warnings=[f"XML could not be parsed safely: {invalid}"])
    reasons = _partial_reasons(context, reasons)
    return InspectionOutcome(
        status=_status_for_stream(context, reasons),
        facts=facts,
        truncation_reasons=reasons,
    )


def _stream_mzml(context: InspectionContext) -> InspectionOutcome:
    parser = _safe_expat_parser()
    root_name: str | None = None
    depth = 0
    current: dict[str, Any] | None = None
    spectrum_count = 0
    chromatogram_count = 0
    ms_levels: Counter[int] = Counter()
    representations: Counter[str] = Counter()
    polarities: Counter[str] = Counter()
    declared_peak_pairs: Counter[int] = Counter()
    retention_min: float | None = None
    retention_max: float | None = None
    unresolved_retention_units: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    reasons: list[str] = []
    invalid: str | None = None
    stream_complete = False

    def start(name: str, attributes: dict[str, str]) -> None:
        nonlocal root_name, depth, current, chromatogram_count
        local = _local_name(name)
        root_name = root_name or local
        depth += 1
        if depth > context.tracker.limits.max_depth:
            if "depth_limit" not in reasons:
                reasons.append("depth_limit")
            raise InspectionBudgetExceeded("elements")
        if local == "spectrum":
            context.tracker.take_element()
            current = {
                "native_id": str(attributes.get("id") or "")[:300],
                "scan_number": _scan_number(str(attributes.get("id") or "")),
                "ms_level": None,
                "rt_seconds": None,
                "rt_value": None,
                "rt_unit_accession": None,
                "rt_unit_name": None,
                "declared_peak_count": _optional_int(attributes.get("defaultArrayLength")),
                "representation": None,
                "polarity": None,
            }
        elif local == "chromatogram":
            context.tracker.take_element()
            chromatogram_count += 1
        elif local == "cvParam" and current is not None:
            accession = str(attributes.get("accession") or "")
            name_text = str(attributes.get("name") or "").casefold()
            raw_value = attributes.get("value")
            if accession == "MS:1000511" or name_text == "ms level":
                current["ms_level"] = _optional_int(raw_value)
            elif accession == "MS:1000016" or name_text == "scan start time":
                parsed = _optional_float(raw_value)
                if parsed is not None:
                    unit_accession = str(attributes.get("unitAccession") or "")
                    unit_name = str(attributes.get("unitName") or "").casefold()
                    current["rt_value"] = parsed
                    current["rt_unit_accession"] = unit_accession or None
                    current["rt_unit_name"] = unit_name or None
                    if unit_accession == "UO:0000031" or "minute" in unit_name:
                        current["rt_seconds"] = parsed * 60
                    elif unit_accession == "UO:0000010" or "second" in unit_name:
                        current["rt_seconds"] = parsed
            elif accession == "MS:1000127" or name_text == "centroid spectrum":
                current["representation"] = "centroid"
            elif accession == "MS:1000128" or name_text == "profile spectrum":
                current["representation"] = "profile"
            elif accession == "MS:1000130" or name_text == "positive scan":
                current["polarity"] = "positive"
            elif accession == "MS:1000129" or name_text == "negative scan":
                current["polarity"] = "negative"

    def end(name: str) -> None:
        nonlocal depth, current, spectrum_count, retention_min, retention_max
        local = _local_name(name)
        if local == "spectrum" and current is not None:
            spectrum_count += 1
            level = current.get("ms_level")
            if isinstance(level, int):
                ms_levels[level] += 1
                peak_count = current.get("declared_peak_count")
                if isinstance(peak_count, int):
                    declared_peak_pairs[level] += peak_count
            representation = current.get("representation")
            if representation:
                representations[str(representation)] += 1
            polarity = current.get("polarity")
            if polarity:
                polarities[str(polarity)] += 1
            rt = current.get("rt_seconds")
            if isinstance(rt, float):
                retention_min = rt if retention_min is None else min(retention_min, rt)
                retention_max = rt if retention_max is None else max(retention_max, rt)
            elif current.get("rt_value") is not None:
                unit_label = str(
                    current.get("rt_unit_accession")
                    or current.get("rt_unit_name")
                    or "missing"
                )
                unresolved_retention_units[unit_label] += 1
            if len(samples) < context.tracker.limits.max_sample_values:
                samples.append(dict(current))
            current = None
        depth = max(0, depth - 1)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        raw = context.path.open("rb")
        with BudgetedReader(raw, context.tracker, file_size=context.path.stat().st_size) as stream:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    parser.Parse(b"", True)
                    stream_complete = True
                    break
                parser.Parse(chunk, False)
    except InspectionBudgetExceeded:
        pass
    except (_UnsafeXml, expat.ExpatError, OSError) as exc:
        invalid = str(exc)[:300]

    facts = {
        "root_element": root_name,
        "spectra_observed": spectrum_count,
        "spectrum_count": spectrum_count if stream_complete and invalid is None else None,
        "spectrum_count_exact": stream_complete and invalid is None,
        "ms_level_counts_observed": {str(key): value for key, value in sorted(ms_levels.items())},
        "declared_peak_pair_counts_observed": {
            **{f"ms{key}": value for key, value in sorted(declared_peak_pairs.items())},
            "total": sum(declared_peak_pairs.values()),
        },
        "retention_time_seconds_observed": [retention_min, retention_max],
        "unresolved_retention_time_units": dict(unresolved_retention_units),
        "representations_observed": dict(representations),
        "polarities_observed": dict(polarities),
        "chromatograms_observed": chromatogram_count,
        "sampled_spectrum_metadata": samples,
        "peak_arrays_returned": False,
        "binary_values_decoded": False,
    }
    if root_name not in {"mzML", "indexedmzML"} and invalid is None and not context.tracker.exhausted:
        invalid = f"root element is {root_name!r}, not mzML or indexedmzML"
    if invalid is not None and not context.tracker.exhausted:
        return InspectionOutcome(status="INVALID", facts=facts, warnings=[f"mzML could not be parsed: {invalid}"])
    reasons = _partial_reasons(context, reasons)
    return InspectionOutcome(
        status=_status_for_stream(context, reasons),
        facts=facts,
        truncation_reasons=reasons,
    )


def _stream_fasta(context: InspectionContext) -> InspectionOutcome:
    records = 0
    total_residues = 0
    minimum_length: int | None = None
    maximum_length: int | None = None
    alphabet: set[str] = set()
    alphabet_exact = True
    identifier_samples: list[str] = []
    identifier_hashes: set[str] = set()
    sequence_hashes: set[str] = set()
    identifiers_exact = True
    sequence_hashes_exact = True
    current_identifier_hash: str | None = None
    current_length = 0
    current_digest = hashlib.sha256()
    invalid: str | None = None

    def finalize_record() -> None:
        nonlocal records
        nonlocal total_residues
        nonlocal minimum_length
        nonlocal maximum_length
        nonlocal identifiers_exact
        nonlocal sequence_hashes_exact
        if current_identifier_hash is None:
            return
        context.tracker.take_element()
        records += 1
        total_residues += current_length
        minimum_length = current_length if minimum_length is None else min(minimum_length, current_length)
        maximum_length = current_length if maximum_length is None else max(maximum_length, current_length)
        if current_identifier_hash in identifier_hashes:
            pass
        elif len(identifier_hashes) < context.tracker.limits.max_tracked_distinct:
            identifier_hashes.add(current_identifier_hash)
        else:
            identifiers_exact = False
        sequence_digest = current_digest.hexdigest()
        if sequence_digest in sequence_hashes:
            pass
        elif len(sequence_hashes) < context.tracker.limits.max_tracked_distinct:
            sequence_hashes.add(sequence_digest)
        else:
            sequence_hashes_exact = False

    try:
        with _open_text(context) as stream:
            for line_number, line in enumerate(stream, start=1):
                text = line.strip()
                if not text or text.startswith(";"):
                    continue
                if text.startswith(">"):
                    finalize_record()
                    identifier = text[1:].split(None, 1)[0]
                    if not identifier:
                        invalid = f"FASTA header at line {line_number} has no identifier."
                        break
                    current_identifier_hash = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
                    if len(identifier_samples) < context.tracker.limits.max_sample_values:
                        identifier_samples.append(_redact_text(identifier)[:160])
                    current_length = 0
                    current_digest = hashlib.sha256()
                    continue
                if current_identifier_hash is None:
                    invalid = f"FASTA sequence data appears before the first header at line {line_number}."
                    break
                normalized = "".join(text.split()).upper()
                current_length += len(normalized)
                for residue in normalized:
                    if residue in alphabet:
                        continue
                    if len(alphabet) < context.tracker.limits.max_tracked_distinct:
                        alphabet.add(residue)
                    else:
                        alphabet_exact = False
                current_digest.update(normalized.encode("utf-8"))
            else:
                finalize_record()
    except InspectionBudgetExceeded:
        pass
    except (UnicodeDecodeError, OSError) as exc:
        invalid = f"FASTA could not be read: {str(exc)[:300]}"

    complete = not context.tracker.exhausted and invalid is None
    unique_identifier_count = len(identifier_hashes) if complete and identifiers_exact else None
    unique_sequence_count = len(sequence_hashes) if complete and sequence_hashes_exact else None
    facts = {
        "records_observed": records,
        "record_count": records if complete else None,
        "record_count_exact": complete,
        "total_residues_observed": total_residues,
        "length_range_observed": [minimum_length, maximum_length] if records else None,
        "residue_alphabet_observed": "".join(sorted(alphabet)),
        "residue_alphabet_exact": alphabet_exact,
        "identifier_samples": identifier_samples,
        "unique_identifier_count": unique_identifier_count,
        "unique_identifier_count_lower_bound": len(identifier_hashes),
        "unique_sequence_count": unique_sequence_count,
        "unique_sequence_count_lower_bound": len(sequence_hashes),
        "duplicate_sequence_count": records - unique_sequence_count if unique_sequence_count is not None else None,
        "sequences_returned": False,
    }
    if invalid is not None:
        return InspectionOutcome(status="INVALID", facts=facts, warnings=[invalid])
    if complete and records == 0:
        return InspectionOutcome(status="INVALID", facts=facts, warnings=["FASTA contains no records."])
    reasons = []
    if not identifiers_exact:
        reasons.append("distinct_identifier_limit")
    if not sequence_hashes_exact:
        reasons.append("distinct_sequence_limit")
    if not alphabet_exact:
        reasons.append("distinct_residue_limit")
    reasons = _partial_reasons(context, reasons)
    return InspectionOutcome(
        status=_status_for_stream(context, reasons),
        facts=facts,
        truncation_reasons=reasons,
    )


def _scan_number(native_id: str) -> int | None:
    match = re.search(r"(?:^|\s)scan=(\d+)(?:\s|$)", native_id)
    return int(match.group(1)) if match else None


def _optional_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _redact_text(value: str) -> str:
    text = value.strip()
    if _ABSOLUTE_WINDOWS_PATH.match(text) or text.startswith(("/", "\\\\")):
        return f"<redacted-absolute-path>/{Path(text.replace('\\\\', '/')).name}"
    return text
