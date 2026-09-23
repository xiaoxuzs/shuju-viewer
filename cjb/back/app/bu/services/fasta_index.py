"""Shared FASTA discovery and indexing for Bottom-Up protein coverage."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.bu.services.peptide_mapper import normalize_aa
from app.core.config import settings

FASTA_SUFFIXES = {".fa", ".faa", ".fasta"}
DEFAULT_FASTA_NAME = "human.fasta"


@dataclass(frozen=True)
class FastaRecord:
    accession: str
    sequence: str
    gene_name: str | None = None
    description: str | None = None


def find_fasta_files(source_root: Path) -> list[Path]:
    """Return all FASTA files under ``source_root`` in deterministic order."""
    if not source_root.exists() or not source_root.is_dir():
        return []
    return sorted(
        (path for path in source_root.rglob("*") if path.is_file() and path.suffix.lower() in FASTA_SUFFIXES),
        key=lambda path: str(path).lower(),
    )


def discover_unique_fasta(source_root: Path) -> Path | None:
    """Return the unique FASTA file under ``source_root``; otherwise ``None``."""
    fasta_files = find_fasta_files(source_root)
    return fasta_files[0] if len(fasta_files) == 1 else None


def discover_default_fasta() -> Path | None:
    """Return the configured/project default FASTA when it exists."""
    candidates: list[Path] = []
    if settings.bu_default_fasta_path is not None:
        candidates.append(Path(settings.bu_default_fasta_path))
    candidates.extend(
        [
            settings.resolved_data_root / DEFAULT_FASTA_NAME,
            settings.resolved_data_root.parent / DEFAULT_FASTA_NAME,
        ]
    )
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file() and resolved.suffix.lower() in FASTA_SUFFIXES:
            return resolved
    return None


def load_fasta_index(path: Path) -> dict[str, str]:
    """Load ``accession.upper() -> normalized sequence`` from a FASTA file."""
    return {accession: record.sequence for accession, record in load_fasta_record_index(path).items()}


def lookup_fasta_record(index: dict[str, FastaRecord], accession: str) -> FastaRecord | None:
    for candidate in candidate_accessions(accession):
        record = index.get(candidate)
        if record is not None:
            return record
    return None


def candidate_accessions(accession: str) -> list[str]:
    candidates: list[str] = []
    for token in re.split(r"[;,\s]+", accession):
        cleaned = token.strip()
        if not cleaned:
            continue
        parts = cleaned.split("|")
        if len(parts) >= 2 and parts[0].lower() in {"sp", "tr"}:
            cleaned = parts[1]
        key = cleaned.upper()
        if key not in candidates:
            candidates.append(key)
    return candidates


def load_fasta_record_index(path: Path) -> dict[str, FastaRecord]:
    """Load ``accession.upper() -> FASTA record`` from a FASTA file."""
    records: dict[str, FastaRecord] = {}
    current_header: str | None = None
    current_lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                _store_record(records, current_header, current_lines)
                current_header = line
                current_lines = []
            else:
                current_lines.append(line)
        _store_record(records, current_header, current_lines)
    return records


def accession_from_fasta_header(header: str) -> str:
    content = header[1:].strip() if header.startswith(">") else header.strip()
    if not content:
        return ""
    token = content.split(None, 1)[0]
    parts = token.split("|")
    if len(parts) >= 2 and parts[0].lower() in {"sp", "tr"}:
        return parts[1]
    return parts[0]


def description_from_fasta_header(header: str) -> str | None:
    content = header[1:].strip() if header.startswith(">") else header.strip()
    if " " not in content:
        return None
    title = content.split(" ", 1)[1].strip()
    for stop_marker in (" OS=", " OX=", " GN=", " PE=", " SV="):
        if stop_marker in title:
            title = title.split(stop_marker, 1)[0].strip()
    return title or None


def gene_name_from_fasta_header(header: str) -> str | None:
    marker = " GN="
    if marker not in header:
        return None
    value = header.split(marker, 1)[1].strip()
    for stop_marker in (" OS=", " OX=", " PE=", " SV="):
        if stop_marker in value:
            value = value.split(stop_marker, 1)[0].strip()
    return value.split()[0].strip() or None


def _store_record(records: dict[str, FastaRecord], header: str | None, lines: list[str]) -> None:
    if not header or not lines:
        return
    accession = accession_from_fasta_header(header)
    sequence = normalize_aa("".join(lines))
    if not accession or not sequence:
        return
    records[accession.upper()] = FastaRecord(
        accession=accession,
        sequence=sequence,
        gene_name=gene_name_from_fasta_header(header),
        description=description_from_fasta_header(header),
    )
