"""某 cutoff 下的蛋白质列表与详情 API：读取 universal schema。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.universal_compat import require_cutoff, require_dataset
from app.schemas import Page, ProteinDetailOut, ProteinListItemOut, ProteoformListItemOut

router = APIRouter(tags=["proteins"])

SORT_MAP = {
    "sequence_id": "sequence_id",
    "sequence_name": "sequence_name",
    "compatible_proteoform_number": "compatible_proteoform_number",
    "prsm_number": "prsm_number",
    "best_prsm_e_value": "best_prsm_e_value",
}


@router.get(
    "/datasets/{slug}/cutoffs/{cutoff}/proteins",
    response_model=Page[ProteinListItemOut],
)
def list_proteins(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str | None = Query(None, description="Search sequence_name / description."),
    sort: str = Query("sequence_id"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    session: Session = Depends(get_db),
    slug: str = "",
    cutoff: str = "",
) -> Page[ProteinListItemOut]:
    """分页列出蛋白质；可选名称/描述模糊搜索。`total` 为过滤后总行数。"""
    dataset = require_dataset(session, slug)
    require_cutoff(cutoff)
    base_sql = """
        SELECT
            p.protein_id AS id,
            CAST(jsonb_extract_path_text(p.extra_metadata, 'source_sequence_id') AS integer) AS sequence_id,
            COALESCE(jsonb_extract_path_text(p.extra_metadata, 'source_sequence_name'), p.accession) AS sequence_name,
            p.description AS sequence_description,
            COALESCE(CAST(jsonb_extract_path_text(p.extra_metadata, 'compatible_proteoform_number') AS integer), 0) AS compatible_proteoform_number,
            COALESCE(CAST(jsonb_extract_path_text(p.extra_metadata, 'prsm_number') AS integer), 0) AS prsm_number,
            CAST(jsonb_extract_path_text(p.extra_metadata, 'best_prsm_id') AS integer) AS best_prsm_id,
            CAST(jsonb_extract_path_text(p.extra_metadata, 'best_prsm_e_value') AS double precision) AS best_prsm_e_value
        FROM proteins p
        WHERE p.dataset_id = :dataset_id
    """
    params: dict[str, object] = {"dataset_id": dataset["dataset_id"]}
    if search:
        base_sql += """
            AND (
                COALESCE(jsonb_extract_path_text(p.extra_metadata, 'source_sequence_name'), p.accession) ILIKE :search
                OR p.description ILIKE :search
            )
        """
        params["search"] = f"%{search}%"

    count_sql = f"SELECT count(1) FROM ({base_sql}) AS q"
    sort_col = SORT_MAP.get(sort, "sequence_id")
    base_sql += f" ORDER BY {sort_col} {'ASC' if order == 'asc' else 'DESC'} NULLS LAST"
    base_sql += " OFFSET :offset LIMIT :limit"
    params["offset"] = (page - 1) * page_size
    params["limit"] = page_size

    total = session.scalar(text(count_sql), params) or 0
    rows = session.execute(text(base_sql), params).mappings().all()
    return Page[ProteinListItemOut](
        items=[ProteinListItemOut(**dict(r)) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/datasets/{slug}/cutoffs/{cutoff}/proteins/{protein_id}",
    response_model=ProteinDetailOut,
)
def get_protein(
    protein_id: int,
    session: Session = Depends(get_db),
    slug: str = "",
    cutoff: str = "",
) -> ProteinDetailOut:
    """单条蛋白质详情；路径中的 protein_id 为表 ``proteins.id``（主键）。"""
    dataset = require_dataset(session, slug)
    require_cutoff(cutoff)
    protein = session.execute(
        text(
            """
            SELECT
                p.protein_id AS id,
                CAST(jsonb_extract_path_text(p.extra_metadata, 'source_sequence_id') AS integer) AS sequence_id,
                COALESCE(jsonb_extract_path_text(p.extra_metadata, 'source_sequence_name'), p.accession) AS sequence_name,
                p.description AS sequence_description,
                COALESCE(CAST(jsonb_extract_path_text(p.extra_metadata, 'compatible_proteoform_number') AS integer), 0) AS compatible_proteoform_number,
                COALESCE(CAST(jsonb_extract_path_text(p.extra_metadata, 'prsm_number') AS integer), 0) AS prsm_number,
                CAST(jsonb_extract_path_text(p.extra_metadata, 'best_prsm_id') AS integer) AS best_prsm_id,
                CAST(jsonb_extract_path_text(p.extra_metadata, 'best_prsm_e_value') AS double precision) AS best_prsm_e_value
            FROM proteins p
            WHERE p.dataset_id = :dataset_id AND p.protein_id = :protein_id
            """
        ),
        {"dataset_id": dataset["dataset_id"], "protein_id": protein_id},
    ).mappings().one_or_none()
    if protein is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "protein not found")

    pfs = session.execute(
        text(
            """
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
            FROM protein_relation_mapping prm
            JOIN proteoforms pf ON pf.proteoform_id = prm.entity_id
            WHERE prm.dataset_id = :dataset_id
              AND prm.protein_id = :protein_id
              AND prm.entity_type = 'PROTEOFORM'
            ORDER BY proteoform_id
            """
        ),
        {"dataset_id": dataset["dataset_id"], "protein_id": protein_id},
    ).mappings().all()
    return ProteinDetailOut(
        **dict(protein),
        proteoforms=[ProteoformListItemOut(**dict(pf)) for pf in pfs],
    )
