"""Import DIA-NN 2.0 Bottom-Up DIA reports into the universal schema."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import typer
from rich.console import Console
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from app.bu.services.protein_sequence_backfill import backfill_protein_sequences_from_fasta
from app.ingest.bu.diann_parquet_reader import find_diann_report, inspect_report, iter_filtered_rows, sibling_file
from app.ingest.bu.field_mapping import (
    Q_VALUE_CUTOFF,
    as_float,
    as_int,
    match_extra_metadata,
    peptide_metadata,
    protein_metadata,
    split_protein_group,
    theoretical_mass_from_precursor,
)
from app.ingest.bu.protein_description_reader import ProteinDescription, read_protein_descriptions
from app.ingest.bu.run_discovery import BuRunFile, discover_bu_runs, match_diann_runs_to_files
from app.ingest.bu.stats_reader import read_stats_tsv
from app.ingest.universal_toppic_adapter import ProgressEvent
from app.pfmb import IndexReader
from app.pfmb.locator import detect_sidecar


console = Console()
app = typer.Typer(no_args_is_help=True, add_completion=False)
ProgressCallback = Callable[[ProgressEvent], None]

BATCH_SIZE = 5000
SOFTWARE = "DIA-NN_2.0"


@dataclass
class UniversalDiannImportStats:
    dataset_id: int
    run_id: int
    proteins: int = 0
    peptides: int = 0
    proteoforms: int = 0
    protein_relations: int = 0
    matches: int = 0
    skipped_matches: int = 0


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _emit(callback: ProgressCallback | None, event: ProgressEvent) -> None:
    if callback is not None:
        try:
            callback(event)
        except Exception:  # noqa: BLE001
            pass


def _relative_or_abs(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


@app.command()
def ingest(
    root: Path = typer.Option(..., "--root", "-r", help="DIA-NN ingest root."),
    slug: str = typer.Option(..., "--slug", "-s", help="Unique dataset slug."),
    name: str = typer.Option(..., "--name", "-n", help="Human-readable dataset name."),
    database_url: str | None = typer.Option(None, "--database-url"),
    q_value_max: float = typer.Option(Q_VALUE_CUTOFF, "--q-value-max"),
    replace: bool = typer.Option(False, "--replace"),
    pfmb_sidecar_dir: Path | None = typer.Option(
        None,
        "--pfmb-sidecar-dir",
        help="Directory containing the PFMB sidecar (results.pfmb + index.json).",
    ),
) -> None:
    if database_url is None:
        from app.core.config import settings  # noqa: WPS433

        database_url = settings.database_url

    def _cli_progress(event: ProgressEvent) -> None:
        parts = [event.phase, f"{event.current}/{event.total}"]
        if event.message:
            parts.append(event.message)
        console.print(" | ".join(parts))

    stats = ingest_universal_diann(
        root=root,
        database_url=database_url,
        slug=slug,
        name=name,
        replace=replace,
        q_value_cutoff=q_value_max,
        pfmb_sidecar_dir=pfmb_sidecar_dir,
        progress_callback=_cli_progress,
    )
    console.print("[green]DIA-NN universal import done[/green]")
    console.print(f"dataset_id={stats.dataset_id} run_id={stats.run_id}")
    console.print(f"proteins={stats.proteins} peptides={stats.peptides} matches={stats.matches}")


def ingest_universal_diann(
    *,
    root: Path,
    database_url: str,
    slug: str,
    name: str,
    replace: bool = False,
    q_value_cutoff: float = Q_VALUE_CUTOFF,
    spectra_source: str | None = None,
    pfmb_sidecar_dir: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> UniversalDiannImportStats:
    """Run the DIA-NN Bottom-Up path import."""
    root = root.resolve()
    report_path = find_diann_report(root)
    report_info = inspect_report(report_path)
    stats_path = sibling_file(report_path, ".stats.tsv")
    descriptions_path = sibling_file(report_path, ".protein_description.tsv")
    refined_report_path = report_path.with_name("target_report.parquet")

    run_files = discover_bu_runs(root)
    if not run_files:
        raise ValueError(f"no mzML or Bruker .d runs found under {root}")
    run_file_by_diann = match_diann_runs_to_files(report_info.run_names, run_files)
    spectra_source = spectra_source or _spectra_source_from_runs(run_files)

    pfmb_sidecar = detect_sidecar(pfmb_sidecar_dir) if pfmb_sidecar_dir else None
    index_reader = IndexReader(pfmb_sidecar["index_path"]) if pfmb_sidecar else None
    if pfmb_sidecar_dir and pfmb_sidecar is None:
        raise FileNotFoundError(
            f"--pfmb-sidecar-dir given but results.pfmb + index.json not found under {pfmb_sidecar_dir}"
        )

    _emit(progress_callback, ProgressEvent("init", None, 0, 1, "初始化 Bottom-Up 数据集"))
    engine = create_engine(database_url, future=True)
    with engine.begin() as conn:
        if replace:
            conn.execute(text("DELETE FROM datasets WHERE slug = :slug"), {"slug": slug})

        dataset_id = _create_dataset(
            conn,
            root=root,
            slug=slug,
            name=name,
            report_path=report_path,
            refined_report_path=refined_report_path if refined_report_path.is_file() else None,
            q_value_cutoff=q_value_cutoff,
            spectra_source=spectra_source,
            stats_rows=read_stats_tsv(stats_path),
            parquet_total_rows=report_info.total_rows,
            pfmb_sidecar=pfmb_sidecar,
        )
        _emit(progress_callback, ProgressEvent("init", None, 1, 1, "数据集记录已创建"))

        run_id_by_path = _insert_runs(conn, dataset_id=dataset_id, run_files=run_files)
        run_id_by_diann = {
            run_name: run_id_by_path[str(run_file.file_path.resolve())]
            for run_name, run_file in run_file_by_diann.items()
        }
        first_run_id = next(iter(run_id_by_path.values()))
        _emit(progress_callback, ProgressEvent("runs", None, len(run_files), len(run_files), "谱图文件已登记"))

        description_by_accession = read_protein_descriptions(descriptions_path)
        rows = list(iter_filtered_rows(report_path, q_value_cutoff=q_value_cutoff))
        imported_total = len(rows)

        proteins, peptides, relations, match_rows = _collect_entities_and_matches(
            rows,
            dataset_id=dataset_id,
            run_id_by_diann=run_id_by_diann,
            description_by_accession=description_by_accession,
            index_reader=index_reader,
        )
        _emit(progress_callback, ProgressEvent("proteins", None, 0, max(len(proteins), 1), "导入蛋白"))
        protein_id_by_accession = _insert_proteins(
            conn,
            dataset_id=dataset_id,
            proteins=proteins,
            descriptions=description_by_accession,
        )
        sequence_backfill_stats = backfill_protein_sequences_from_fasta(conn, dataset_id=dataset_id, source_root=root)
        _emit(progress_callback, ProgressEvent("proteins", None, len(proteins), max(len(proteins), 1), "蛋白完成"))

        _emit(progress_callback, ProgressEvent("peptides", None, 0, max(len(peptides), 1), "导入肽段"))
        peptide_id_by_sequence = _insert_peptides(conn, dataset_id=dataset_id, peptides=peptides)
        _emit(progress_callback, ProgressEvent("peptides", None, len(peptides), max(len(peptides), 1), "肽段完成"))

        _emit(progress_callback, ProgressEvent("matches", None, 0, max(imported_total, 1), "导入鉴定"))
        _insert_matches(
            conn,
            dataset_id=dataset_id,
            match_rows=match_rows,
            peptide_id_by_sequence=peptide_id_by_sequence,
            progress_callback=progress_callback,
            imported_total=imported_total,
        )

        relation_count = _insert_relations(
            conn,
            dataset_id=dataset_id,
            relations=relations,
            protein_id_by_accession=protein_id_by_accession,
            peptide_id_by_sequence=peptide_id_by_sequence,
        )

        _emit(progress_callback, ProgressEvent("finalize", None, 0, 1, "收尾"))
        conn.execute(
            text(
                """
                UPDATE datasets
                SET
                    status = 'READY',
                    extra_metadata = extra_metadata || CAST(:extra_patch AS jsonb)
                WHERE dataset_id = :dataset_id
                """
            ),
            {
                "dataset_id": dataset_id,
                "extra_patch": _json(
                    {
                        "import_stats": {
                            "parquet_total_rows": report_info.total_rows,
                            "imported_matches": imported_total,
                            "unique_peptides": len(peptides),
                            "unique_proteins": len(proteins),
                            "protein_relations": relation_count,
                            "sequence_backfill": sequence_backfill_stats,
                        }
                    }
                ),
            },
        )
        conn.execute(text("UPDATE runs SET status = 'READY' WHERE dataset_id = :dataset_id"), {"dataset_id": dataset_id})
        _emit(progress_callback, ProgressEvent("finalize", None, 1, 1, "导入完成"))

        return UniversalDiannImportStats(
            dataset_id=dataset_id,
            run_id=first_run_id,
            proteins=len(proteins),
            peptides=len(peptides),
            proteoforms=0,
            protein_relations=relation_count,
            matches=imported_total,
            skipped_matches=max(report_info.total_rows - imported_total, 0),
        )


def _spectra_source_from_runs(run_files: list[BuRunFile]) -> str:
    formats = {r.raw_format for r in run_files}
    if formats == {"mzml"}:
        return "mzml_memory"
    if formats == {"bruker_d"}:
        return "tdf_memory"
    return "mixed"


def _create_dataset(
    conn: Connection,
    *,
    root: Path,
    slug: str,
    name: str,
    report_path: Path,
    refined_report_path: Path | None,
    q_value_cutoff: float,
    spectra_source: str,
    stats_rows: list[dict[str, Any]],
    parquet_total_rows: int,
    pfmb_sidecar: dict[str, str] | None = None,
) -> int:
    caps = {
        "spectra_source": spectra_source,
        "has_ms1": True,
        "has_ms2": True,
        "has_ms2_pfmb": pfmb_sidecar is not None,
        "has_im": spectra_source in {"mixed", "tdf_memory"},
        "has_dia_windows": True,
        "analysis_shape": "bottom_up_dia",
        "import_mode": "diann_parquet",
        "entity_types": ["PEPTIDE"],
        "list_routes": ["proteins", "peptides", "matches"],
    }
    extra = {
        "q_value_cutoff": q_value_cutoff,
        "parquet_path": _relative_or_abs(report_path, root),
        "refined_report_path": _relative_or_abs(refined_report_path, root) if refined_report_path else None,
        "stats": stats_rows,
        "import_stats": {"parquet_total_rows": parquet_total_rows},
    }
    if pfmb_sidecar is not None:
        extra["ms2_annotation"] = pfmb_sidecar
    row = conn.execute(
        text(
            """
            INSERT INTO datasets (
                dataset_name, slug, analysis_mode, source_software,
                source_root, status, description, capabilities, extra_metadata
            )
            VALUES (
                :name, :slug, 'BOTTOM_UP', :software,
                :source_root, 'IMPORTED',
                'DIA-NN 2.0 Bottom-Up DIA dataset imported by universal adapter',
                CAST(:capabilities AS jsonb), CAST(:extra_metadata AS jsonb)
            )
            RETURNING dataset_id
            """
        ),
        {
            "name": name,
            "slug": slug,
            "software": SOFTWARE,
            "source_root": str(root),
            "capabilities": _json(caps),
            "extra_metadata": _json(extra),
        },
    ).one()
    return int(row.dataset_id)


def _insert_runs(conn: Connection, *, dataset_id: int, run_files: list[BuRunFile]) -> dict[str, int]:
    out: dict[str, int] = {}
    for run_file in run_files:
        metadata = {
            "raw_format": run_file.raw_format,
            "diann_run_name": run_file.diann_run_name,
        }
        if run_file.raw_format == "mzml":
            metadata["mzml_file_path"] = str(run_file.file_path)
        if run_file.raw_format == "bruker_d":
            metadata["tdf_path"] = str(run_file.file_path)
        row = conn.execute(
            text(
                """
                INSERT INTO runs (
                    dataset_id, file_path, file_name,
                    analysis_mode, software, status, run_metadata
                )
                VALUES (
                    :dataset_id, :file_path, :file_name,
                    'BOTTOM_UP', :software, 'IMPORTED', CAST(:run_metadata AS jsonb)
                )
                RETURNING run_id
                """
            ),
            {
                "dataset_id": dataset_id,
                "file_path": str(run_file.file_path),
                "file_name": run_file.file_name,
                "software": SOFTWARE,
                "run_metadata": _json(metadata),
            },
        ).one()
        out[str(run_file.file_path.resolve())] = int(row.run_id)
    return out


def _collect_entities_and_matches(
    rows: list[dict[str, Any]],
    *,
    dataset_id: int,
    run_id_by_diann: dict[str, int],
    description_by_accession: dict[str, ProteinDescription],
    index_reader: IndexReader | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], set[tuple[str, str]], list[dict[str, Any]]]:
    proteins: dict[str, dict[str, Any]] = {}
    peptides: dict[str, dict[str, Any]] = {}
    relations: set[tuple[str, str]] = set()
    matches: list[dict[str, Any]] = []

    for row in rows:
        sequence = str(row.get("Stripped.Sequence") or "").strip()
        if not sequence:
            continue
        peptides.setdefault(
            sequence,
            {
                "sequence": sequence,
                "theoretical_mass": theoretical_mass_from_precursor(row.get("Precursor.Mz"), row.get("Precursor.Charge")),
                "length": len(sequence),
                "extra_metadata": peptide_metadata(row),
            },
        )

        accessions = split_protein_group(row.get("Protein.Group"))
        for accession in accessions:
            desc = description_by_accession.get(accession)
            proteins.setdefault(
                accession,
                {
                    "accession": accession,
                    "gene_name": desc.gene if desc and desc.gene else (str(row.get("Genes") or "").split(";")[0] or None),
                    "description": desc.description if desc and desc.description else None,
                    "base_sequence": desc.sequence if desc else None,
                    "is_decoy": False,
                    "extra_metadata": protein_metadata(row, accession=accession),
                },
            )
            relations.add((accession, sequence))

        run_name = str(row.get("Run") or "")
        run_id = run_id_by_diann.get(run_name)
        if run_id is None:
            raise ValueError(f"no run mapping for DIA-NN Run value: {run_name}")
        retention_time = as_float(row.get("RT"))
        precursor_charge = as_int(row.get("Precursor.Charge"))
        extra = match_extra_metadata(row)
        pfmb_block = _pfmb_match_block(index_reader, sequence, precursor_charge, retention_time)
        if pfmb_block is not None:
            extra["pfmb"] = pfmb_block
        matches.append(
            {
                "dataset_id": dataset_id,
                "run_id": run_id,
                "sequence": sequence,
                "scan_number": -1,
                "retention_time": retention_time,
                "modified_sequence": row.get("Modified.Sequence"),
                "experimental_mass": theoretical_mass_from_precursor(row.get("Precursor.Mz"), row.get("Precursor.Charge")),
                "precursor_mz": as_float(row.get("Precursor.Mz")),
                "precursor_charge": precursor_charge,
                "intensity": as_float(row.get("Precursor.Quantity")) or as_float(row.get("Ms2.Area")),
                "score": as_float(row.get("Global.Q.Value")) or as_float(row.get("Q.Value")),
                "q_value": as_float(row.get("Q.Value")),
                "pep": as_float(row.get("PEP")),
                "extra_metadata": extra,
            }
        )
    return proteins, peptides, relations, matches


def _pfmb_match_block(
    index_reader: IndexReader | None,
    sequence: str,
    charge: int | None,
    retention_time_minutes: float | None,
) -> dict[str, Any] | None:
    """Resolve a match to its PFMB source_row and bake its RT slots.

    DIA-NN ``RT`` is in minutes; ``index.json`` ``slot_rt`` is in seconds, so the
    RT used for duplicate disambiguation is converted with ``* 60``.
    """

    if index_reader is None or not sequence or charge is None:
        return None
    rt_seconds = retention_time_minutes * 60.0 if retention_time_minutes is not None else None
    source_row = index_reader.resolve_source_row(sequence, charge, rt_seconds)
    if source_row is None:
        return None
    slots = index_reader.get_slots(source_row)
    return {
        "source_row": source_row,
        "apex_slot": slots[0].apex_slot if slots else None,
        "slots": [
            {"prsm_index": slot.prsm_index, "slot_index": slot.slot_index, "slot_rt": slot.slot_rt}
            for slot in slots
        ],
    }


def _insert_proteins(
    conn: Connection,
    *,
    dataset_id: int,
    proteins: dict[str, dict[str, Any]],
    descriptions: dict[str, ProteinDescription],
) -> dict[str, int]:
    out: dict[str, int] = {}
    for idx, (accession, data) in enumerate(proteins.items(), start=1):
        desc = descriptions.get(accession)
        row = conn.execute(
            text(
                """
                INSERT INTO proteins (
                    dataset_id, accession, gene_name, description,
                    base_sequence, is_decoy, extra_metadata
                )
                VALUES (
                    :dataset_id, :accession, :gene_name, :description,
                    :base_sequence, :is_decoy, CAST(:extra_metadata AS jsonb)
                )
                RETURNING protein_id
                """
            ),
            {
                "dataset_id": dataset_id,
                "accession": accession,
                "gene_name": data.get("gene_name"),
                "description": data.get("description") or (desc.description if desc else None),
                "base_sequence": data.get("base_sequence") or (desc.sequence if desc else None),
                "is_decoy": bool(data.get("is_decoy")),
                "extra_metadata": _json(data.get("extra_metadata") or {}),
            },
        ).one()
        out[accession] = int(row.protein_id)
        if idx % BATCH_SIZE == 0:
            pass
    return out


def _insert_peptides(conn: Connection, *, dataset_id: int, peptides: dict[str, dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for sequence, data in peptides.items():
        row = conn.execute(
            text(
                """
                INSERT INTO peptides (
                    dataset_id, sequence, theoretical_mass, length, extra_metadata
                )
                VALUES (
                    :dataset_id, :sequence, :theoretical_mass, :length, CAST(:extra_metadata AS jsonb)
                )
                RETURNING peptide_id
                """
            ),
            {
                "dataset_id": dataset_id,
                "sequence": sequence,
                "theoretical_mass": data.get("theoretical_mass"),
                "length": data.get("length"),
                "extra_metadata": _json(data.get("extra_metadata") or {}),
            },
        ).one()
        out[sequence] = int(row.peptide_id)
    return out


_MATCH_INSERT_SQL = text(
    """
    INSERT INTO identification_matches (
        dataset_id, run_id, scan_number, spectrum_native_id,
        retention_time, ms_level, entity_type, entity_id,
        modified_sequence, experimental_mass, precursor_mz, precursor_charge,
        intensity, score, e_value, q_value, pep,
        is_decoy_match, search_engine,
        detail_path, detail_cache, extra_metadata
    )
    VALUES (
        :dataset_id, :run_id, :scan_number, NULL,
        :retention_time, 2, 'PEPTIDE', :entity_id,
        :modified_sequence, :experimental_mass, :precursor_mz, :precursor_charge,
        :intensity, :score, NULL, :q_value, :pep,
        FALSE, 'DIA-NN',
        NULL, NULL, CAST(:extra_metadata AS jsonb)
    )
    """
)


def _insert_matches(
    conn: Connection,
    *,
    dataset_id: int,
    match_rows: list[dict[str, Any]],
    peptide_id_by_sequence: dict[str, int],
    progress_callback: ProgressCallback | None,
    imported_total: int,
) -> None:
    batch: list[dict[str, Any]] = []
    done = 0
    for row in match_rows:
        entity_id = peptide_id_by_sequence.get(row["sequence"])
        if entity_id is None:
            continue
        batch.append(
            {
                "dataset_id": dataset_id,
                "run_id": row["run_id"],
                "scan_number": row["scan_number"],
                "retention_time": row["retention_time"],
                "entity_id": entity_id,
                "modified_sequence": row["modified_sequence"],
                "experimental_mass": row["experimental_mass"],
                "precursor_mz": row["precursor_mz"],
                "precursor_charge": row["precursor_charge"],
                "intensity": row["intensity"],
                "score": row["score"],
                "q_value": row["q_value"],
                "pep": row["pep"],
                "extra_metadata": _json(row["extra_metadata"]),
            }
        )
        if len(batch) >= BATCH_SIZE:
            conn.execute(_MATCH_INSERT_SQL, batch)
            done += len(batch)
            batch.clear()
            _emit(
                progress_callback,
                ProgressEvent("matches", None, done, max(imported_total, 1), f"导入鉴定 {done}/{imported_total}"),
            )
    if batch:
        conn.execute(_MATCH_INSERT_SQL, batch)
        done += len(batch)
    _emit(
        progress_callback,
        ProgressEvent("matches", None, done, max(imported_total, 1), f"导入鉴定 {done}/{imported_total}"),
    )


def _insert_relations(
    conn: Connection,
    *,
    dataset_id: int,
    relations: set[tuple[str, str]],
    protein_id_by_accession: dict[str, int],
    peptide_id_by_sequence: dict[str, int],
) -> int:
    rows: list[dict[str, Any]] = []
    for accession, sequence in relations:
        protein_id = protein_id_by_accession.get(accession)
        peptide_id = peptide_id_by_sequence.get(sequence)
        if protein_id is None or peptide_id is None:
            continue
        rows.append(
            {
                "dataset_id": dataset_id,
                "protein_id": protein_id,
                "entity_id": peptide_id,
                "extra_metadata": _json({"source": "diann_report"}),
            }
        )
    if rows:
        conn.execute(
            text(
                """
                INSERT INTO protein_relation_mapping (
                    dataset_id, protein_id, entity_type, entity_id,
                    start_position, end_position, is_unique, extra_metadata
                )
                VALUES (
                    :dataset_id, :protein_id, 'PEPTIDE', :entity_id,
                    NULL, NULL, FALSE, CAST(:extra_metadata AS jsonb)
                )
                """
            ),
            rows,
        )
    return len(rows)


if __name__ == "__main__":
    app()
