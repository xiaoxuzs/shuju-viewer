"""DIA-NN parquet row mapping for the universal schema."""

from __future__ import annotations

import math
from typing import Any

PROTON_MASS = 1.007276466812
Q_VALUE_CUTOFF = 0.01


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def as_bool_decoy(value: Any) -> bool:
    return bool(as_int(value) or 0)


def split_protein_group(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def theoretical_mass_from_precursor(precursor_mz: Any, charge: Any) -> float | None:
    mz = as_float(precursor_mz)
    z = as_int(charge)
    if mz is None or z is None or z <= 0:
        return None
    return mz * z - PROTON_MASS * z


def should_import_match(row: dict[str, Any], *, q_value_cutoff: float = Q_VALUE_CUTOFF) -> bool:
    q_value = as_float(row.get("Q.Value"))
    if q_value is None or q_value >= q_value_cutoff:
        return False
    return not as_bool_decoy(row.get("Decoy"))


def match_extra_metadata(row: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "precursor_id": "Precursor.Id",
        "rt_start": "RT.Start",
        "rt_stop": "RT.Stop",
        "ms2_scan": "MS2.Scan",
        "lib_qvalue": "Lib.Q.Value",
        "mass_evidence": "Mass.Evidence",
        "protein_group": "Protein.Group",
        "genes": "Genes",
        "pg_q_value": "PG.Q.Value",
        "pg_max_lfq": "PG.MaxLFQ",
        "im": "IM",
    }
    out: dict[str, Any] = {}
    for dst, src in keys.items():
        if src not in row:
            continue
        value = row.get(src)
        if value == "":
            value = None
        out[dst] = value
    return out


def peptide_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {"modified_sequence": row.get("Modified.Sequence")}


def protein_metadata(row: dict[str, Any], *, accession: str) -> dict[str, Any]:
    return {
        "protein_group": row.get("Protein.Group"),
        "protein_ids": row.get("Protein.Ids"),
        "protein_names": row.get("Protein.Names"),
        "genes": row.get("Genes"),
        "pg_max_lfq": as_float(row.get("PG.MaxLFQ")),
        "pg_q_value": as_float(row.get("PG.Q.Value")),
        "accession": accession,
    }
