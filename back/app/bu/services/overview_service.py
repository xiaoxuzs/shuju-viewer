"""Overview aggregation for Bottom-Up datasets."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas import BuOverviewOut, BuOverviewCounts, BuQcBlock, BuRunSummary


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


def get_overview(session: Session, dataset: dict[str, Any]) -> BuOverviewOut:
    dataset_id = int(dataset["dataset_id"])
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
        counts=BuOverviewCounts(**{k: int(counts_row[k] or 0) for k in counts_row.keys()}),
        qc=BuQcBlock(by_run=qc_rows, aggregated=_aggregate_qc(qc_rows)),
        runs=_runs(session, dataset_id),
        capabilities=_json_object(dataset.get("capabilities")),
        import_stats=_json_object(extra.get("import_stats")),
        created_at=dataset["created_at"],
    )

