"""Read DIA-NN protein description TSV files."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProteinDescription:
    protein_name: str | None = None
    gene: str | None = None
    description: str | None = None
    sequence: str | None = None


def read_protein_descriptions(path: Path | None) -> dict[str, ProteinDescription]:
    """Return accession -> protein description metadata."""
    if path is None or not path.is_file():
        return {}
    out: dict[str, ProteinDescription] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            accession = (row.get("Protein.Id") or "").strip()
            if not accession:
                continue
            out[accession] = ProteinDescription(
                protein_name=(row.get("Protein.Name") or "").strip() or None,
                gene=(row.get("Gene") or "").strip() or None,
                description=(row.get("Description") or "").strip() or None,
                sequence=(row.get("Sequence") or "").strip() or None,
            )
    return out
