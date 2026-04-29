"""Compatibility helpers for reading the universal schema with legacy API shapes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.js_parser import load_js_object


VALID_CUTOFFS = {"prsm", "proteoform"}


def require_dataset(session: Session, slug: str) -> dict[str, Any]:
    row = session.execute(
        text(
            """
            SELECT
                dataset_id,
                dataset_name,
                slug,
                description,
                source_root,
                created_at
            FROM datasets
            WHERE slug = :slug
            """
        ),
        {"slug": slug},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dataset not found: {slug}")
    return dict(row)


def require_cutoff(cutoff: str) -> str:
    if cutoff not in VALID_CUTOFFS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"cutoff not found: {cutoff}")
    return cutoff


def cutoff_id(cutoff: str) -> int:
    return 1 if cutoff == "prsm" else 2


def cutoff_label(cutoff: str) -> str:
    return "TopPIC PrSM cutoff" if cutoff == "prsm" else "TopPIC Proteoform cutoff"


def source_cutoff_filter_sql() -> str:
    return "jsonb_extract_path_text(extra_metadata, 'source_cutoff') = :cutoff"


def source_prsm_id_sql(table_alias: str = "im.extra_metadata") -> str:
    return f"CAST(jsonb_extract_path_text({table_alias}, 'source_prsm_id') AS integer)"


def source_sequence_id_sql(table_alias: str = "im.extra_metadata") -> str:
    return f"CAST(jsonb_extract_path_text({table_alias}, 'source_sequence_id') AS integer)"


def source_proteoform_id_sql(table_alias: str = "im.extra_metadata") -> str:
    return f"CAST(jsonb_extract_path_text({table_alias}, 'source_proteoform_id') AS integer)"


def json_text(field: str, key: str) -> str:
    return f"jsonb_extract_path_text({field}, '{key}')"


def prsm_list_select_sql(where_sql: str = "") -> str:
    where_clause = f"WHERE {where_sql}" if where_sql else ""
    return f"""
        SELECT
            im.match_id AS id,
            {source_prsm_id_sql()} AS prsm_id,
            {source_sequence_id_sql()} AS sequence_id,
            CAST({json_text('im.extra_metadata', 'p_value')} AS double precision) AS p_value,
            im.e_value,
            im.q_value AS fdr,
            CAST({json_text('im.extra_metadata', 'matched_fragment_number')} AS integer) AS matched_fragment_number,
            CAST({json_text('im.extra_metadata', 'matched_peak_number')} AS integer) AS matched_peak_number,
            im.experimental_mass AS precursor_mono_mass,
            im.precursor_charge,
            im.precursor_mz,
            pf.theoretical_mass AS proteoform_mass,
            {json_text('im.extra_metadata', 'ms1_scans')} AS ms1_scans,
            {json_text('im.extra_metadata', 'ms2_scans')} AS ms2_scans
        FROM identification_matches im
        LEFT JOIN proteoforms pf ON pf.proteoform_id = im.entity_id
        {where_clause}
    """


def prsm_list_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "prsm_id": row["prsm_id"],
        "sequence_id": row["sequence_id"],
        "p_value": row["p_value"],
        "e_value": row["e_value"],
        "fdr": row["fdr"],
        "matched_fragment_number": row["matched_fragment_number"],
        "matched_peak_number": row["matched_peak_number"],
        "precursor_mono_mass": row["precursor_mono_mass"],
        "precursor_charge": row["precursor_charge"],
        "precursor_mz": row["precursor_mz"],
        "proteoform_mass": row["proteoform_mass"],
        "ms1_scans": row["ms1_scans"],
        "ms2_scans": row["ms2_scans"],
    }


def load_prsm_detail(detail_path: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    if not detail_path:
        return None, None, None
    path = Path(detail_path)
    if not path.exists():
        return None, None, None
    doc = load_js_object(path)
    prsm_root = doc.get("prsm") or doc
    annotated = prsm_root.get("annotated_protein") or None
    ms = prsm_root.get("ms", {}) or {}
    header = ms.get("ms_header") or None
    peaks = ms.get("peaks") or None
    return annotated, header, peaks
