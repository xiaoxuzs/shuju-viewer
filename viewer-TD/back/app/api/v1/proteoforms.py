"""Proteoform list and detail endpoints for a given cutoff; reads the universal schema."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.universal_compat import prsm_list_item, prsm_list_select_sql, require_cutoff, require_dataset
from app.schemas import Page, PrsmListItemOut, ProteoformDetailOut, ProteoformListItemOut

router = APIRouter(tags=["proteoforms"])

SORT_MAP = {
    "proteoform_id": "proteoform_id",
    "prsm_number": "prsm_number",
    "best_prsm_e_value": "best_prsm_e_value",
    "proteoform_mass": "proteoform_mass",
}


@router.get(
    "/datasets/{slug}/cutoffs/{cutoff}/proteoforms",
    response_model=Page[ProteoformListItemOut],
)
def list_proteoforms(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    protein_id: int | None = Query(None),
    sort: str = Query("proteoform_id"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    session: Session = Depends(get_db),
    slug: str = "",
    cutoff: str = "",
) -> Page[ProteoformListItemOut]:
    """List proteoforms with pagination; if ``protein_id`` is set, restrict to forms under that protein (``proteins.protein_id``).

    Cutoff semantics: include only proteoforms that have ``identification_matches`` for the current cutoff ---
    the reliable membership rule, since universal ``proteoforms`` rows are shared across cutoffs.
    """
    dataset = require_dataset(session, slug)
    require_cutoff(cutoff)
    params: dict[str, object] = {"dataset_id": dataset["dataset_id"], "cutoff": cutoff}
    join_sql = ""
    where_sql = (
        "pf.dataset_id = :dataset_id"
        " AND EXISTS ("
        "   SELECT 1 FROM identification_matches im"
        "   WHERE im.dataset_id = pf.dataset_id"
        "     AND im.entity_type = 'PROTEOFORM'"
        "     AND im.entity_id = pf.proteoform_id"
        "     AND jsonb_extract_path_text(im.extra_metadata, 'source_cutoff') = :cutoff"
        " )"
    )
    if protein_id is not None:
        join_sql = """
            JOIN protein_relation_mapping prm
              ON prm.entity_id = pf.proteoform_id
             AND prm.entity_type = 'PROTEOFORM'
             AND prm.dataset_id = pf.dataset_id
        """
        where_sql += " AND prm.protein_id = :protein_id"
        params["protein_id"] = protein_id

    base_sql = f"""
        SELECT
            pf.proteoform_id AS id,
            CAST(jsonb_extract_path_text(pf.extra_metadata, 'source_proteoform_id') AS integer) AS proteoform_id,
            CAST(jsonb_extract_path_text(pf.extra_metadata, 'source_sequence_id') AS integer) AS sequence_id,
            COALESCE(jsonb_extract_path_text(pf.extra_metadata, 'sequence_name'), '') AS sequence_name,
            pf.theoretical_mass AS proteoform_mass,
            COALESCE(CAST(jsonb_extract_path_text(pf.extra_metadata, 'prsm_number') AS integer), 0) AS prsm_number,
            CAST(jsonb_extract_path_text(pf.extra_metadata, 'best_prsm_id') AS integer) AS best_prsm_id,
            CAST(jsonb_extract_path_text(pf.extra_metadata, 'best_prsm_e_value') AS double precision) AS best_prsm_e_value,
            NULL::integer AS n_acetylation,
            NULL::integer AS unexpected_shift_number
        FROM proteoforms pf
        {join_sql}
        WHERE {where_sql}
    """
    count_sql = f"SELECT count(1) FROM ({base_sql}) AS q"
    sort_col = SORT_MAP.get(sort, "proteoform_id")
    base_sql += f" ORDER BY {sort_col} {'ASC' if order == 'asc' else 'DESC'} NULLS LAST"
    base_sql += " OFFSET :offset LIMIT :limit"
    params["offset"] = (page - 1) * page_size
    params["limit"] = page_size

    total = session.scalar(text(count_sql), params) or 0
    rows = session.execute(text(base_sql), params).mappings().all()
    return Page[ProteoformListItemOut](
        items=[ProteoformListItemOut(**dict(r)) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/datasets/{slug}/cutoffs/{cutoff}/proteoforms/{proteoform_id}",
    response_model=ProteoformDetailOut,
)
def get_proteoform(
    proteoform_id: int,
    session: Session = Depends(get_db),
    slug: str = "",
    cutoff: str = "",
) -> ProteoformDetailOut:
    """Detail path ``proteoform_id`` is ``proteoforms.proteoform_id`` (PK), not TopPIC's business proteoform id.

    Cutoff semantics: the proteoform row is shared across cutoffs, but with ``cutoff=X`` in the URL there must be
    at least one ``identification_matches`` row for cutoff X or we return 404, so we never show forms that appear only under another cutoff.
    """
    dataset = require_dataset(session, slug)
    require_cutoff(cutoff)
    pf = session.execute(
        text(
            """
            SELECT
                pf.proteoform_id AS id,
                prm.protein_id AS protein_id,
                CAST(jsonb_extract_path_text(pf.extra_metadata, 'source_proteoform_id') AS integer) AS proteoform_id,
                CAST(jsonb_extract_path_text(pf.extra_metadata, 'source_sequence_id') AS integer) AS sequence_id,
                COALESCE(jsonb_extract_path_text(pf.extra_metadata, 'sequence_name'), '') AS sequence_name,
                pf.theoretical_mass AS proteoform_mass,
                COALESCE(CAST(jsonb_extract_path_text(pf.extra_metadata, 'prsm_number') AS integer), 0) AS prsm_number,
                CAST(jsonb_extract_path_text(pf.extra_metadata, 'best_prsm_id') AS integer) AS best_prsm_id,
                CAST(jsonb_extract_path_text(pf.extra_metadata, 'best_prsm_e_value') AS double precision) AS best_prsm_e_value,
                NULL::integer AS n_acetylation,
                NULL::integer AS unexpected_shift_number
            FROM proteoforms pf
            LEFT JOIN protein_relation_mapping prm
              ON prm.entity_id = pf.proteoform_id
             AND prm.entity_type = 'PROTEOFORM'
             AND prm.dataset_id = pf.dataset_id
            WHERE pf.dataset_id = :dataset_id AND pf.proteoform_id = :proteoform_id
              AND EXISTS (
                SELECT 1 FROM identification_matches im
                WHERE im.dataset_id = pf.dataset_id
                  AND im.entity_type = 'PROTEOFORM'
                  AND im.entity_id = pf.proteoform_id
                  AND jsonb_extract_path_text(im.extra_metadata, 'source_cutoff') = :cutoff
              )
            LIMIT 1
            """
        ),
        {"dataset_id": dataset["dataset_id"], "proteoform_id": proteoform_id, "cutoff": cutoff},
    ).mappings().one_or_none()
    if pf is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proteoform not found")

    prsms = session.execute(
        text(
            prsm_list_select_sql(
                """
                im.dataset_id = :dataset_id
                AND im.entity_id = :proteoform_id
                AND jsonb_extract_path_text(im.extra_metadata, 'source_cutoff') = :cutoff
                """
            )
            + " ORDER BY im.e_value ASC NULLS LAST"
        ),
        {"dataset_id": dataset["dataset_id"], "proteoform_id": proteoform_id, "cutoff": cutoff},
    ).mappings().all()
    return ProteoformDetailOut(
        **dict(pf),
        prsms=[PrsmListItemOut(**prsm_list_item(dict(p))) for p in prsms],
    )
