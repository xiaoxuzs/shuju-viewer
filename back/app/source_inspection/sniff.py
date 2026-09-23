"""Small-prefix file classification; never reads a whole large file to sniff it."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .budget import BudgetTracker, BudgetedReader, InspectionBudgetExceeded
from .contracts import InspectionLimits, ObservationArtifact, SniffResult
from .observation import InspectionOutcome, finalize_observation
from .paths import CasePathResolver


SNIFFER_ID = "source-file-sniffer"
SNIFFER_VERSION = "1.0.0"

_FASTA_EXTENSIONS = {".fa", ".faa", ".fas", ".fasta", ".fna"}


def sniff_file(
    case_root: str | Path,
    relative_path: str,
    *,
    limits: InspectionLimits | None = None,
) -> ObservationArtifact:
    resolver = CasePathResolver(case_root)
    path = resolver.resolve_file(relative_path)
    relative = resolver.relative(path)
    tracker = BudgetTracker(limits or InspectionLimits())
    try:
        result, whole_content_hash, sampled_only = sniff_resolved(path, relative, tracker)
    except InspectionBudgetExceeded:
        return finalize_observation(
            path=path,
            relative_path=relative,
            detected_format="unknown",
            inspector_id=SNIFFER_ID,
            inspector_version=SNIFFER_VERSION,
            tracker=tracker,
            outcome=InspectionOutcome(
                status="PARTIAL",
                facts={"file_content_returned": False},
                warnings=["The inspection budget was exhausted before file classification completed."],
                truncation_reasons=["sniff_incomplete"],
            ),
        )
    outcome = InspectionOutcome(
        status="COMPLETE",
        facts={
            "sniff": result.model_dump(mode="json"),
            "sniffer_version": SNIFFER_VERSION,
            "file_content_returned": False,
        },
        truncation_reasons=["content_sampled_by_design"] if sampled_only else [],
        source_content_sha256=whole_content_hash,
    )
    return finalize_observation(
        path=path,
        relative_path=relative,
        detected_format=result.detected_format,
        inspector_id=SNIFFER_ID,
        inspector_version=SNIFFER_VERSION,
        tracker=tracker,
        outcome=outcome,
    )


def sniff_resolved(
    path: Path,
    relative_path: str,
    tracker: BudgetTracker,
) -> tuple[SniffResult, str | None, bool]:
    size = path.stat().st_size
    reserve_tail = 4 if size > tracker.limits.sniff_bytes and path.suffix.casefold() == ".parquet" else 0
    prefix_limit = min(size, tracker.limits.sniff_bytes - reserve_tail)
    with path.open("rb") as raw:
        stream = BudgetedReader(raw, tracker, file_size=size)
        prefix = stream.read(prefix_limit)
        tail = b""
        if reserve_tail and tracker.remaining_bytes >= reserve_tail:
            stream.seek(max(0, size - reserve_tail))
            tail = stream.read(reserve_tail)
    sampled_only = len(prefix) < size
    whole_content_hash = hashlib.sha256(prefix).hexdigest() if not sampled_only else None
    return _classify(relative_path, prefix, tail), whole_content_hash, sampled_only


def _classify(relative_path: str, prefix: bytes, tail: bytes) -> SniffResult:
    extension = Path(relative_path).suffix.casefold()
    magic: list[str] = []
    binary_format: tuple[str, str] | None = None
    if prefix.startswith(b"PAR1") and (not tail or tail == b"PAR1"):
        magic.append("parquet:PAR1")
        binary_format = ("parquet", "application/vnd.apache.parquet")
    elif prefix.startswith(b"SQLite format 3\x00"):
        magic.append("sqlite-header")
        binary_format = ("sqlite", "application/vnd.sqlite3")
    elif prefix.startswith(b"PK\x03\x04"):
        magic.append("zip-header")
        binary_format = ("zip", "application/zip")
    elif prefix.startswith(b"\x1f\x8b"):
        magic.append("gzip-header")
        binary_format = ("gzip", "application/gzip")
    elif prefix.startswith(b"%PDF-"):
        magic.append("pdf-header")
        binary_format = ("pdf", "application/pdf")
    elif prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        magic.append("png-header")
        binary_format = ("png", "image/png")
    elif prefix.startswith(b"\xff\xd8\xff"):
        magic.append("jpeg-header")
        binary_format = ("jpeg", "image/jpeg")

    if binary_format is not None:
        return SniffResult(
            relative_path=relative_path,
            extension=extension,
            detected_format=binary_format[0],
            media_type=binary_format[1],
            encoding=None,
            is_binary=True,
            confidence="high",
            magic_matches=magic,
        )

    encoding, decoded, is_binary = _decode_prefix(prefix)
    if is_binary:
        detected = "viewer_zp" if extension == ".zp" else "binary"
        media_type = "application/x-viewer-zp" if extension == ".zp" else "application/octet-stream"
        return SniffResult(
            relative_path=relative_path,
            extension=extension,
            detected_format=detected,
            media_type=media_type,
            encoding=None,
            is_binary=True,
            confidence="medium" if extension == ".zp" else "low",
            magic_matches=magic,
        )

    stripped = decoded.lstrip("\ufeff \t\r\n")
    lowered = stripped[:2048].casefold()
    if "<mzml" in lowered or "<indexedmzml" in lowered:
        detected, media_type, confidence = "mzml", "application/mzml+xml", "high"
        magic.append("xml-root:mzML")
    elif stripped.startswith("<"):
        detected, media_type, confidence = "xml", "application/xml", "high" if "<?xml" in lowered else "medium"
        magic.append("xml-leading-tag")
    elif extension in _FASTA_EXTENSIONS or stripped.startswith(">"):
        detected, media_type, confidence = "fasta", "text/x-fasta", "high" if stripped.startswith(">") else "medium"
        if stripped.startswith(">"):
            magic.append("fasta-header")
    elif extension in {".jsonl", ".ndjson"}:
        detected, media_type, confidence = "jsonl", "application/x-ndjson", "medium"
    elif extension not in {".json"} and _looks_like_json_lines(stripped):
        detected, media_type, confidence = "jsonl", "application/x-ndjson", "medium"
        magic.append("multiple-json-object-lines")
    elif extension == ".json" or stripped.startswith(("{", "[")):
        detected, media_type, confidence = "json", "application/json", "medium"
        if stripped.startswith(("{", "[")):
            magic.append("json-leading-token")
    elif extension == ".csv":
        detected, media_type, confidence = "csv", "text/csv", "medium"
    elif extension == ".tsv":
        detected, media_type, confidence = "tsv", "text/tab-separated-values", "medium"
    elif extension == ".txt":
        delimiter = _consistent_delimiter(stripped)
        if delimiter is not None:
            detected = "tsv" if delimiter == "\t" else "csv"
            media_type = "text/tab-separated-values" if detected == "tsv" else "text/csv"
            confidence = "medium"
            magic.append(f"delimiter:{'tab' if detected == 'tsv' else 'comma'}")
        else:
            detected, media_type, confidence = "delimited_text", "text/plain", "medium"
    else:
        delimiter = _consistent_delimiter(stripped)
        if delimiter is not None:
            detected = "tsv" if delimiter == "\t" else "csv"
            media_type = "text/tab-separated-values" if detected == "tsv" else "text/csv"
            confidence = "low"
            magic.append(f"delimiter:{'tab' if detected == 'tsv' else 'comma'}")
        else:
            detected, media_type, confidence = "unknown_text", "text/plain", "low"
    return SniffResult(
        relative_path=relative_path,
        extension=extension,
        detected_format=detected,
        media_type=media_type,
        encoding=encoding,
        is_binary=False,
        confidence=confidence,
        magic_matches=magic,
    )


def _decode_prefix(prefix: bytes) -> tuple[str | None, str, bool]:
    if prefix.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", prefix.decode("utf-8-sig", errors="replace"), False
    if prefix.startswith(b"\xff\xfe"):
        return "utf-16", prefix.decode("utf-16", errors="replace"), False
    if prefix.startswith(b"\xfe\xff"):
        return "utf-16", prefix.decode("utf-16", errors="replace"), False
    try:
        decoded = prefix.decode("utf-8")
    except UnicodeDecodeError:
        for trim in range(1, min(3, len(prefix)) + 1):
            try:
                decoded = prefix[:-trim].decode("utf-8")
            except UnicodeDecodeError:
                continue
            control_count = sum(ord(char) < 32 and char not in "\t\r\n" for char in decoded)
            if b"\x00" in prefix or (decoded and control_count / len(decoded) > 0.02):
                return None, "", True
            return "utf-8", decoded, False
        if b"\x00" in prefix:
            return None, "", True
        return "unknown-8bit", prefix.decode("latin-1"), False
    control_count = sum(ord(char) < 32 and char not in "\t\r\n" for char in decoded)
    if b"\x00" in prefix or (decoded and control_count / len(decoded) > 0.02):
        return None, "", True
    return "utf-8", decoded, False


def _looks_like_json_lines(value: str) -> bool:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    try:
        return all(isinstance(json.loads(line), dict) for line in lines[:2])
    except (ValueError, RecursionError):
        return False


def _consistent_delimiter(value: str) -> str | None:
    lines = [line for line in value.splitlines() if line.strip()][:5]
    if len(lines) < 2:
        return None
    candidates = []
    for delimiter in ("\t", ","):
        counts = [line.count(delimiter) for line in lines]
        if counts[0] > 0 and len(set(counts)) == 1:
            candidates.append((counts[0], delimiter))
    if not candidates:
        return None
    return max(candidates)[1]
