"""Resolve protein base sequences for Bottom-Up coverage."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.bu.services.peptide_mapper import normalize_aa
from app.core.config import settings


_UNIPROT_CACHE_SIZE = 256
_FASTA_CACHE_SIZE = 8
_UNIPROT_MIN_INTERVAL_SECONDS = 1.0 / 3.0
_UNIPROT_CACHE: OrderedDict[str, tuple[str | None, dict[str, Any]]] = OrderedDict()
_FASTA_CACHE: OrderedDict[str, dict[str, str] | None] = OrderedDict()
_last_uniprot_request_at = 0.0


def resolve_base_sequence(
    session: Session,
    dataset: dict[str, Any],
    protein: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    """Resolve and persist a protein sequence when possible."""
    metadata = _json_object(protein.get("extra_metadata"))
    existing = normalize_aa(protein.get("base_sequence"))
    if existing:
        metadata.setdefault("sequence_source", metadata.get("sequence_source") or "database")
        metadata.setdefault("sequence_length", len(existing))
        return existing, metadata

    if bool(protein.get("is_decoy")):
        metadata.setdefault("sequence_source", "decoy")
        return None, metadata

    accession = str(protein.get("accession") or "").strip()
    if not accession:
        metadata["sequence_fetch_error"] = "missing_accession"
        return None, metadata

    fasta_sequence = _lookup_dataset_fasta(str(dataset.get("source_root") or ""), accession)
    if fasta_sequence:
        sequence = normalize_aa(fasta_sequence)
        if sequence:
            update_sequence(session, int(dataset["dataset_id"]), int(protein["id"]), sequence, "user_fasta")
            metadata.update({"sequence_source": "user_fasta", "sequence_length": len(sequence)})
            return sequence, metadata

    if not settings.bu_uniprot_enabled:
        metadata.update({"sequence_source": "missing", "sequence_fetch_error": "uniprot_disabled"})
        return None, metadata

    sequence, fetched_metadata = _fetch_uniprot_cached(accession)
    if sequence:
        update_sequence(session, int(dataset["dataset_id"]), int(protein["id"]), sequence, "uniprot", fetched_metadata)
        metadata.update(fetched_metadata)
        metadata.update({"sequence_source": "uniprot", "sequence_length": len(sequence)})
        return sequence, metadata

    metadata.update(fetched_metadata)
    update_sequence_error(session, int(dataset["dataset_id"]), int(protein["id"]), metadata.get("sequence_fetch_error", "missing"))
    return None, metadata


def update_sequence(
    session: Session,
    dataset_id: int,
    protein_id: int,
    sequence: str,
    source: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    patch = dict(metadata or {})
    patch.update({"sequence_source": source, "sequence_length": len(sequence)})
    session.execute(
        text(
            """
            UPDATE proteins
            SET base_sequence = :sequence,
                extra_metadata = extra_metadata || CAST(:metadata AS jsonb)
            WHERE dataset_id = :dataset_id AND protein_id = :protein_id
            """
        ),
        {
            "dataset_id": dataset_id,
            "protein_id": protein_id,
            "sequence": sequence,
            "metadata": json.dumps(patch),
        },
    )
    session.commit()


def update_sequence_error(session: Session, dataset_id: int, protein_id: int, error: str) -> None:
    session.execute(
        text(
            """
            UPDATE proteins
            SET extra_metadata = extra_metadata || CAST(:metadata AS jsonb)
            WHERE dataset_id = :dataset_id AND protein_id = :protein_id
            """
        ),
        {
            "dataset_id": dataset_id,
            "protein_id": protein_id,
            "metadata": json.dumps({"sequence_source": "missing", "sequence_fetch_error": error}),
        },
    )
    session.commit()


def _lookup_dataset_fasta(source_root: str, accession: str) -> str | None:
    if not source_root:
        return None
    index = _load_dataset_fasta(source_root)
    if not index:
        return None
    return index.get(accession.upper())


def _load_dataset_fasta(source_root: str) -> dict[str, str] | None:
    cached = _FASTA_CACHE.get(source_root)
    if source_root in _FASTA_CACHE:
        _FASTA_CACHE.move_to_end(source_root)
        return cached

    root = Path(source_root)
    index: dict[str, str] | None = None
    if root.exists() and root.is_dir():
        fasta_files = [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".fa", ".fasta"}]
        if len(fasta_files) == 1:
            index = _read_fasta(fasta_files[0])

    _FASTA_CACHE[source_root] = index
    _FASTA_CACHE.move_to_end(source_root)
    while len(_FASTA_CACHE) > _FASTA_CACHE_SIZE:
        _FASTA_CACHE.popitem(last=False)
    return index


def _read_fasta(path: Path) -> dict[str, str]:
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
                current_accession = _accession_from_fasta_header(line)
                current_lines = []
            else:
                current_lines.append(line)
        if current_accession and current_lines:
            records[current_accession.upper()] = normalize_aa("".join(current_lines))
    return records


def _accession_from_fasta_header(header: str) -> str:
    token = header[1:].strip().split(None, 1)[0]
    parts = token.split("|")
    if len(parts) >= 2 and parts[0].lower() in {"sp", "tr"}:
        return parts[1]
    return parts[0]


def _fetch_uniprot_cached(accession: str) -> tuple[str | None, dict[str, Any]]:
    key = accession.upper()
    cached = _UNIPROT_CACHE.get(key)
    if cached is not None:
        _UNIPROT_CACHE.move_to_end(key)
        return cached

    sequence, metadata = _fetch_uniprot(accession)
    _UNIPROT_CACHE[key] = (sequence, metadata)
    _UNIPROT_CACHE.move_to_end(key)
    while len(_UNIPROT_CACHE) > _UNIPROT_CACHE_SIZE:
        _UNIPROT_CACHE.popitem(last=False)
    return sequence, metadata


def _fetch_uniprot(accession: str) -> tuple[str | None, dict[str, Any]]:
    errors: list[str] = []
    for _attempt in range(3):
        _rate_limit_uniprot()
        try:
            url = f"https://rest.uniprot.org/uniprotkb/{urllib.parse.quote(accession)}.fasta"
            request = urllib.request.Request(url, headers={"User-Agent": "proteo-viewer/0.1"})
            with urllib.request.urlopen(request, timeout=8) as response:
                body = response.read().decode("utf-8", errors="replace")
            sequence, metadata = _parse_uniprot_fasta(body)
            if sequence:
                return sequence, metadata
            errors.append("empty_fasta")
        except urllib.error.HTTPError as exc:
            errors.append(str(exc.code))
            if exc.code == 404:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            errors.append(type(exc).__name__)
    error = errors[-1] if errors else "uniprot_unavailable"
    return None, {"sequence_source": "missing", "sequence_fetch_error": error}


def _rate_limit_uniprot() -> None:
    global _last_uniprot_request_at
    now = time.monotonic()
    elapsed = now - _last_uniprot_request_at
    if elapsed < _UNIPROT_MIN_INTERVAL_SECONDS:
        time.sleep(_UNIPROT_MIN_INTERVAL_SECONDS - elapsed)
    _last_uniprot_request_at = time.monotonic()


def _parse_uniprot_fasta(body: str) -> tuple[str | None, dict[str, Any]]:
    header: str | None = None
    lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None:
                break
            header = line
            continue
        if header is not None:
            lines.append(line)
    sequence = normalize_aa("".join(lines))
    metadata: dict[str, Any] = {}
    if header:
        metadata["protein_names"] = _protein_name_from_uniprot_header(header)
    return (sequence or None), metadata


def _protein_name_from_uniprot_header(header: str) -> str | None:
    marker = " "
    if marker not in header:
        return None
    title = header.split(marker, 1)[1].strip()
    for stop_marker in (" OS=", " OX=", " GN=", " PE=", " SV="):
        if stop_marker in title:
            title = title.split(stop_marker, 1)[0].strip()
    return title or None


def _json_object(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}
