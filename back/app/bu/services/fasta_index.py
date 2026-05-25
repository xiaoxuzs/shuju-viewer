"""Shared FASTA discovery and indexing for Bottom-Up protein coverage."""

from __future__ import annotations

from pathlib import Path

from app.bu.services.peptide_mapper import normalize_aa

FASTA_SUFFIXES = {".fa", ".fasta"}


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


def load_fasta_index(path: Path) -> dict[str, str]:
    """Load ``accession.upper() -> normalized sequence`` from a FASTA file."""
    records: dict[str, str] = {}
    current_accession: str | None = None
    current_lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if current_accession and current_lines:
                    records[current_accession.upper()] = normalize_aa("".join(current_lines))
                current_accession = accession_from_fasta_header(line)
                current_lines = []
            else:
                current_lines.append(line)
        if current_accession and current_lines:
            records[current_accession.upper()] = normalize_aa("".join(current_lines))
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
