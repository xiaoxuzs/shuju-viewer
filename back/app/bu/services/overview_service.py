"""Overview aggregation for Bottom-Up datasets."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.schemas import BuOverviewOut, BuOverviewCounts, BuQcBlock, BuRtMzHeatmapOut, BuRunSummary
from app.zp_runtime import ZpBottomUpOverview, get_binary_bottom_up_overview


def _json_object(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _run_meta(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _snake_key(value: str) -> str:
    return value.strip().replace(".", "_").replace(" ", "_").replace("-", "_").lower()


def _qc_rows(extra_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    rows = extra_metadata.get("stats")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append({_snake_key(str(k)): v for k, v in row.items()})
    return out


def _aggregate_qc(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    # v1 uses the first stats row as the main run summary; this matches the
    # single-match-run DIA-NN sample and keeps multi-run semantics explicit.
    return dict(rows[0])


def _supports_identifications(dataset: dict[str, Any]) -> bool:
    capabilities = _json_object(dataset.get("capabilities"))
    if capabilities.get("has_identifications") is False:
        return False
    return str(capabilities.get("analysis_shape") or "").lower() not in {
        "mzml_only",
        "raw_mzml_only",
        "zp_spectra_only",
    }


def _runs(session: Session, dataset_id: int) -> list[BuRunSummary]:
    rows = session.execute(
        text(
            """
            SELECT
                r.run_id,
                r.file_name,
                r.run_metadata,
                count(im.match_id) AS match_count
            FROM runs r
            LEFT JOIN identification_matches im
              ON im.dataset_id = r.dataset_id
             AND im.run_id = r.run_id
            WHERE r.dataset_id = :dataset_id
            GROUP BY r.run_id, r.file_name, r.run_metadata
            ORDER BY r.run_id
            """
        ),
        {"dataset_id": dataset_id},
    ).mappings().all()
    out: list[BuRunSummary] = []
    for row in rows:
        meta = _run_meta(row.get("run_metadata"))
        raw_format = meta.get("raw_format")
        out.append(
            BuRunSummary(
                run_id=int(row["run_id"]),
                file_name=str(row["file_name"] or ""),
                raw_format=raw_format,
                diann_run_name=meta.get("diann_run_name"),
                match_count=int(row["match_count"] or 0),
                has_im=(raw_format == "bruker_d"),
            )
        )
    return out


def _binary_runs(
    session: Session,
    dataset_id: int,
    *,
    match_count: int,
) -> list[BuRunSummary]:
    rows = session.execute(
        text(
            """
            SELECT run_id, file_name, run_metadata
            FROM runs
            WHERE dataset_id = :dataset_id
            ORDER BY run_id
            """
        ),
        {"dataset_id": dataset_id},
    ).mappings().all()
    out: list[BuRunSummary] = []
    single_run_match_count = match_count if len(rows) == 1 else None
    for row in rows:
        meta = _run_meta(row.get("run_metadata"))
        raw_format = meta.get("raw_format")
        out.append(
            BuRunSummary(
                run_id=int(row["run_id"]),
                file_name=str(row["file_name"] or ""),
                raw_format=raw_format,
                diann_run_name=meta.get("diann_run_name"),
                match_count=single_run_match_count,
                has_im=(raw_format == "bruker_d"),
            )
        )
    return out


def get_overview(session: Session, dataset: dict[str, Any]) -> BuOverviewOut:
    dataset_id = int(dataset["dataset_id"])
    supports_identifications = _supports_identifications(dataset)
    try:
        counts_row = session.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM identification_matches im
                      WHERE im.dataset_id = :dataset_id AND im.entity_type = 'PEPTIDE') AS matches,
                    (SELECT count(*) FROM peptides p WHERE p.dataset_id = :dataset_id) AS peptides,
                    (SELECT count(*) FROM proteins p
                      WHERE p.dataset_id = :dataset_id AND p.is_decoy = false) AS proteins,
                    (SELECT count(DISTINCT jsonb_extract_path_text(p.extra_metadata, 'protein_group'))
                       FROM proteins p
                      WHERE p.dataset_id = :dataset_id
                        AND jsonb_extract_path_text(p.extra_metadata, 'protein_group') IS NOT NULL) AS protein_groups,
                    (SELECT count(*) FROM runs r WHERE r.dataset_id = :dataset_id) AS runs,
                    (SELECT count(*) FROM identification_matches im
                      WHERE im.dataset_id = :dataset_id AND im.is_decoy_match = true) AS decoy_matches
                """
            ),
            {"dataset_id": dataset_id},
        ).mappings().one()
    except SQLAlchemyError:
        if supports_identifications:
            binary = get_binary_bottom_up_overview(session, dataset_id)
            if binary is not None:
                return _binary_overview(session, dataset, binary)
        raise
    counts = BuOverviewCounts(**{k: int(counts_row[k] or 0) for k in counts_row.keys()})
    if counts.matches == 0 and supports_identifications:
        binary = get_binary_bottom_up_overview(session, dataset_id)
        if binary is not None:
            return _binary_overview(session, dataset, binary)

    extra = _json_object(dataset.get("extra_metadata"))
    qc_rows = _qc_rows(extra)
    return BuOverviewOut(
        dataset_id=dataset_id,
        slug=str(dataset["slug"]),
        name=str(dataset["dataset_name"]),
        source_software=dataset.get("source_software"),
        status=str(dataset["status"]),
        source_root=str(dataset["source_root"]),
        q_value_cutoff=extra.get("q_value_cutoff"),
        counts=counts,
        qc=BuQcBlock(by_run=qc_rows, aggregated=_aggregate_qc(qc_rows)),
        runs=_runs(session, dataset_id),
        capabilities=_json_object(dataset.get("capabilities")),
        import_stats=_json_object(extra.get("import_stats")),
        created_at=dataset["created_at"],
    )


def _binary_overview(
    session: Session,
    dataset: dict[str, Any],
    binary: ZpBottomUpOverview,
) -> BuOverviewOut:
    dataset_id = int(dataset["dataset_id"])
    extra = _json_object(dataset.get("extra_metadata"))
    summary = binary.summary
    metadata = binary.metadata
    matches = _int_count(summary.get("identification"))
    runs = _binary_runs(session, dataset_id, match_count=matches)
    qc_rows = _qc_rows(extra)
    capabilities = _json_object(dataset.get("capabilities"))
    capabilities["binary_layer"] = {
        "available": True,
        "identifications": True,
        "summary": True,
        "source_type": summary.get("source_type"),
        "adapter_flavor": summary.get("adapter_flavor"),
        "identification_kind": summary.get("identification_kind"),
        "fragment_support": summary.get("fragment_support"),
        "quantification": binary.quantification_summary,
    }
    selection = _json_object(metadata.get("selection_policy"))
    return BuOverviewOut(
        dataset_id=dataset_id,
        slug=str(dataset["slug"]),
        name=str(dataset["dataset_name"]),
        source_software=metadata.get("source_software") or dataset.get("source_software"),
        status=str(dataset["status"]),
        source_root=str(dataset["source_root"]),
        q_value_cutoff=selection.get("q_value_cutoff") or extra.get("q_value_cutoff"),
        counts=BuOverviewCounts(
            matches=matches,
            peptides=_int_count(summary.get("peptide")),
            proteins=_int_count(summary.get("protein")),
            protein_groups=_int_count(summary.get("protein_group")),
            runs=len(runs),
            decoy_matches=0,
        ),
        qc=BuQcBlock(by_run=qc_rows, aggregated=_aggregate_qc(qc_rows)),
        runs=runs,
        capabilities=capabilities,
        import_stats=_json_object(extra.get("import_stats")),
        created_at=dataset["created_at"],
    )


def _int_count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def get_rt_mz_heatmap(
    session: Session,
    dataset: dict[str, Any],
    *,
    run_id: int | None,
    q_max: float,
    bins_rt: int,
    bins_mz: int,
    decoy: bool,
) -> BuRtMzHeatmapOut:
    if bins_rt <= 0 or bins_mz <= 0:
        raise ValueError("RT-m/z heatmap bin counts must be positive")

    dataset_id = int(dataset["dataset_id"])
    clauses = [
        "dataset_id = :dataset_id",
        "entity_type = 'PEPTIDE'",
        "q_value <= :q_max",
        "retention_time IS NOT NULL",
        "precursor_mz IS NOT NULL",
    ]
    params: dict[str, Any] = {"dataset_id": dataset_id, "q_max": q_max}
    if run_id is not None:
        clauses.append("run_id = :run_id")
        params["run_id"] = run_id
    if not decoy:
        clauses.append("COALESCE(is_decoy_match, false) = false")

    where_sql = " AND ".join(clauses)
    bounds = session.execute(
        text(
            f"""
            SELECT
                min(retention_time) AS rt_min,
                max(retention_time) AS rt_max,
                min(precursor_mz) AS mz_min,
                max(precursor_mz) AS mz_max,
                count(*) AS total_points
            FROM identification_matches
            WHERE {where_sql}
            """
        ),
        params,
    ).mappings().one()
    total_points = int(bounds["total_points"] or 0)
    if total_points == 0:
        return BuRtMzHeatmapOut(run_id=run_id)

    rt_min = float(bounds["rt_min"])
    rt_max = float(bounds["rt_max"])
    mz_min = float(bounds["mz_min"])
    mz_max = float(bounds["mz_max"])
    if rt_min == rt_max:
        rt_max = rt_min + 1.0
    if mz_min == mz_max:
        mz_max = mz_min + 1.0

    aggregate_params = {
        **params,
        "rt_min": rt_min,
        "rt_max": rt_max,
        "mz_min": mz_min,
        "mz_max": mz_max,
        "bins_rt": bins_rt,
        "bins_mz": bins_mz,
    }
    # Viewer runs on PostgreSQL; width_bucket keeps raw identification rows in the database.
    rows = session.execute(
        text(
            f"""
            SELECT
                LEAST(
                    GREATEST(
                        width_bucket(
                            retention_time::double precision,
                            :rt_min,
                            :rt_max,
                            :bins_rt
                        ),
                        1
                    ),
                    :bins_rt
                ) - 1 AS rt_bin,
                LEAST(
                    GREATEST(
                        width_bucket(
                            precursor_mz::double precision,
                            :mz_min,
                            :mz_max,
                            :bins_mz
                        ),
                        1
                    ),
                    :bins_mz
                ) - 1 AS mz_bin,
                count(*) AS point_count
            FROM identification_matches
            WHERE {where_sql}
            GROUP BY rt_bin, mz_bin
            ORDER BY rt_bin, mz_bin
            """
        ),
        aggregate_params,
    ).mappings().all()
    return build_rt_mz_heatmap_from_bins(
        rows,
        rt_min=rt_min,
        rt_max=rt_max,
        mz_min=mz_min,
        mz_max=mz_max,
        bins_rt=bins_rt,
        bins_mz=bins_mz,
        total_points=total_points,
        run_id=run_id,
    )


def build_rt_mz_heatmap_from_bins(
    rows: list[dict[str, Any]],
    *,
    rt_min: float,
    rt_max: float,
    mz_min: float,
    mz_max: float,
    bins_rt: int,
    bins_mz: int,
    total_points: int,
    run_id: int | None,
) -> BuRtMzHeatmapOut:
    if len(rows) > bins_rt * bins_mz:
        raise RuntimeError("RT-m/z aggregate returned more rows than available bins")

    counts = [[0 for _ in range(bins_mz)] for _ in range(bins_rt)]
    max_count = 0
    aggregated_total = 0
    seen: set[tuple[int, int]] = set()
    for row in rows:
        rt_bin = int(row["rt_bin"])
        mz_bin = int(row["mz_bin"])
        point_count = int(row["point_count"])
        key = (rt_bin, mz_bin)
        if not 0 <= rt_bin < bins_rt or not 0 <= mz_bin < bins_mz or key in seen:
            raise RuntimeError("RT-m/z aggregate returned an invalid bin")
        seen.add(key)
        counts[rt_bin][mz_bin] = point_count
        aggregated_total += point_count
        max_count = max(max_count, point_count)
    if aggregated_total != total_points:
        raise RuntimeError("RT-m/z aggregate point count does not match bounds query")

    return BuRtMzHeatmapOut(
        rt_edges=_edges(rt_min, rt_max, bins_rt),
        mz_edges=_edges(mz_min, mz_max, bins_mz),
        counts=counts,
        max_count=max_count,
        total_points=total_points,
        run_id=run_id,
    )


def _edges(start: float, stop: float, bins: int) -> list[float]:
    width = (stop - start) / bins
    return [start + width * index for index in range(bins)] + [stop]
