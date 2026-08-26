"""某 cutoff 下的 PrSM 列表与详情 API：读取 universal schema。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.universal_compat import load_prsm_detail, prsm_list_item, prsm_list_select_sql, require_cutoff, require_dataset
from app.ingest.utils import to_float, to_int
from app.schemas import Page, PrsmDetailOut, PrsmListItemOut
from app.zp_runtime import ZpAssetReadError, ZpTopDownPrsm, get_binary_top_down_prsm

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
        items=[
            PrsmListItemOut(**_binary_prsm_list_payload(session, int(dataset["dataset_id"]), prsm_list_item(dict(r))))
            for r in rows
        ],
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

    Universal schema has no ``prsms`` table; PrSMs live in
    ``identification_matches`` and the original TopPIC numeric id is stored as
    ``extra_metadata.source_prsm_id`` (with cutoff in
    ``extra_metadata.source_cutoff``). The composite
    ``(dataset_id, source_cutoff, source_prsm_id)`` is treated as unique by the
    universal adapter (see ``app.ingest.universal_toppic_adapter``).

    Using the business id here means the URL shown in the UI (``PrSM #4534``)
    matches the navigation URL (``/prsms/4534``), and links coming from
    ``best_prsm_id`` (stored as the TopPIC business id, not a DB primary key)
    resolve correctly.
    """
    dataset = require_dataset(session, slug)
    require_cutoff(cutoff)
    row = session.execute(
        text(
            """
            SELECT
                im.match_id AS id,
                im.dataset_id AS dataset_id,
                im.run_id AS run_id,
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
    binary = _safe_binary_top_down_prsm(session, int(dataset["dataset_id"]), prsm_id)
    if binary is not None:
        item = _apply_binary_prsm_item(item, binary)
        annotated, ms_header, ms_peaks = _binary_prsm_detail_parts(binary)
    else:
        annotated, ms_header, ms_peaks = load_prsm_detail(row["detail_path"])
    if ms_header:
        item["precursor_mono_mass"] = item["precursor_mono_mass"] or to_float(ms_header.get("precursor_mono_mass"))
        item["precursor_charge"] = item["precursor_charge"] or to_int(ms_header.get("precursor_charge"))
        item["precursor_mz"] = item["precursor_mz"] or to_float(ms_header.get("precursor_mz"))
        item["ms1_scans"] = item["ms1_scans"] or _as_text(ms_header.get("ms1_scans"))
        item["ms2_scans"] = item["ms2_scans"] or _as_text(ms_header.get("scans"))
    if annotated:
        item["proteoform_mass"] = item["proteoform_mass"] or to_float(annotated.get("proteoform_mass"))
    spectrum_reference = _json_object(binary.prsm.get("spectrum_reference")) if binary is not None else {}
    spectrum_file_name = _first_value(
        spectrum_reference.get("spectrum_file_name"),
        ms_header.get("spectrum_file_name") if ms_header else None,
    )
    return PrsmDetailOut(
        **item,
        dataset_id=row["dataset_id"],
        run_id=row["run_id"],
        proteoform_id=row["db_proteoform_id"],
        spectrum_file_name=spectrum_file_name,
        ms1_ids=_first_value(_joined_text(spectrum_reference.get("ms1_ids")), row["ms1_ids"], (_as_text(ms_header.get("ms1_ids")) if ms_header else None)),
        ms2_ids=_first_value(_joined_text(spectrum_reference.get("native_ids")), row["ms2_ids"], (_as_text(ms_header.get("ids")) if ms_header else None)),
        feature_inte=_first_value((binary.prsm.get("feature_intensity") if binary is not None else None), row["feature_inte"], (to_float(ms_header.get("feature_inte")) if ms_header else None)),
        ms_header=ms_header,
        annotated_protein=annotated,
        ms_peaks=ms_peaks,
    )


def _as_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _binary_prsm_list_payload(
    session: Session,
    dataset_id: int,
    payload: dict[str, object],
) -> dict[str, object]:
    binary = _safe_binary_top_down_prsm(session, dataset_id, int(payload["prsm_id"]))
    return _apply_binary_prsm_item(payload, binary) if binary is not None else payload


def _safe_binary_top_down_prsm(
    session: Session,
    dataset_id: int,
    prsm_id: int,
) -> ZpTopDownPrsm | None:
    try:
        return get_binary_top_down_prsm(session, dataset_id, prsm_id)
    except ZpAssetReadError:
        return None


def _apply_binary_prsm_item(
    payload: dict[str, object],
    binary: ZpTopDownPrsm,
) -> dict[str, object]:
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


def _binary_prsm_detail_parts(
    binary: ZpTopDownPrsm,
) -> tuple[dict[str, object] | None, dict[str, object] | None, dict[str, object] | None]:
    source_fields = _json_object(binary.prsm.get("source_fields"))
    detail_ref = _json_object(source_fields.get("prsm_detail"))
    detail = _json_object(detail_ref.get("value"))
    annotated = detail.get("annotated_protein") if isinstance(detail.get("annotated_protein"), dict) else None
    ms = _json_object(detail.get("ms"))
    ms_header = ms.get("ms_header") if isinstance(ms.get("ms_header"), dict) else None
    ms_peaks = ms.get("peaks") if isinstance(ms.get("peaks"), dict) else None
    if ms_peaks is None and binary.peaks:
        ms_peaks = {"peaks": [dict(item) for item in binary.peaks]}
    return annotated, ms_header, ms_peaks


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
