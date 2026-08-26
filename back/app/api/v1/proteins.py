"""某 cutoff 下的蛋白质列表与详情 API：读取 universal schema。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.universal_compat import require_cutoff, require_dataset
from app.schemas import Page, ProteinDetailOut, ProteinListItemOut, ProteoformListItemOut
from app.zp_runtime import (
    ZpAssetReadError,
    ZpTopDownProtein,
    ZpTopDownProteoform,
    get_binary_top_down_protein,
    get_binary_top_down_proteoform,
)

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
    """分页列出蛋白质；可选名称/描述模糊搜索。`total` 为过滤后总行数。

    Cutoff 维度通过 ``EXISTS (identification_matches WHERE source_cutoff = :cutoff)``
    在 protein → proteoform → match 链路上过滤；仅在该 cutoff 下产生过鉴定的
    蛋白才会出现在列表里。
    """
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
          AND EXISTS (
            SELECT 1
            FROM protein_relation_mapping prm
            JOIN identification_matches im
              ON im.dataset_id = prm.dataset_id
             AND im.entity_type = prm.entity_type
             AND im.entity_id = prm.entity_id
            WHERE prm.dataset_id = p.dataset_id
              AND prm.protein_id = p.protein_id
              AND jsonb_extract_path_text(im.extra_metadata, 'source_cutoff') = :cutoff
          )
    """
    params: dict[str, object] = {"dataset_id": dataset["dataset_id"], "cutoff": cutoff}
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
        items=[
            ProteinListItemOut(**_binary_protein_payload(session, int(dataset["dataset_id"]), dict(r)))
            for r in rows
        ],
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
    """单条蛋白质详情；路径中的 protein_id 为表 ``proteins.protein_id``（主键）。

    Cutoff 维度：要求该蛋白在当前 cutoff 下至少有一条 ``identification_matches``
    记录；下属 proteoform 列表也会按同一 cutoff 过滤。
    """
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
              AND EXISTS (
                SELECT 1
                FROM protein_relation_mapping prm
                JOIN identification_matches im
                  ON im.dataset_id = prm.dataset_id
                 AND im.entity_type = prm.entity_type
                 AND im.entity_id = prm.entity_id
                WHERE prm.dataset_id = p.dataset_id
                  AND prm.protein_id = p.protein_id
                  AND jsonb_extract_path_text(im.extra_metadata, 'source_cutoff') = :cutoff
              )
            """
        ),
        {"dataset_id": dataset["dataset_id"], "protein_id": protein_id, "cutoff": cutoff},
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
              AND EXISTS (
                SELECT 1 FROM identification_matches im
                WHERE im.dataset_id = prm.dataset_id
                  AND im.entity_type = prm.entity_type
                  AND im.entity_id = prm.entity_id
                  AND jsonb_extract_path_text(im.extra_metadata, 'source_cutoff') = :cutoff
              )
            ORDER BY proteoform_id
            """
        ),
        {"dataset_id": dataset["dataset_id"], "protein_id": protein_id, "cutoff": cutoff},
    ).mappings().all()
    protein_payload = dict(protein)
    binary = _safe_binary_top_down_protein(
        session,
        int(dataset["dataset_id"]),
        sequence_id=protein_payload.get("sequence_id"),
        sequence_name=str(protein_payload.get("sequence_name") or ""),
    )
    if binary is not None:
        protein_payload = _apply_binary_protein_item(protein_payload, binary)
    return ProteinDetailOut(
        **protein_payload,
        proteoforms=[
            ProteoformListItemOut(**_binary_proteoform_payload(session, int(dataset["dataset_id"]), dict(pf)))
            for pf in pfs
        ],
    )


def _binary_protein_payload(
    session: Session,
    dataset_id: int,
    payload: dict[str, object],
) -> dict[str, object]:
    binary = _safe_binary_top_down_protein(
        session,
        dataset_id,
        sequence_id=payload.get("sequence_id"),
        sequence_name=str(payload.get("sequence_name") or ""),
    )
    return _apply_binary_protein_item(payload, binary) if binary is not None else payload


def _safe_binary_top_down_protein(
    session: Session,
    dataset_id: int,
    *,
    sequence_id: object,
    sequence_name: str,
) -> ZpTopDownProtein | None:
    try:
        return get_binary_top_down_protein(
            session,
            dataset_id,
            sequence_id=sequence_id,
            sequence_name=sequence_name,
        )
    except ZpAssetReadError:
        return None


def _apply_binary_protein_item(
    payload: dict[str, object],
    binary: ZpTopDownProtein,
) -> dict[str, object]:
    best_prsm = _best_prsm(binary.prsms)
    out = dict(payload)
    out["sequence_id"] = _int_first(binary.sequence_id, out.get("sequence_id"))
    out["sequence_name"] = _first_value(binary.protein_accession, out.get("sequence_name"))
    out["sequence_description"] = _first_value(binary.protein_description, out.get("sequence_description"))
    out["compatible_proteoform_number"] = len(binary.proteoforms)
    out["prsm_number"] = len(binary.prsms)
    out["best_prsm_id"] = _int_or_none(_first_value((best_prsm or {}).get("prsm_id"), out.get("best_prsm_id")))
    out["best_prsm_e_value"] = _first_value((best_prsm or {}).get("e_value"), out.get("best_prsm_e_value"))
    return out


def _binary_proteoform_payload(
    session: Session,
    dataset_id: int,
    payload: dict[str, object],
) -> dict[str, object]:
    binary = _safe_binary_top_down_proteoform(
        session,
        dataset_id,
        payload.get("proteoform_id"),
        sequence_id=payload.get("sequence_id"),
    )
    return _apply_binary_proteoform_item(payload, binary) if binary is not None else payload


def _safe_binary_top_down_proteoform(
    session: Session,
    dataset_id: int,
    proteoform_id: object,
    *,
    sequence_id: object,
) -> ZpTopDownProteoform | None:
    try:
        return get_binary_top_down_proteoform(
            session,
            dataset_id,
            proteoform_id,
            sequence_id=sequence_id,
        )
    except ZpAssetReadError:
        return None


def _apply_binary_proteoform_item(
    payload: dict[str, object],
    binary: ZpTopDownProteoform,
) -> dict[str, object]:
    proteoform = binary.proteoform
    best_prsm = _best_prsm(binary.prsms)
    out = dict(payload)
    out["sequence_id"] = _int_first(proteoform.get("sequence_id"), out.get("sequence_id"))
    out["sequence_name"] = _first_value(proteoform.get("protein_accession"), out.get("sequence_name"))
    out["proteoform_mass"] = _first_value(
        proteoform.get("theoretical_mass"),
        proteoform.get("experimental_mass"),
        out.get("proteoform_mass"),
    )
    out["prsm_number"] = len(binary.prsms)
    out["best_prsm_id"] = _int_or_none(_first_value(proteoform.get("best_prsm_id"), (best_prsm or {}).get("prsm_id"), out.get("best_prsm_id")))
    out["best_prsm_e_value"] = _first_value((best_prsm or {}).get("e_value"), out.get("best_prsm_e_value"))
    out["n_acetylation"] = 1 if proteoform.get("terminal_state") == "N_ACETYLATION" else out.get("n_acetylation")
    return out


def _best_prsm(records: tuple[dict[str, object], ...]) -> dict[str, object] | None:
    if not records:
        return None
    return min(records, key=lambda item: (_float_or_none(item.get("e_value")) is None, _float_or_none(item.get("e_value")) or 0.0))


def _first_value(*values: object) -> object:
    for value in values:
        if value is not None:
            return value
    return None


def _int_first(*values: object) -> int:
    for value in values:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return 0


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
