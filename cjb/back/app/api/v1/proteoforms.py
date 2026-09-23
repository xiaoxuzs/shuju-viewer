"""某 cutoff 下的 proteoform 列表与详情 API：读取 universal schema。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.universal_compat import prsm_list_item, prsm_list_select_sql, require_cutoff, require_dataset
from app.schemas import Page, PrsmListItemOut, ProteoformDetailOut, ProteoformListItemOut
from app.zp_runtime import (
    ZpAssetReadError,
    ZpTopDownPrsm,
    ZpTopDownProteoform,
    get_binary_top_down_prsm,
    get_binary_top_down_proteoform,
)

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
    """分页列出 proteoform；若传 ``protein_id`` 则仅返回该蛋白质（``proteins.protein_id``）下的形式。

    Cutoff 维度：仅返回在当前 cutoff 下出现过 ``identification_matches`` 的
    proteoform —— 这是唯一可靠的归属判据，因为 universal 的 ``proteoforms``
    表本身是跨 cutoff 共享的。
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
        items=[
            ProteoformListItemOut(**_binary_proteoform_payload(session, int(dataset["dataset_id"]), dict(r)))
            for r in rows
        ],
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
    """详情路径中的 proteoform_id 为 ``proteoforms.proteoform_id``（主键），非 TopPIC 的 proteoform 业务号。

    Cutoff 维度：proteoform 行本身是跨 cutoff 共享的，但 URL 里点了 ``cutoff=X``
    就要求该 proteoform 在 X 这个 cutoff 下至少有一条 ``identification_matches``，
    否则返回 404，避免在 prsm cutoff 下显示只在 proteoform cutoff 下出现的 form。
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
    pf_payload = dict(pf)
    binary = _safe_binary_top_down_proteoform(
        session,
        int(dataset["dataset_id"]),
        pf_payload.get("proteoform_id"),
        sequence_id=pf_payload.get("sequence_id"),
    )
    if binary is not None:
        pf_payload = _apply_binary_proteoform_item(pf_payload, binary)
    return ProteoformDetailOut(
        **pf_payload,
        prsms=[
            PrsmListItemOut(**_binary_prsm_payload(session, int(dataset["dataset_id"]), prsm_list_item(dict(p))))
            for p in prsms
        ],
    )


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


def _binary_prsm_payload(
    session: Session,
    dataset_id: int,
    payload: dict[str, object],
) -> dict[str, object]:
    binary = _safe_binary_top_down_prsm(session, dataset_id, int(payload["prsm_id"]))
    if binary is None:
        return payload
    prsm = binary.prsm
    proteoform = binary.proteoform or {}
    reference = _json_object(prsm.get("spectrum_reference"))
    out = dict(payload)
    out["sequence_id"] = _int_first(proteoform.get("sequence_id"), out.get("sequence_id"))
    out["p_value"] = _first_value(prsm.get("p_value"), out.get("p_value"))
    out["e_value"] = _first_value(prsm.get("e_value"), out.get("e_value"))
    out["fdr"] = _first_value(prsm.get("q_value"), out.get("fdr"))
    out["matched_fragment_number"] = _first_value(prsm.get("matched_fragment_count"), out.get("matched_fragment_number"))
    out["matched_peak_number"] = _first_value(prsm.get("matched_peak_count"), out.get("matched_peak_number"))
    out["precursor_mono_mass"] = _first_value(prsm.get("precursor_mass"), out.get("precursor_mono_mass"))
    out["precursor_charge"] = _first_value(prsm.get("charge"), out.get("precursor_charge"))
    out["precursor_mz"] = _first_value(prsm.get("precursor_mz"), out.get("precursor_mz"))
    out["proteoform_mass"] = _first_value(
        proteoform.get("theoretical_mass"),
        proteoform.get("experimental_mass"),
        prsm.get("adjusted_mass"),
        out.get("proteoform_mass"),
    )
    out["ms1_scans"] = _first_value(_joined_text(reference.get("ms1_scan_numbers")), out.get("ms1_scans"))
    out["ms2_scans"] = _first_value(_joined_text(reference.get("scan_numbers")), out.get("ms2_scans"))
    return out


def _safe_binary_top_down_prsm(
    session: Session,
    dataset_id: int,
    prsm_id: int,
) -> ZpTopDownPrsm | None:
    try:
        return get_binary_top_down_prsm(session, dataset_id, prsm_id)
    except ZpAssetReadError:
        return None


def _best_prsm(records: tuple[dict[str, object], ...]) -> dict[str, object] | None:
    if not records:
        return None
    return min(records, key=lambda item: (_float_or_none(item.get("e_value")) is None, _float_or_none(item.get("e_value")) or 0.0))


def _json_object(raw: object) -> dict[str, object]:
    return dict(raw) if isinstance(raw, dict) else {}


def _joined_text(value: object) -> str | None:
    if isinstance(value, (list, tuple)):
        values = [str(item) for item in value if item is not None]
        return ",".join(values) if values else None
    return str(value) if value is not None else None


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
