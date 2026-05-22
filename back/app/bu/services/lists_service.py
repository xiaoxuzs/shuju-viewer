"""Bottom-Up list and summary queries."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
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
    return Page[BuProteinListItemOut](
        items=[BuProteinListItemOut(**dict(row)) for row in rows],
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
    return Page[BuPeptideListItemOut](
        items=[BuPeptideListItemOut(**dict(row)) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_match_detail(
    session: Session,
    dataset: dict[str, Any],
    match: dict[str, Any],
) -> BuMatchDetailOut:
    meta = _json_object(match.get("extra_metadata"))
    run_meta = _json_object(match.get("run_metadata"))
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
    list_item = BuMatchListItemOut(
        id=int(match["match_id"]),
        run_id=int(match["run_id"]),
        run_name=str(match["run_name"] or ""),
        peptide_id=int(match["entity_id"]),
        sequence=str(match["sequence"] or ""),
        modified_sequence=match.get("modified_sequence"),
        precursor_mz=match.get("precursor_mz"),
        precursor_charge=match.get("precursor_charge"),
        retention_time=match.get("retention_time"),
        experimental_mass=match.get("experimental_mass"),
        q_value=match.get("q_value"),
        score=match.get("score"),
        intensity=match.get("intensity"),
        is_decoy_match=bool(match.get("is_decoy_match")),
        scan_number=int(match["scan_number"]),
        protein_group=protein_group,
        protein_accessions=_protein_accessions(protein_group),
        genes=meta.get("genes"),
        search_engine=match.get("search_engine"),
    )
    return BuMatchDetailOut(
        **list_item.model_dump(),
        spectrum_native_id=match.get("spectrum_native_id"),
        ms_level=int(match.get("ms_level") or 2),
        run=BuRunDetail(
            run_id=int(match["run_id"]),
            file_name=str(match["run_name"] or ""),
            raw_format=run_meta.get("raw_format"),
            file_path=str(match["file_path"] or ""),
            diann_run_name=run_meta.get("diann_run_name"),
        ),
        rt_window=BuRtWindow(
            rt_start=meta.get("rt_start"),
            rt_stop=meta.get("rt_stop"),
            rt_apex=match.get("retention_time"),
        ),
        proteins=[BuProteinMini(**dict(row)) for row in proteins],
        diann={
            "precursor_id": meta.get("precursor_id"),
            "lib_qvalue": meta.get("lib_qvalue"),
            "mass_accuracy": meta.get("mass_evidence"),
            "ms2_scan": meta.get("ms2_scan"),
            "resolved_scan": meta.get("resolved_scan"),
        },
        spectrum_links={
            "xic": f"{links_base}/xic",
            "ms2": f"{links_base}/spectrum/ms2",
            "ms1": f"{links_base}/spectrum/ms1",
            "mobility_slice": f"{links_base}/mobility-slice" if run_meta.get("raw_format") == "bruker_d" else None,
        },
        extra_metadata=meta,
    )


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
    return BuPeptideDetailOut(
        **base.model_dump(),
        proteins=[BuPeptideProteinRef(**dict(row)) for row in protein_rows],
        matches_summary=BuPeptideMatchesSummary(
            total=total_matches,
            items=[BuPeptideMatchSummaryItem(**dict(row)) for row in match_rows],
        ),
        extra_metadata=_json_object(item_rows.get("extra_metadata")),
    )
