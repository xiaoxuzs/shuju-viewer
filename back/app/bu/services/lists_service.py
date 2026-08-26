"""Bottom-Up list and summary queries."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.schemas import (
    BuMatchDetailOut,
    BuMatchListItemOut,
    BuPeptideDetailOut,
    BuPeptideListItemOut,
    BuPeptideMatchesSummary,
    BuPeptideMatchSummaryItem,
    BuPeptideProteinRef,
    BuProteinListItemOut,
    BuProteinMini,
    BuRtWindow,
    BuRunDetail,
    Page,
)
from app.zp_runtime import (
    ZpBottomUpMatch,
    ZpBottomUpPeptide,
    ZpBottomUpProtein,
    get_binary_bottom_up_match,
    get_binary_bottom_up_peptide,
    get_binary_bottom_up_protein,
)


def _json_object(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _protein_accessions(protein_group: str | None) -> list[str]:
    if not protein_group:
        return []
    return [part.strip() for part in protein_group.split(";") if part.strip()]


def _q_value_cutoff(dataset: dict[str, Any], q_max: float | None) -> float | None:
    if q_max is not None:
        return q_max
    extra = _json_object(dataset.get("extra_metadata"))
    value = extra.get("q_value_cutoff")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pagination(page: int, page_size: int) -> tuple[int, int]:
    return (page - 1) * page_size, page_size


def _use_binary_entities(session: Session, dataset_id: int) -> bool:
    try:
        has_db_rows = bool(
            session.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM identification_matches
                        WHERE dataset_id = :dataset_id
                          AND entity_type = 'PEPTIDE'
                        LIMIT 1
                    )
                    """
                ),
                {"dataset_id": dataset_id},
            )
        )
    except (AttributeError, SQLAlchemyError):
        return True
    return not has_db_rows


def list_matches(
    session: Session,
    dataset: dict[str, Any],
    *,
    page: int,
    page_size: int,
    q_max: float | None,
    run_id: int | None,
    peptide_id: int | None,
    protein_id: int | None,
    charge: int | None,
    search: str | None,
    decoy: bool,
    sort: str,
    order: str,
) -> Page[BuMatchListItemOut]:
    dataset_id = int(dataset["dataset_id"])
    params: dict[str, Any] = {"dataset_id": dataset_id}
    where = ["im.dataset_id = :dataset_id", "im.entity_type = 'PEPTIDE'"]
    cutoff = _q_value_cutoff(dataset, q_max)
    if cutoff is not None:
        where.append("im.q_value <= :q_max")
        params["q_max"] = cutoff
    if not decoy:
        where.append("im.is_decoy_match = false")
    if run_id is not None:
        where.append("im.run_id = :run_id")
        params["run_id"] = run_id
    if peptide_id is not None:
        where.append("im.entity_id = :peptide_id")
        params["peptide_id"] = peptide_id
    if charge is not None:
        where.append("im.precursor_charge = :charge")
        params["charge"] = charge
    if protein_id is not None:
        where.append(
            """
            EXISTS (
                SELECT 1
                FROM protein_relation_mapping prm
                WHERE prm.dataset_id = im.dataset_id
                  AND prm.entity_type = 'PEPTIDE'
                  AND prm.entity_id = im.entity_id
                  AND prm.protein_id = :protein_id
            )
            """
        )
        params["protein_id"] = protein_id
    if search:
        where.append(
            """
            (
                p.sequence ILIKE :search
                OR im.modified_sequence ILIKE :search
                OR jsonb_extract_path_text(im.extra_metadata, 'protein_group') ILIKE :search
                OR jsonb_extract_path_text(im.extra_metadata, 'genes') ILIKE :search
            )
            """
        )
        params["search"] = f"%{search}%"

    where_sql = " AND ".join(where)
    base_sql = f"""
        FROM identification_matches im
        JOIN peptides p
          ON p.dataset_id = im.dataset_id
         AND p.peptide_id = im.entity_id
        JOIN runs r
          ON r.dataset_id = im.dataset_id
         AND r.run_id = im.run_id
        WHERE {where_sql}
    """
    total = int(session.scalar(text(f"SELECT count(*) {base_sql}"), params) or 0)
    sort_map = {
        "q_value": "im.q_value",
        "score": "im.score",
        "retention_time": "im.retention_time",
        "precursor_mz": "im.precursor_mz",
        "precursor_charge": "im.precursor_charge",
        "intensity": "im.intensity",
        "match_id": "im.match_id",
    }
    sort_col = sort_map.get(sort, "im.q_value")
    offset, limit = _pagination(page, page_size)
    params.update({"offset": offset, "limit": limit})
    rows = session.execute(
        text(
            f"""
            SELECT
                im.match_id AS id,
                im.run_id,
                r.file_name AS run_name,
                im.entity_id AS peptide_id,
                p.sequence,
                im.modified_sequence,
                im.precursor_mz,
                im.precursor_charge,
                im.retention_time,
                im.experimental_mass,
                im.q_value,
                im.score,
                im.intensity,
                im.is_decoy_match,
                im.scan_number,
                jsonb_extract_path_text(im.extra_metadata, 'protein_group') AS protein_group,
                jsonb_extract_path_text(im.extra_metadata, 'genes') AS genes,
                im.search_engine
            {base_sql}
            ORDER BY {sort_col} {'ASC' if order == 'asc' else 'DESC'} NULLS LAST, im.match_id ASC
            OFFSET :offset LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    items = [
        BuMatchListItemOut(
            **dict(row),
            protein_accessions=_protein_accessions(row.get("protein_group")),
        )
        for row in rows
    ]
    return Page[BuMatchListItemOut](items=items, total=total, page=page, page_size=page_size)


def list_proteins(
    session: Session,
    dataset: dict[str, Any],
    *,
    page: int,
    page_size: int,
    search: str | None,
    decoy: bool,
) -> Page[BuProteinListItemOut]:
    params: dict[str, Any] = {"dataset_id": int(dataset["dataset_id"])}
    where = ["p.dataset_id = :dataset_id"]
    if not decoy:
        where.append("p.is_decoy = false")
    if search:
        where.append(
            """
            (
                p.accession ILIKE :search
                OR p.gene_name ILIKE :search
                OR p.description ILIKE :search
                OR jsonb_extract_path_text(p.extra_metadata, 'protein_group') ILIKE :search
            )
            """
        )
        params["search"] = f"%{search}%"
    where_sql = " AND ".join(where)
    base_sql = f"""
        FROM proteins p
        LEFT JOIN protein_relation_mapping prm
          ON prm.dataset_id = p.dataset_id
         AND prm.protein_id = p.protein_id
         AND prm.entity_type = 'PEPTIDE'
        LEFT JOIN identification_matches im
          ON im.dataset_id = prm.dataset_id
         AND im.entity_type = 'PEPTIDE'
         AND im.entity_id = prm.entity_id
        WHERE {where_sql}
        GROUP BY p.protein_id
    """
    total = int(session.scalar(text(f"SELECT count(*) FROM (SELECT p.protein_id {base_sql}) q"), params) or 0)
    offset, limit = _pagination(page, page_size)
    params.update({"offset": offset, "limit": limit})
    rows = session.execute(
        text(
            f"""
            SELECT
                p.protein_id AS id,
                p.accession,
                p.gene_name,
                p.description,
                p.is_decoy,
                jsonb_extract_path_text(p.extra_metadata, 'protein_group') AS protein_group,
                count(DISTINCT prm.entity_id) AS peptide_count,
                count(im.match_id) AS match_count,
                min(im.q_value) AS best_q_value,
                CAST(jsonb_extract_path_text(p.extra_metadata, 'pg_max_lfq') AS double precision) AS pg_max_lfq,
                CAST(jsonb_extract_path_text(p.extra_metadata, 'pg_q_value') AS double precision) AS pg_q_value,
                NULL::double precision AS pg_quantity
            {base_sql}
            ORDER BY best_q_value ASC NULLS LAST, p.protein_id ASC
            OFFSET :offset LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    items = []
    use_binary = _use_binary_entities(session, int(dataset["dataset_id"]))
    for row in rows:
        payload = dict(row)
        binary = (
            get_binary_bottom_up_protein(session, int(dataset["dataset_id"]), str(payload.get("accession") or ""))
            if use_binary
            else None
        )
        if binary is not None:
            payload = _binary_protein_list_payload(payload, binary)
        items.append(BuProteinListItemOut(**payload))
    return Page[BuProteinListItemOut](
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


def list_peptides(
    session: Session,
    dataset: dict[str, Any],
    *,
    page: int,
    page_size: int,
    search: str | None,
    q_max: float | None,
) -> Page[BuPeptideListItemOut]:
    params: dict[str, Any] = {"dataset_id": int(dataset["dataset_id"])}
    where = ["p.dataset_id = :dataset_id"]
    if search:
        where.append("p.sequence ILIKE :search")
        params["search"] = f"%{search}%"
    cutoff = _q_value_cutoff(dataset, q_max)
    im_filter = ""
    if cutoff is not None:
        im_filter = "AND im.q_value <= :q_max"
        params["q_max"] = cutoff
    where_sql = " AND ".join(where)
    base_sql = f"""
        FROM peptides p
        LEFT JOIN identification_matches im
          ON im.dataset_id = p.dataset_id
         AND im.entity_type = 'PEPTIDE'
         AND im.entity_id = p.peptide_id
         AND im.is_decoy_match = false
         {im_filter}
        LEFT JOIN protein_relation_mapping prm
          ON prm.dataset_id = p.dataset_id
         AND prm.entity_type = 'PEPTIDE'
         AND prm.entity_id = p.peptide_id
        WHERE {where_sql}
        GROUP BY p.peptide_id
    """
    total = int(session.scalar(text(f"SELECT count(*) FROM (SELECT p.peptide_id {base_sql}) q"), params) or 0)
    offset, limit = _pagination(page, page_size)
    params.update({"offset": offset, "limit": limit})
    rows = session.execute(
        text(
            f"""
            SELECT
                p.peptide_id AS id,
                p.sequence,
                p.length,
                p.theoretical_mass,
                p.missed_cleavages,
                count(im.match_id) AS match_count,
                count(DISTINCT prm.protein_id) AS protein_count,
                min(im.q_value) AS best_q_value,
                (array_agg(im.precursor_mz ORDER BY im.q_value ASC NULLS LAST))[1] AS best_precursor_mz,
                (array_agg(im.precursor_charge ORDER BY im.q_value ASC NULLS LAST))[1] AS best_charge,
                (array_agg(im.match_id ORDER BY im.q_value ASC NULLS LAST))[1] AS best_match_id,
                string_agg(DISTINCT jsonb_extract_path_text(im.extra_metadata, 'protein_group'), ';') AS protein_groups,
                string_agg(DISTINCT jsonb_extract_path_text(im.extra_metadata, 'genes'), ';') AS genes,
                (array_agg(im.modified_sequence ORDER BY im.q_value ASC NULLS LAST))[1] AS example_modified
            {base_sql}
            ORDER BY best_q_value ASC NULLS LAST, p.peptide_id ASC
            OFFSET :offset LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    items = []
    use_binary = _use_binary_entities(session, int(dataset["dataset_id"]))
    for row in rows:
        payload = dict(row)
        binary = (
            get_binary_bottom_up_peptide(session, int(dataset["dataset_id"]), str(payload.get("sequence") or ""))
            if use_binary
            else None
        )
        if binary is not None:
            payload = _binary_peptide_list_payload(payload, binary)
        items.append(BuPeptideListItemOut(**payload))
    return Page[BuPeptideListItemOut](
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


def get_match_detail(
    session: Session,
    dataset: dict[str, Any],
    match: dict[str, Any],
) -> BuMatchDetailOut:
    binary = (
        get_binary_bottom_up_match(session, int(dataset["dataset_id"]), match)
        if _use_binary_entities(session, int(dataset["dataset_id"]))
        else None
    )
    meta = _json_object(match.get("extra_metadata"))
    run_meta = _json_object(match.get("run_metadata"))
    if binary is not None:
        meta = _binary_match_metadata(meta, binary)
    binary_identification = binary.identification if binary is not None else {}
    binary_spectrum = binary.spectrum if binary is not None else None
    binary_typed = _json_object(binary_identification.get("typed_fields"))
    scan_number = _binary_scan_number(binary_spectrum, match["scan_number"])
    scan_available = scan_number >= 0
    proteins = session.execute(
        text(
            """
            SELECT p.protein_id, p.accession, p.gene_name, p.description
            FROM protein_relation_mapping prm
            JOIN proteins p
              ON p.dataset_id = prm.dataset_id
             AND p.protein_id = prm.protein_id
            WHERE prm.dataset_id = :dataset_id
              AND prm.entity_type = 'PEPTIDE'
              AND prm.entity_id = :peptide_id
            ORDER BY p.protein_id
            """
        ),
        {"dataset_id": int(dataset["dataset_id"]), "peptide_id": int(match["entity_id"])},
    ).mappings().all()
    protein_group = meta.get("protein_group")
    links_base = f"/api/v1/datasets/{dataset['slug']}/matches/{match['match_id']}"
    rt_apex = _first_value(
        _seconds_to_minutes(binary_identification.get("rt_seconds")),
        match.get("retention_time"),
    )
    list_item = BuMatchListItemOut(
        id=int(match["match_id"]),
        run_id=int(match["run_id"]),
        run_name=str(match["run_name"] or ""),
        peptide_id=int(match["entity_id"]),
        sequence=str(_first_value(binary_identification.get("stripped_sequence"), match.get("sequence"), "")),
        modified_sequence=_first_value(binary_identification.get("modified_sequence"), match.get("modified_sequence")),
        precursor_mz=_first_value(binary_identification.get("precursor_mz"), match.get("precursor_mz")),
        precursor_charge=_first_value(binary_identification.get("charge"), match.get("precursor_charge")),
        retention_time=rt_apex,
        experimental_mass=_first_value(binary_identification.get("neutral_mass"), match.get("experimental_mass")),
        q_value=_first_value(binary_typed.get("q_value"), match.get("q_value")),
        score=_first_value(binary_typed.get("global_q_value"), binary_typed.get("q_value"), match.get("score")),
        intensity=_first_value(_binary_identification_intensity(binary), match.get("intensity")),
        is_decoy_match=bool(match.get("is_decoy_match")),
        scan_number=scan_number,
        protein_group=protein_group,
        protein_accessions=_protein_accessions(protein_group),
        genes=meta.get("genes"),
        search_engine=match.get("search_engine"),
    )
    return BuMatchDetailOut(
        **list_item.model_dump(),
        identification_rt_apex=rt_apex,
        scan_available=scan_available,
        scan_unavailable_reason=None if scan_available else "Not available from imported match metadata",
        spectrum_native_id=_first_value(
            (binary_spectrum or {}).get("native_id") if binary_spectrum else None,
            match.get("spectrum_native_id"),
        ),
        ms_level=int(_first_value((binary_spectrum or {}).get("ms_level") if binary_spectrum else None, match.get("ms_level"), 2)),
        run=BuRunDetail(
            run_id=int(match["run_id"]),
            file_name=str(match["run_name"] or ""),
            raw_format=run_meta.get("raw_format"),
            file_path=str(match["file_path"] or ""),
            diann_run_name=run_meta.get("diann_run_name"),
        ),
        rt_window=BuRtWindow(
            rt_start=_first_value(_seconds_to_minutes(binary_identification.get("rt_start_seconds")), meta.get("rt_start")),
            rt_stop=_first_value(_seconds_to_minutes(binary_identification.get("rt_stop_seconds")), meta.get("rt_stop")),
            rt_apex=rt_apex,
        ),
        proteins=[BuProteinMini(**dict(row)) for row in proteins],
        diann={
            "precursor_id": meta.get("precursor_id"),
            "lib_qvalue": meta.get("lib_qvalue"),
            "mass_accuracy": meta.get("mass_evidence"),
            "ms2_scan": meta.get("ms2_scan"),
            "resolved_scan": meta.get("resolved_scan"),
            "binary_identification_id": binary_identification.get("identification_id"),
            "binary_spectrum_id": binary_identification.get("spectrum_id"),
        },
        spectrum_links={
            "xic": f"{links_base}/xic",
            "ms2": f"{links_base}/spectrum/ms2",
            "ms1": f"{links_base}/spectrum/ms1",
            "mobility_slice": f"{links_base}/mobility-slice" if run_meta.get("raw_format") == "bruker_d" else None,
        },
        extra_metadata=meta,
    )


def _binary_match_metadata(
    meta: dict[str, Any],
    binary: ZpBottomUpMatch,
) -> dict[str, Any]:
    identification = binary.identification
    typed = _json_object(identification.get("typed_fields"))
    source = _json_object(identification.get("source_fields"))
    protein_group = binary.protein_group or {}
    out = dict(meta)
    updates = {
        "precursor_id": identification.get("source_precursor_id"),
        "rt_start": _seconds_to_minutes(identification.get("rt_start_seconds")),
        "rt_stop": _seconds_to_minutes(identification.get("rt_stop_seconds")),
        "protein_group": _first_value(protein_group.get("source_group"), source.get("Protein.Group"), meta.get("protein_group")),
        "genes": _first_value(source.get("Genes"), meta.get("genes")),
        "lib_qvalue": _first_value(typed.get("lib_q_value"), meta.get("lib_qvalue")),
        "mass_evidence": _first_value(typed.get("mass_evidence"), meta.get("mass_evidence")),
        "binary_identification_id": identification.get("identification_id"),
        "binary_spectrum_id": identification.get("spectrum_id"),
    }
    for key, value in updates.items():
        if value is not None:
            out[key] = value
    return out


def _binary_scan_number(spectrum: dict[str, Any] | None, fallback: Any) -> int:
    if spectrum is not None:
        try:
            return int(spectrum["scan_number"])
        except (KeyError, TypeError, ValueError):
            pass
    return int(fallback)


def _binary_identification_intensity(binary: ZpBottomUpMatch | None) -> float | None:
    if binary is None:
        return None
    for record in binary.quantification:
        if record.get("entity_kind") != "identification":
            continue
        measurements = _json_object(record.get("measurements"))
        for key in (
            "precursor_quantity",
            "precursor_normalised",
            "ms1_area",
            "ms1_apex_area",
        ):
            value = measurements.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
    return None


def _binary_peptide_list_payload(
    payload: dict[str, Any],
    binary: ZpBottomUpPeptide,
) -> dict[str, Any]:
    peptide = binary.peptide
    best = _best_bottom_up_identification(binary.identifications)
    out = dict(payload)
    out["sequence"] = _first_value(peptide.get("sequence"), out.get("sequence"))
    out["length"] = _first_value(peptide.get("length"), out.get("length"))
    out["match_count"] = len(binary.identifications)
    out["protein_count"] = len(binary.proteins)
    out["best_q_value"] = _first_value(_bottom_up_q_value(best), out.get("best_q_value"))
    out["best_precursor_mz"] = _first_value((best or {}).get("precursor_mz"), out.get("best_precursor_mz"))
    out["best_charge"] = _first_value((best or {}).get("charge"), out.get("best_charge"))
    out["protein_groups"] = _first_value(_joined_values(binary.protein_groups, "source_group"), out.get("protein_groups"))
    out["genes"] = _first_value(_joined_values(binary.proteins, "gene"), out.get("genes"))
    out["example_modified"] = _first_value(
        _first_list_value(peptide.get("modified_sequences")),
        (best or {}).get("modified_sequence"),
        out.get("example_modified"),
    )
    return out


def _binary_protein_list_payload(
    payload: dict[str, Any],
    binary: ZpBottomUpProtein,
) -> dict[str, Any]:
    protein = binary.protein
    out = dict(payload)
    out["accession"] = _first_value(protein.get("accession"), out.get("accession"))
    out["gene_name"] = _first_value(protein.get("gene"), protein.get("name"), out.get("gene_name"))
    out["description"] = _first_value(protein.get("description"), out.get("description"))
    out["is_decoy"] = bool(_first_value(protein.get("is_decoy"), out.get("is_decoy")))
    out["protein_group"] = _first_value(_joined_values(binary.protein_groups, "source_group"), out.get("protein_group"))
    out["peptide_count"] = len(binary.peptides)
    out["match_count"] = len(binary.identifications)
    out["best_q_value"] = _first_value(_best_bottom_up_q_value(binary.identifications), out.get("best_q_value"))
    out["pg_q_value"] = _first_value(protein.get("q_value"), out.get("pg_q_value"))
    return out


def _binary_peptide_metadata(
    meta: dict[str, Any],
    binary: ZpBottomUpPeptide,
) -> dict[str, Any]:
    out = dict(meta)
    peptide = binary.peptide
    updates = {
        "binary_peptide_id": peptide.get("peptide_id"),
        "binary_identification_ids": [item.get("identification_id") for item in binary.identifications],
        "binary_protein_ids": [item.get("protein_id") for item in binary.proteins],
        "binary_protein_group_ids": [item.get("protein_group_id") for item in binary.protein_groups],
        "binary_modified_sequences": peptide.get("modified_sequences"),
        "binary_precursor_charges": peptide.get("precursor_charges"),
        "binary_modification_count": len(binary.modifications),
        "binary_quantification_count": len(binary.quantification),
    }
    for key, value in updates.items():
        if value is not None:
            out[key] = value
    return out


def _best_bottom_up_identification(records: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
    if not records:
        return None
    return min(records, key=lambda item: (_bottom_up_q_value(item) is None, _bottom_up_q_value(item) or 0.0))


def _best_bottom_up_q_value(records: tuple[dict[str, Any], ...]) -> float | None:
    best = _best_bottom_up_identification(records)
    return _bottom_up_q_value(best) if best is not None else None


def _bottom_up_q_value(record: dict[str, Any] | None) -> float | None:
    if record is None:
        return None
    typed = _json_object(record.get("typed_fields"))
    try:
        return float(typed.get("q_value")) if typed.get("q_value") is not None else None
    except (TypeError, ValueError):
        return None


def _joined_values(records: tuple[dict[str, Any], ...], field_name: str) -> str | None:
    values = [
        str(item.get(field_name)).strip()
        for item in records
        if item.get(field_name) is not None and str(item.get(field_name)).strip()
    ]
    unique = list(dict.fromkeys(values))
    return ";".join(unique) if unique else None


def _first_list_value(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else None


def _seconds_to_minutes(value: Any) -> float | None:
    try:
        return float(value) / 60.0 if value is not None else None
    except (TypeError, ValueError):
        return None


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def get_peptide_detail(session: Session, dataset: dict[str, Any], peptide_id: int) -> BuPeptideDetailOut | None:
    row = session.execute(
        text(
            """
            SELECT peptide_id
            FROM peptides
            WHERE dataset_id = :dataset_id AND peptide_id = :peptide_id
            """
        ),
        {"dataset_id": int(dataset["dataset_id"]), "peptide_id": peptide_id},
    ).mappings().one_or_none()
    if row is None:
        return None

    item_rows = session.execute(
        text(
            """
            SELECT
                p.peptide_id AS id,
                p.sequence,
                p.length,
                p.theoretical_mass,
                p.missed_cleavages,
                count(im.match_id) AS match_count,
                count(DISTINCT prm.protein_id) AS protein_count,
                min(im.q_value) AS best_q_value,
                (array_agg(im.precursor_mz ORDER BY im.q_value ASC NULLS LAST))[1] AS best_precursor_mz,
                (array_agg(im.precursor_charge ORDER BY im.q_value ASC NULLS LAST))[1] AS best_charge,
                (array_agg(im.match_id ORDER BY im.q_value ASC NULLS LAST))[1] AS best_match_id,
                string_agg(DISTINCT jsonb_extract_path_text(im.extra_metadata, 'protein_group'), ';') AS protein_groups,
                string_agg(DISTINCT jsonb_extract_path_text(im.extra_metadata, 'genes'), ';') AS genes,
                (array_agg(im.modified_sequence ORDER BY im.q_value ASC NULLS LAST))[1] AS example_modified,
                p.extra_metadata
            FROM peptides p
            LEFT JOIN identification_matches im
              ON im.dataset_id = p.dataset_id
             AND im.entity_type = 'PEPTIDE'
             AND im.entity_id = p.peptide_id
             AND im.is_decoy_match = false
            LEFT JOIN protein_relation_mapping prm
              ON prm.dataset_id = p.dataset_id
             AND prm.entity_type = 'PEPTIDE'
             AND prm.entity_id = p.peptide_id
            WHERE p.dataset_id = :dataset_id AND p.peptide_id = :peptide_id
            GROUP BY p.peptide_id
            """
        ),
        {"dataset_id": int(dataset["dataset_id"]), "peptide_id": peptide_id},
    ).mappings().one()
    base = BuPeptideListItemOut(**{k: item_rows[k] for k in BuPeptideListItemOut.model_fields})

    protein_rows = session.execute(
        text(
            """
            SELECT
                p.protein_id,
                p.accession,
                p.gene_name,
                jsonb_extract_path_text(p.extra_metadata, 'protein_group') AS protein_group,
                prm.is_unique
            FROM protein_relation_mapping prm
            JOIN proteins p
              ON p.dataset_id = prm.dataset_id
             AND p.protein_id = prm.protein_id
            WHERE prm.dataset_id = :dataset_id
              AND prm.entity_type = 'PEPTIDE'
              AND prm.entity_id = :peptide_id
            ORDER BY p.protein_id
            """
        ),
        {"dataset_id": int(dataset["dataset_id"]), "peptide_id": peptide_id},
    ).mappings().all()
    match_rows = session.execute(
        text(
            """
            SELECT
                im.match_id AS id,
                im.run_id,
                r.file_name AS run_name,
                im.precursor_mz,
                im.precursor_charge,
                im.retention_time,
                im.q_value,
                im.intensity
            FROM identification_matches im
            JOIN runs r ON r.dataset_id = im.dataset_id AND r.run_id = im.run_id
            WHERE im.dataset_id = :dataset_id
              AND im.entity_type = 'PEPTIDE'
              AND im.entity_id = :peptide_id
              AND im.is_decoy_match = false
            ORDER BY im.q_value ASC NULLS LAST, im.match_id ASC
            LIMIT 20
            """
        ),
        {"dataset_id": int(dataset["dataset_id"]), "peptide_id": peptide_id},
    ).mappings().all()
    total_matches = int(
        session.scalar(
            text(
                """
                SELECT count(*)
                FROM identification_matches
                WHERE dataset_id = :dataset_id
                  AND entity_type = 'PEPTIDE'
                  AND entity_id = :peptide_id
                  AND is_decoy_match = false
                """
            ),
            {"dataset_id": int(dataset["dataset_id"]), "peptide_id": peptide_id},
        )
        or 0
    )
    binary = (
        get_binary_bottom_up_peptide(session, int(dataset["dataset_id"]), str(item_rows.get("sequence") or ""))
        if _use_binary_entities(session, int(dataset["dataset_id"]))
        else None
    )
    base_payload = base.model_dump()
    extra_metadata = _json_object(item_rows.get("extra_metadata"))
    if binary is not None:
        base_payload = _binary_peptide_list_payload(base_payload, binary)
        extra_metadata = _binary_peptide_metadata(extra_metadata, binary)
    return BuPeptideDetailOut(
        **base_payload,
        proteins=[BuPeptideProteinRef(**dict(row)) for row in protein_rows],
        matches_summary=BuPeptideMatchesSummary(
            total=total_matches,
            items=[BuPeptideMatchSummaryItem(**dict(row)) for row in match_rows],
        ),
        extra_metadata=extra_metadata,
    )
