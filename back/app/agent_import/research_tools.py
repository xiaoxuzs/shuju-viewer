"""Case-scoped, read-only tools exposed to the Kimi research agent."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import numpy as np
from pyteomics import mzml

from app.agent_import.source_sampling import _safe_sample_path, summarize_source_root
from app.agent_import.zp_capabilities import build_zp_capabilities
from app.spectrum_memory.mzml_spectrum_extract import extract_precursor, parse_scan, rt_seconds


MAX_TOOL_RESULT_BYTES = 128 * 1024
MAX_DISTINCT_SAMPLES = 5
MAX_SAMPLE_SCANS = 5
_ABSOLUTE_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _function_tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


class AgentResearchToolbox:
    """Dispatch a fixed set of inspection functions inside one Case root."""

    def __init__(self, source_root: str | Path) -> None:
        self.root = Path(source_root).expanduser().resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("research source root must be a directory")
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "inspect_source_tree": self._inspect_source_tree,
            "inspect_tabular_file": self._inspect_tabular_file,
            "inspect_json_file": self._inspect_json_file,
            "inspect_xml_file": self._inspect_xml_file,
            "inspect_mzml": self._inspect_mzml,
            "inspect_fasta": self._inspect_fasta,
            "hash_source_file": self._hash_source_file,
            "validate_table_relation": self._validate_table_relation,
            "validate_scan_relation": self._validate_scan_relation,
            "validate_fasta_relation": self._validate_fasta_relation,
            "inspect_viewer_capabilities": self._inspect_viewer_capabilities,
        }

    def definitions(self) -> list[dict[str, Any]]:
        relative_path = {
            "type": "string",
            "description": "Case-relative file path. Absolute paths and parent traversal are forbidden.",
        }
        string_array = {"type": "array", "items": {"type": "string"}, "maxItems": 100}
        return [
            _function_tool(
                "inspect_source_tree",
                "Inventory the Case source tree before inspecting individual files.",
                {},
            ),
            _function_tool(
                "inspect_tabular_file",
                "Stream a CSV, TSV, TXT, or JSONL file and return its schema, row counts, "
                "nulls, numeric ranges, and bounded value examples.",
                {
                    "relative_path": relative_path,
                    "columns": string_array,
                },
                ["relative_path"],
            ),
            _function_tool(
                "inspect_json_file",
                "Read a bounded JSON metadata file and redact absolute local paths.",
                {"relative_path": relative_path},
                ["relative_path"],
            ),
            _function_tool(
                "inspect_xml_file",
                "Inspect XML structure and selected leaf values without returning the whole document.",
                {
                    "relative_path": relative_path,
                    "tag_names": string_array,
                },
                ["relative_path"],
            ),
            _function_tool(
                "inspect_mzml",
                "Stream an mzML file and summarize spectra, peak arrays, retention times, "
                "precursors, activation, charge, and chromatograms without returning peak values.",
                {"relative_path": relative_path},
                ["relative_path"],
            ),
            _function_tool(
                "inspect_fasta",
                "Inspect FASTA counts, identifiers, lengths, duplicate sequences, residue alphabet, "
                "and optional accession matches without returning sequences.",
                {
                    "relative_path": relative_path,
                    "accessions": string_array,
                },
                ["relative_path"],
            ),
            _function_tool(
                "hash_source_file",
                "Compute a source file SHA-1 or SHA-256 locally for provenance. File bytes are never returned.",
                {
                    "relative_path": relative_path,
                    "algorithm": {"type": "string", "enum": ["sha1", "sha256"]},
                },
                ["relative_path", "algorithm"],
            ),
            _function_tool(
                "validate_table_relation",
                "Validate references from one table field to another table field with an optional semicolon splitter.",
                {
                    "left_path": relative_path,
                    "left_field": {"type": "string"},
                    "right_path": relative_path,
                    "right_field": {"type": "string"},
                    "split_semicolon": {"type": "boolean"},
                },
                ["left_path", "left_field", "right_path", "right_field", "split_semicolon"],
            ),
            _function_tool(
                "validate_scan_relation",
                "Compare scan numbers in a table field with real scan numbers in an mzML file.",
                {
                    "table_path": relative_path,
                    "scan_field": {"type": "string"},
                    "mzml_path": relative_path,
                    "split_semicolon": {"type": "boolean"},
                },
                ["table_path", "scan_field", "mzml_path", "split_semicolon"],
            ),
            _function_tool(
                "validate_fasta_relation",
                "Compare accessions in a table field with FASTA identifiers.",
                {
                    "table_path": relative_path,
                    "accession_field": {"type": "string"},
                    "fasta_path": relative_path,
                    "split_semicolon": {"type": "boolean"},
                },
                ["table_path", "accession_field", "fasta_path", "split_semicolon"],
            ),
            _function_tool(
                "inspect_viewer_capabilities",
                "Inspect the current fixed ZP writer, source adapters, logical blocks, and extension capabilities.",
                {},
            ),
        ]

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._handlers)

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = self._handlers.get(name)
        if handler is None:
            raise ValueError(f"unknown local research tool: {name}")
        result = handler(arguments)
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_TOOL_RESULT_BYTES:
            raise ValueError(f"tool result exceeds {MAX_TOOL_RESULT_BYTES} bytes")
        return result

    def _resolve(self, relative_path: object) -> Path:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("relative_path must be a non-empty string")
        normalized = relative_path.strip().replace("\\", "/")
        candidate = PurePosixPath(normalized)
        if (
            candidate.is_absolute()
            or _ABSOLUTE_WINDOWS_PATH.match(normalized)
            or any(part == ".." for part in candidate.parts)
        ):
            raise ValueError("relative_path must stay inside the Case source root")
        return _safe_sample_path(self.root, candidate.as_posix())

    def _inspect_source_tree(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        summary = summarize_source_root(self.root)
        return {
            "schema_version": summary.get("schema_version"),
            "file_count": summary.get("file_count"),
            "truncated": summary.get("truncated"),
            "files": summary.get("files", []),
            "file_content_returned_to_model": False,
        }

    def _inspect_tabular_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve(arguments.get("relative_path"))
        requested = arguments.get("columns") or []
        if not isinstance(requested, list) or not all(isinstance(item, str) for item in requested):
            raise ValueError("columns must be a list of strings")
        if path.suffix.casefold() in {".jsonl", ".ndjson"}:
            return _inspect_jsonl(path, requested)
        return _inspect_delimited(path, requested)

    def _inspect_json_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve(arguments.get("relative_path"))
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("JSON metadata inspection is limited to 4 MiB")
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return {
            "relative_path": _relative(self.root, path),
            "size_bytes": path.stat().st_size,
            "value": _sanitize_json(value, depth=0),
        }

    def _inspect_xml_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve(arguments.get("relative_path"))
        raw_tags = arguments.get("tag_names") or []
        if not isinstance(raw_tags, list) or not all(isinstance(item, str) for item in raw_tags):
            raise ValueError("tag_names must be a list of strings")
        selected = {item.strip() for item in raw_tags if item.strip()}
        tag_counts: Counter[str] = Counter()
        leaf_values: list[dict[str, str]] = []
        root_name: str | None = None
        element_count = 0
        for event, element in ET.iterparse(path, events=("start", "end")):
            name = _local_name(element.tag)
            if event == "start":
                root_name = root_name or name
                continue
            element_count += 1
            tag_counts[name] += 1
            text = (element.text or "").strip()
            if text and (not selected or name in selected) and len(leaf_values) < 150:
                leaf_values.append({"tag": name, "value": _redact_text(text)[:500]})
            element.clear()
        return {
            "relative_path": _relative(self.root, path),
            "root_element": root_name,
            "element_count": element_count,
            "unique_tag_count": len(tag_counts),
            "tag_counts": dict(tag_counts.most_common(200)),
            "leaf_values": leaf_values,
            "leaf_values_truncated": len(leaf_values) >= 150,
        }

    def _inspect_mzml(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve(arguments.get("relative_path"))
        if not path.name.casefold().endswith(".mzml"):
            raise ValueError("inspect_mzml requires an .mzML file")
        return _stream_mzml_summary(self.root, path)

    def _inspect_fasta(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve(arguments.get("relative_path"))
        requested = arguments.get("accessions") or []
        if not isinstance(requested, list) or not all(isinstance(item, str) for item in requested):
            raise ValueError("accessions must be a list of strings")
        return _inspect_fasta_file(self.root, path, requested)

    def _hash_source_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve(arguments.get("relative_path"))
        algorithm = arguments.get("algorithm")
        if algorithm not in {"sha1", "sha256"}:
            raise ValueError("algorithm must be sha1 or sha256")
        digest = hashlib.new(str(algorithm))
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return {
            "relative_path": _relative(self.root, path),
            "algorithm": algorithm,
            "digest": digest.hexdigest(),
            "size_bytes": path.stat().st_size,
        }

    def _validate_table_relation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        left = self._resolve(arguments.get("left_path"))
        right = self._resolve(arguments.get("right_path"))
        left_field = _required_string(arguments, "left_field")
        right_field = _required_string(arguments, "right_field")
        split = bool(arguments.get("split_semicolon"))
        right_values = _table_column_values(right, right_field, split_semicolon=False)
        left_values = _table_column_values(left, left_field, split_semicolon=split)
        return _relation_result(
            left_label=f"{_relative(self.root, left)}:{left_field}",
            right_label=f"{_relative(self.root, right)}:{right_field}",
            left_values=left_values,
            right_values=right_values,
        )

    def _validate_scan_relation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        table = self._resolve(arguments.get("table_path"))
        mzml_path = self._resolve(arguments.get("mzml_path"))
        field = _required_string(arguments, "scan_field")
        raw_values = _table_column_values(
            table,
            field,
            split_semicolon=bool(arguments.get("split_semicolon")),
        )
        table_scans = {str(int(value)) for value in raw_values if _integer_text(value)}
        mzml_scans: set[str] = set()
        with mzml.read(str(mzml_path), decode_binary=False) as reader:
            for spectrum in reader:
                scan = parse_scan(str(spectrum.get("id") or ""))
                if scan is not None:
                    mzml_scans.add(str(scan))
        return _relation_result(
            left_label=f"{_relative(self.root, table)}:{field}",
            right_label=f"{_relative(self.root, mzml_path)}:scan_number",
            left_values=table_scans,
            right_values=mzml_scans,
        )

    def _validate_fasta_relation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        table = self._resolve(arguments.get("table_path"))
        fasta = self._resolve(arguments.get("fasta_path"))
        field = _required_string(arguments, "accession_field")
        table_values = _table_column_values(
            table,
            field,
            split_semicolon=bool(arguments.get("split_semicolon")),
        )
        fasta_ids = {identifier for identifier, _sequence in _iter_fasta(fasta)}
        aliases = set(fasta_ids)
        for identifier in fasta_ids:
            parts = identifier.split("|")
            if len(parts) >= 2 and parts[1]:
                aliases.add(parts[1])
        return _relation_result(
            left_label=f"{_relative(self.root, table)}:{field}",
            right_label=f"{_relative(self.root, fasta)}:identifier",
            left_values=table_values,
            right_values=aliases,
        )

    def _inspect_viewer_capabilities(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        return build_zp_capabilities()


def _inspect_delimited(path: Path, requested: list[str]) -> dict[str, Any]:
    delimiter = "\t" if path.suffix.casefold() in {".tsv", ".txt"} else ","
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        first = stream.readline()
        stream.seek(0)
        if path.suffix.casefold() not in {".tsv", ".txt", ".csv"}:
            delimiter = "\t" if first.count("\t") >= first.count(",") else ","
        reader = csv.DictReader(stream, delimiter=delimiter)
        header = list(reader.fieldnames or [])
        if not header or len(header) != len(set(header)):
            raise ValueError("table header is empty or contains duplicate fields")
        selected = requested or header
        missing = [item for item in selected if item not in header]
        if missing:
            raise ValueError(f"requested columns are missing: {', '.join(missing)}")
        stats = {name: _new_column_stats() for name in selected}
        row_count = 0
        for row in reader:
            if None in row:
                raise ValueError(f"row {row_count + 2} has more fields than the header")
            row_count += 1
            for name in selected:
                _update_column_stats(stats[name], row.get(name))
    return {
        "relative_path": path.name,
        "format": "tsv" if delimiter == "\t" else "csv",
        "header": header,
        "column_count": len(header),
        "row_count": row_count,
        "inspected_columns": {name: _finish_column_stats(value) for name, value in stats.items()},
    }


def _inspect_jsonl(path: Path, requested: list[str]) -> dict[str, Any]:
    header: list[str] = []
    header_set: set[str] = set()
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_no, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL line {line_no} is not an object")
            rows.append(value)
            for key in value:
                name = str(key)
                if name not in header_set:
                    header_set.add(name)
                    header.append(name)
    selected = requested or header
    missing = [item for item in selected if item not in header_set]
    if missing:
        raise ValueError(f"requested fields are missing: {', '.join(missing)}")
    stats = {name: _new_column_stats() for name in selected}
    for row in rows:
        for name in selected:
            _update_column_stats(stats[name], row.get(name))
    return {
        "relative_path": path.name,
        "format": "jsonl",
        "header": header,
        "column_count": len(header),
        "row_count": len(rows),
        "inspected_columns": {name: _finish_column_stats(value) for name, value in stats.items()},
    }


def _new_column_stats() -> dict[str, Any]:
    return {
        "nonempty": 0,
        "empty": 0,
        "nan_literal": 0,
        "numeric": 0,
        "minimum": None,
        "maximum": None,
        "examples": [],
    }


def _update_column_stats(stats: dict[str, Any], raw: Any) -> None:
    text = "" if raw is None else str(raw).strip()
    if not text:
        stats["empty"] += 1
        return
    stats["nonempty"] += 1
    if text.casefold() in {"nan", "+nan", "-nan"}:
        stats["nan_literal"] += 1
    try:
        number = float(text)
    except ValueError:
        number = None
    if number is not None and math.isfinite(number):
        stats["numeric"] += 1
        stats["minimum"] = number if stats["minimum"] is None else min(stats["minimum"], number)
        stats["maximum"] = number if stats["maximum"] is None else max(stats["maximum"], number)
    examples: list[str] = stats["examples"]
    sample = _redact_text(text)[:160]
    if sample not in examples and len(examples) < MAX_DISTINCT_SAMPLES:
        examples.append(sample)


def _finish_column_stats(stats: dict[str, Any]) -> dict[str, Any]:
    return {
        **stats,
        "inferred_type": (
            "numeric"
            if stats["nonempty"] > 0 and stats["numeric"] + stats["nan_literal"] == stats["nonempty"]
            else "string"
        ),
    }


def _stream_mzml_summary(root: Path, path: Path) -> dict[str, Any]:
    ms_levels: Counter[int] = Counter()
    peak_pairs: Counter[int] = Counter()
    charges: Counter[int] = Counter()
    representations: Counter[str] = Counter()
    polarities: Counter[str] = Counter()
    activation_methods: Counter[str] = Counter()
    collision_energies: Counter[str] = Counter()
    scans: list[int] = []
    rt_min: float | None = None
    rt_max: float | None = None
    precursor_count = 0
    sampled: list[dict[str, Any]] = []
    with mzml.read(str(path)) as reader:
        for spectrum in reader:
            level = int(spectrum.get("ms level", 0) or 0)
            ms_levels[level] += 1
            mz_values = np.asarray(spectrum.get("m/z array", []))
            intensity_values = np.asarray(spectrum.get("intensity array", []))
            if mz_values.size != intensity_values.size:
                raise ValueError("mzML spectrum arrays have different lengths")
            peak_pairs[level] += int(mz_values.size)
            scan = parse_scan(str(spectrum.get("id") or ""))
            if scan is not None:
                scans.append(scan)
            rt = rt_seconds(spectrum)
            rt_min = rt if rt_min is None else min(rt_min, rt)
            rt_max = rt if rt_max is None else max(rt_max, rt)
            if spectrum.get("centroid spectrum") is not None:
                representations["centroid"] += 1
            elif spectrum.get("profile spectrum") is not None:
                representations["profile"] += 1
            if spectrum.get("positive scan") is not None:
                polarities["positive"] += 1
            if spectrum.get("negative scan") is not None:
                polarities["negative"] += 1
            precursor = extract_precursor(spectrum)
            if precursor is not None:
                precursor_count += 1
                charge = precursor.get("charge")
                if isinstance(charge, int):
                    charges[charge] += 1
                raw_precursors = spectrum.get("precursorList", {}).get("precursor", [])
                activation = raw_precursors[0].get("activation", {}) if raw_precursors else {}
                for name, value in activation.items():
                    if name == "collision energy":
                        try:
                            collision_energies[f"{float(value):g}"] += 1
                        except (TypeError, ValueError):
                            pass
                    elif value is not None and name not in {"collision energy"}:
                        activation_methods[str(name)] += 1
            if len(sampled) < MAX_SAMPLE_SCANS:
                sampled.append(
                    {
                        "scan_number": scan,
                        "ms_level": level,
                        "rt_seconds": rt,
                        "peak_count": int(mz_values.size),
                        "precursor": precursor,
                    }
                )

    chromatograms: list[dict[str, Any]] = []
    try:
        with mzml.MzML(str(path), use_index=True) as reader:
            for record in reader.iterfind("chromatogram"):
                time_values = np.asarray(record.get("time array", []))
                intensity_values = np.asarray(record.get("intensity array", []))
                chromatogram_type = next(
                    (
                        name
                        for name in ("basepeak chromatogram", "total ion current chromatogram")
                        if record.get(name) is not None
                    ),
                    "unknown",
                )
                chromatograms.append(
                    {
                        "id": str(record.get("id") or ""),
                        "type": chromatogram_type,
                        "point_count": int(min(time_values.size, intensity_values.size)),
                    }
                )
    except Exception as exc:  # noqa: BLE001 - chromatogram absence is reported, not hidden
        chromatograms.append({"type": "inspection_error", "message": str(exc)[:300], "point_count": 0})

    return {
        "relative_path": _relative(root, path),
        "size_bytes": path.stat().st_size,
        "spectrum_count": sum(ms_levels.values()),
        "ms_level_counts": {str(key): value for key, value in sorted(ms_levels.items())},
        "peak_pair_counts": {
            **{f"ms{key}": value for key, value in sorted(peak_pairs.items())},
            "total": sum(peak_pairs.values()),
        },
        "scan_number_range": [min(scans), max(scans)] if scans else None,
        "retention_time_seconds": [rt_min, rt_max],
        "representations": dict(representations),
        "polarities": dict(polarities),
        "precursor_count": precursor_count,
        "precursor_charge_histogram": {str(key): value for key, value in sorted(charges.items())},
        "activation_methods": dict(activation_methods),
        "collision_energies": dict(collision_energies),
        "chromatograms": chromatograms,
        "sampled_scans": sampled,
        "peak_values_returned_to_model": False,
    }


def _inspect_fasta_file(root: Path, path: Path, requested: list[str]) -> dict[str, Any]:
    identifiers: set[str] = set()
    sequence_hashes: set[str] = set()
    lengths: list[int] = []
    alphabet: set[str] = set()
    matched: set[str] = set()
    requested_set = {item.strip() for item in requested if item.strip()}
    for identifier, sequence in _iter_fasta(path):
        identifiers.add(identifier)
        lengths.append(len(sequence))
        alphabet.update(sequence)
        sequence_hashes.add(hashlib.sha256(sequence.encode("ascii", errors="ignore")).hexdigest())
        aliases = {identifier}
        parts = identifier.split("|")
        if len(parts) >= 2:
            aliases.add(parts[1])
        matched.update(requested_set & aliases)
    return {
        "relative_path": _relative(root, path),
        "record_count": len(lengths),
        "unique_identifier_count": len(identifiers),
        "unique_sequence_count": len(sequence_hashes),
        "duplicate_sequence_count": len(lengths) - len(sequence_hashes),
        "total_residues": sum(lengths),
        "length_range": [min(lengths), max(lengths)] if lengths else None,
        "residue_alphabet": "".join(sorted(alphabet)),
        "requested_accession_count": len(requested_set),
        "matched_accessions": sorted(matched),
        "sequences_returned_to_model": False,
    }


def _iter_fasta(path: Path):
    identifier: str | None = None
    chunks: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            text = line.strip()
            if not text:
                continue
            if text.startswith(">"):
                if identifier is not None:
                    yield identifier, "".join(chunks).upper()
                identifier = text[1:].split(None, 1)[0]
                chunks = []
            else:
                chunks.append(text)
    if identifier is not None:
        yield identifier, "".join(chunks).upper()


def _table_column_values(path: Path, field: str, *, split_semicolon: bool) -> set[str]:
    delimiter = "\t" if path.suffix.casefold() in {".tsv", ".txt"} else ","
    result: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=delimiter)
        if field not in (reader.fieldnames or []):
            raise ValueError(f"table field is missing: {field}")
        for row in reader:
            raw = str(row.get(field) or "").strip()
            values = raw.split(";") if split_semicolon else [raw]
            result.update(item.strip() for item in values if item.strip())
    return result


def _relation_result(
    *,
    left_label: str,
    right_label: str,
    left_values: set[str],
    right_values: set[str],
) -> dict[str, Any]:
    missing = sorted(left_values - right_values)
    return {
        "left": left_label,
        "right": right_label,
        "left_distinct_count": len(left_values),
        "right_distinct_count": len(right_values),
        "matched_count": len(left_values & right_values),
        "missing_count": len(missing),
        "missing_examples": missing[:10],
    }


def _sanitize_json(value: Any, *, depth: int) -> Any:
    if depth >= 8:
        return "<depth-limit>"
    if isinstance(value, dict):
        return {str(key): _sanitize_json(item, depth=depth + 1) for key, item in list(value.items())[:300]}
    if isinstance(value, list):
        return [_sanitize_json(item, depth=depth + 1) for item in value[:300]]
    if isinstance(value, str):
        return _redact_text(value)[:1000]
    if value is None or isinstance(value, (bool, int, float)):
        return value if not isinstance(value, float) or math.isfinite(value) else str(value)
    return str(value)[:1000]


def _redact_text(value: str) -> str:
    text = value.strip()
    if _ABSOLUTE_WINDOWS_PATH.match(text) or text.startswith(("/", "\\\\")):
        return f"<redacted-absolute-path>/{Path(text.replace('\\\\', '/')).name}"
    return text


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _required_string(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _integer_text(value: str) -> bool:
    try:
        int(value)
    except ValueError:
        return False
    return True
