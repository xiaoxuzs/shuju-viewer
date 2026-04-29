"""某 cutoff 下的 PrSM 列表与详情 API：读取 universal schema。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.universal_compat import load_prsm_detail, prsm_list_item, prsm_list_select_sql, require_cutoff, require_dataset
from app.ingest.utils import to_float, to_int
from app.schemas import Page, PrsmDetailOut, PrsmListItemOut

router = APIRouter(tags=["prsms"])

SORT_MAP = {
    "prsm_id": "prsm_id",
    "e_value": "e_value",
    "p_value": "p_value",
    "precursor_mono_mass": "precursor_mono_mass",
    "precursor_charge": "precursor_charge",
    "matched_fragment_number": "matched_fragment_number",
    "matched_peak_number": "matched_peak_number",
}


@router.get(
    "/datasets/{slug}/cutoffs/{cutoff}/prsms",
    response_model=Page[PrsmListItemOut],
)
def list_prsms(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    proteoform_id: int | None = Query(None, description="Filter by proteoform.id"),
    protein_id: int | None = Query(None),
    sort: str = Query("e_value"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    session: Session = Depends(get_db),
    slug: str = "",
    cutoff: str = "",
) -> Page[PrsmListItemOut]:
    dataset = require_dataset(session, slug)
    require_cutoff(cutoff)
    params: dict[str, object] = {"dataset_id": dataset["dataset_id"], "cutoff": cutoff}
    where_parts = [
        "im.dataset_id = :dataset_id",
        "jsonb_extract_path_text(im.extra_metadata, 'source_cutoff') = :cutoff",
    ]
    if proteoform_id is not None:
        where_parts.append("im.entity_id = :proteoform_id")
        params["proteoform_id"] = proteoform_id
    if protein_id is not None:
        where_parts.append(
            """
            EXISTS (
                SELECT 1
                FROM protein_relation_mapping prm
                WHERE prm.dataset_id = im.dataset_id
                  AND prm.entity_type = 'PROTEOFORM'
                  AND prm.entity_id = im.entity_id
                  AND prm.protein_id = :protein_id
            )
            """
        )
        params["protein_id"] = protein_id

    base_sql = prsm_list_select_sql(" AND ".join(where_parts))
    count_sql = f"SELECT count(1) FROM ({base_sql}) AS q"
    sort_col = SORT_MAP.get(sort, "e_value")
    base_sql += f" ORDER BY {sort_col} {'ASC' if order == 'asc' else 'DESC'} NULLS LAST"
    base_sql += " OFFSET :offset LIMIT :limit"
    params["offset"] = (page - 1) * page_size
    params["limit"] = page_size

    total = session.scalar(text(count_sql), params) or 0
    rows = session.execute(text(base_sql), params).mappings().all()
    return Page[PrsmListItemOut](
        items=[PrsmListItemOut(**prsm_list_item(dict(r))) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/datasets/{slug}/cutoffs/{cutoff}/prsms/{prsm_id}",
    response_model=PrsmDetailOut,
)
def get_prsm(
    prsm_id: int,
    session: Session = Depends(get_db),
    slug: str = "",
    cutoff: str = "",
) -> PrsmDetailOut:
    """Look up a PrSM by its **business** ``prsm_id`` inside the given cutoff.

    The composite ``(cutoff_id, prsm_id)`` is unique (see
    :class:`app.models.protein.Prsm` ``__table_args__``). Using the business id
    here means the URL shown in the UI (``PrSM #4534``) matches the navigation
    URL (``/prsms/4534``), and it allows links coming from
    ``Protein.best_prsm_id`` / ``Proteoform.best_prsm_id`` (which store the
    business id, not the DB primary key) to resolve correctly.
    """
    dataset = require_dataset(session, slug)
    require_cutoff(cutoff)
    row = session.execute(
        text(
            """
            SELECT
                im.match_id AS id,
                CAST(jsonb_extract_path_text(im.extra_metadata, 'source_prsm_id') AS integer) AS prsm_id,
                CAST(jsonb_extract_path_text(im.extra_metadata, 'source_sequence_id') AS integer) AS sequence_id,
                CAST(jsonb_extract_path_text(im.extra_metadata, 'p_value') AS double precision) AS p_value,
                im.e_value,
                im.q_value AS fdr,
                CAST(jsonb_extract_path_text(im.extra_metadata, 'matched_fragment_number') AS integer) AS matched_fragment_number,
                CAST(jsonb_extract_path_text(im.extra_metadata, 'matched_peak_number') AS integer) AS matched_peak_number,
                im.experimental_mass AS precursor_mono_mass,
                im.precursor_charge,
                im.precursor_mz,
                pf.theoretical_mass AS proteoform_mass,
                jsonb_extract_path_text(im.extra_metadata, 'ms1_scans') AS ms1_scans,
                jsonb_extract_path_text(im.extra_metadata, 'ms2_scans') AS ms2_scans,
                im.entity_id AS db_proteoform_id,
                jsonb_extract_path_text(im.extra_metadata, 'ms1_ids') AS ms1_ids,
                jsonb_extract_path_text(im.extra_metadata, 'ms2_ids') AS ms2_ids,
                im.intensity AS feature_inte,
                im.detail_path AS detail_path
            FROM identification_matches im
            LEFT JOIN proteoforms pf ON pf.proteoform_id = im.entity_id
            WHERE im.dataset_id = :dataset_id
              AND jsonb_extract_path_text(im.extra_metadata, 'source_cutoff') = :cutoff
              AND CAST(jsonb_extract_path_text(im.extra_metadata, 'source_prsm_id') AS integer) = :prsm_id
            LIMIT 1
            """
        ),
        {"dataset_id": dataset["dataset_id"], "cutoff": cutoff, "prsm_id": prsm_id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "prsm not found")
    item = prsm_list_item(dict(row))
    annotated, ms_header, ms_peaks = load_prsm_detail(row["detail_path"])
    if ms_header:
        item["precursor_mono_mass"] = item["precursor_mono_mass"] or to_float(ms_header.get("precursor_mono_mass"))
        item["precursor_charge"] = item["precursor_charge"] or to_int(ms_header.get("precursor_charge"))
        item["precursor_mz"] = item["precursor_mz"] or to_float(ms_header.get("precursor_mz"))
        item["ms1_scans"] = item["ms1_scans"] or _as_text(ms_header.get("ms1_scans"))
        item["ms2_scans"] = item["ms2_scans"] or _as_text(ms_header.get("scans"))
    if annotated:
        item["proteoform_mass"] = item["proteoform_mass"] or to_float(annotated.get("proteoform_mass"))
    spectrum_file_name = ms_header.get("spectrum_file_name") if ms_header else None
    return PrsmDetailOut(
        **item,
        proteoform_id=row["db_proteoform_id"],
        spectrum_file_name=spectrum_file_name,
        ms1_ids=row["ms1_ids"] or (_as_text(ms_header.get("ms1_ids")) if ms_header else None),
        ms2_ids=row["ms2_ids"] or (_as_text(ms_header.get("ids")) if ms_header else None),
        feature_inte=row["feature_inte"] or (to_float(ms_header.get("feature_inte")) if ms_header else None),
        ms_header=ms_header,
        annotated_protein=annotated,
        ms_peaks=ms_peaks,
    )


def _as_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
