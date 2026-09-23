"""Read DIA-NN stats TSV files into JSON-friendly metadata."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def _coerce(value: str) -> Any:
    text = value.strip()
    if text == "":
        return None
    try:
        if any(ch in text for ch in (".", "e", "E")):
            return float(text)
        return int(text)
    except ValueError:
        return text


def read_stats_tsv(path: Path | None) -> list[dict[str, Any]]:
    """Return rows from ``all_report.stats.tsv`` or an empty list."""
    if path is None or not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        return [{k: _coerce(v) for k, v in row.items()} for row in reader]
