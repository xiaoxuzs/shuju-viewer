"""Import TopPIC / TopFD output into the universal 7-table schema.

This adapter targets the manually-created Universal_Viewer database schema:

- datasets
- runs
- proteins
- peptides
- proteoforms
- identification_matches
- protein_relation_mapping

It intentionally does not import spectrum peak arrays. Spectrum files remain on
disk and are addressed later through runs.file_path plus scan/native spectrum ids.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from tqdm import tqdm

from app.ingest.utils import best_prsm, ensure_list, to_float, to_int
from app.services.js_parser import load_js_object


console = Console()
app = typer.Typer(no_args_is_help=True, add_completion=False)

CUTOFF_DIRS = {
    "prsm": "toppic_prsm_cutoff",
    "proteoform": "toppic_proteoform_cutoff",
}


@dataclass
class UniversalImportStats:
    dataset_id: int
    run_id: int
    proteins: int = 0
    proteoforms: int = 0
    protein_relations: int = 0
    matches: int = 0
    skipped_matches: int = 0


@app.command()
def ingest(
    root: Path = typer.Option(..., "--root", "-r", help="TopPIC / TopFD HTML output directory."),
    database_url: str = typer.Option(
        ...,
        "--database-url",
        help="SQLAlchemy database URL, e.g. postgresql+psycopg://postgres:postgres@localhost:5432/Universal_Viewer",
    ),
    slug: str = typer.Option("mz20160222ds_histone48", "--slug", "-s"),
    name: str = typer.Option("MZ20160222DS_histone48_html", "--name", "-n"),
    mode: str = typer.Option("fast", "--mode", help="Import mode: fast or full."),
    replace: bool = typer.Option(False, "--replace", help="Delete existing dataset with the same slug first."),
) -> None:
    """Import a TopPIC / TopFD dataset into the universal schema."""
    stats = ingest_universal_toppic(
        root=root,
        database_url=database_url,
        slug=slug,
        name=name,
        mode=mode,
        replace=replace,
    )
    console.print("[green]universal import done[/green]")
    console.print(f"  dataset_id={stats.dataset_id}  run_id={stats.run_id}")
    console.print(
        "  proteins={proteins}  proteoforms={proteoforms}  relations={relations}  "
        "matches={matches}  skipped_matches={skipped}".format(
            proteins=stats.proteins,
            proteoforms=stats.proteoforms,
            relations=stats.protein_relations,
            matches=stats.matches,
            skipped=stats.skipped_matches,
        )
    )


def ingest_universal_toppic(
    *,
    root: Path,
    database_url: str,
    slug: str,
    name: str,
    mode: str = "fast",
    replace: bool = False,
) -> UniversalImportStats:
    """Run the universal-schema TopPIC / TopFD import."""
    root = root.resolve()
    if not root.exists():
        raise FileNotFoundError(root)
    if mode not in {"fast", "full"}:
        raise ValueError("mode must be 'fast' or 'full'")

    engine = create_engine(database_url, future=True)
    with engine.begin() as conn:
        if replace:
            conn.execute(text("DELETE FROM datasets WHERE slug = :slug"), {"slug": slug})

        dataset_id = _create_dataset(conn, root=root, slug=slug, name=name)
        run_id = _create_run(conn, dataset_id=dataset_id, root=root)
        stats = UniversalImportStats(dataset_id=dataset_id, run_id=run_id)

        protein_by_source_seq: dict[int, int] = {}
        proteoform_by_source_key: dict[tuple[int, int], int] = {}
        relation_keys: set[tuple[int, str, int]] = set()
        fast_match_keys: set[tuple[str, int]] = set()

        for cutoff_kind, folder_name in CUTOFF_DIRS.items():
            cutoff_root = root / folder_name / "data_js"
            proteins_file = cutoff_root / "proteins.js"
            if not proteins_file.exists():
                console.print(f"[yellow]skip missing cutoff[/yellow] {cutoff_root}")
                continue

            _import_proteins_and_forms(
                conn,
                dataset_id=dataset_id,
                cutoff_kind=cutoff_kind,
                cutoff_root=cutoff_root,
                run_id=run_id,
                mode=mode,
                proteins_file=proteins_file,
                protein_by_source_seq=protein_by_source_seq,
                proteoform_by_source_key=proteoform_by_source_key,
                relation_keys=relation_keys,
                fast_match_keys=fast_match_keys,
                stats=stats,
            )
            if mode == "full":
                _import_prsm_matches(
                    conn,
                    dataset_id=dataset_id,
                    run_id=run_id,
                    cutoff_kind=cutoff_kind,
                    cutoff_root=cutoff_root,
                    proteoform_by_source_key=proteoform_by_source_key,
                    stats=stats,
                )

        conn.execute(
            text("UPDATE datasets SET status = 'READY' WHERE dataset_id = :dataset_id"),
            {"dataset_id": dataset_id},
        )
        conn.execute(
            text("UPDATE runs SET status = 'READY' WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
        return stats


def _create_dataset(conn: Connection, *, root: Path, slug: str, name: str) -> int:
    row = conn.execute(
        text(
            """
            INSERT INTO datasets (
                dataset_name,
                slug,
                analysis_mode,
                source_software,
                source_root,
                status,
                description,
                capabilities
            )
            VALUES (
                :name,
                :slug,
                'TOP_DOWN',
                'TopPIC_TopFD',
                :source_root,
                'IMPORTED',
                'TopPIC/TopFD top-down dataset imported by universal adapter',
                CAST(:capabilities AS jsonb)
            )
            RETURNING dataset_id
            """
        ),
        {
            "name": name,
            "slug": slug,
            "source_root": str(root),
            "capabilities": (
                '{"has_ms1": true, "has_ms2": true, "has_prsms": true, '
                '"has_proteoforms": true, "has_spectrum_files": true, '
                '"spectra_in_database": false}'
            ),
        },
    ).one()
    return int(row.dataset_id)


def _create_run(conn: Connection, *, dataset_id: int, root: Path) -> int:
    row = conn.execute(
        text(
            """
            INSERT INTO runs (
                dataset_id,
                file_path,
                file_name,
                analysis_mode,
                software,
                status
            )
            VALUES (
                :dataset_id,
                :file_path,
                :file_name,
                'TOP_DOWN',
                'TopPIC_TopFD',
                'IMPORTED'
            )
            RETURNING run_id
            """
        ),
        {
            "dataset_id": dataset_id,
            "file_path": str(root),
            "file_name": root.name,
        },
    ).one()
    return int(row.run_id)


def _import_proteins_and_forms(
    conn: Connection,
    *,
    dataset_id: int,
    cutoff_kind: str,
    cutoff_root: Path,
    run_id: int,
    mode: str,
    proteins_file: Path,
    protein_by_source_seq: dict[int, int],
    proteoform_by_source_key: dict[tuple[int, int], int],
    relation_keys: set[tuple[int, str, int]],
    fast_match_keys: set[tuple[str, int]],
    stats: UniversalImportStats,
) -> None:
    doc = load_js_object(proteins_file)
    protein_list = (
        doc.get("protein_list", {}).get("proteins", {}).get("protein")
        or doc.get("prsm_data", {}).get("protein_list", {}).get("proteins", {}).get("protein")
    )

    for protein_doc in ensure_list(protein_list or []):
        source_seq_id = to_int(protein_doc.get("sequence_id"))
        if source_seq_id is None:
            continue

        protein_id = protein_by_source_seq.get(source_seq_id)
        if protein_id is None:
            protein_id = _insert_protein(conn, dataset_id, protein_doc)
            protein_by_source_seq[source_seq_id] = protein_id
            stats.proteins += 1

        for form_doc in ensure_list(protein_doc.get("compatible_proteoform")):
            source_form_id = to_int(form_doc.get("proteoform_id"))
            if source_form_id is None:
                continue
            form_key = (source_seq_id, source_form_id)
            proteoform_id = proteoform_by_source_key.get(form_key)
            if proteoform_id is None:
                proteoform_id = _insert_proteoform(
                    conn,
                    dataset_id=dataset_id,
                    cutoff_kind=cutoff_kind,
                    source_seq_id=source_seq_id,
                    form_doc=form_doc,
                    fallback_sequence_name=protein_doc.get("sequence_name"),
                )
                proteoform_by_source_key[form_key] = proteoform_id
                stats.proteoforms += 1

            relation_key = (protein_id, "PROTEOFORM", proteoform_id)
            if relation_key not in relation_keys:
                _insert_relation(
                    conn,
                    dataset_id=dataset_id,
                    protein_id=protein_id,
                    proteoform_id=proteoform_id,
                    cutoff_kind=cutoff_kind,
                    source_seq_id=source_seq_id,
                    source_form_id=source_form_id,
                )
                relation_keys.add(relation_key)
                stats.protein_relations += 1

            if mode == "fast":
                _import_fast_prsm_summaries(
                    conn,
                    dataset_id=dataset_id,
                    run_id=run_id,
                    cutoff_kind=cutoff_kind,
                    cutoff_root=cutoff_root,
                    source_seq_id=source_seq_id,
                    source_form_id=source_form_id,
                    proteoform_id=proteoform_id,
                    sequence_name=str(form_doc.get("sequence_name") or protein_doc.get("sequence_name") or ""),
                    form_doc=form_doc,
                    fast_match_keys=fast_match_keys,
                    stats=stats,
                )


def _insert_protein(conn: Connection, dataset_id: int, protein_doc: dict[str, Any]) -> int:
    source_seq_id = to_int(protein_doc.get("sequence_id"))
    sequence_name = str(protein_doc.get("sequence_name") or f"sequence_{source_seq_id}")
    accession = _accession_from_sequence_name(sequence_name, source_seq_id)
    compat_list = ensure_list(protein_doc.get("compatible_proteoform"))
    prsm_total = 0
    protein_best_id: int | None = None
    protein_best_e: float | None = None
    for form_doc in compat_list:
        prsm_total += to_int(form_doc.get("prsm_number"), 0) or 0
        form_best_id, form_best_e = best_prsm(ensure_list(form_doc.get("prsm")))
        if form_best_id is not None and (
            protein_best_e is None or (form_best_e is not None and form_best_e < protein_best_e)
        ):
            protein_best_id = form_best_id
            protein_best_e = form_best_e

    row = conn.execute(
        text(
            """
            INSERT INTO proteins (
                dataset_id,
                accession,
                description,
                base_sequence,
                is_decoy,
                extra_metadata
            )
            VALUES (
                :dataset_id,
                :accession,
                :description,
                NULL,
                :is_decoy,
                CAST(:extra_metadata AS jsonb)
            )
            RETURNING protein_id
            """
        ),
        {
            "dataset_id": dataset_id,
            "accession": accession,
            "description": protein_doc.get("sequence_description"),
            "is_decoy": _looks_decoy(sequence_name, protein_doc.get("sequence_description")),
            "extra_metadata": _json_dumps(
                {
                    "source_sequence_id": source_seq_id,
                    "source_sequence_name": sequence_name,
                    "compatible_proteoform_number": to_int(
                        protein_doc.get("compatible_proteoform_number"),
                        len(compat_list),
                    ),
                    "prsm_number": prsm_total,
                    "best_prsm_id": protein_best_id,
                    "best_prsm_e_value": protein_best_e,
                }
            ),
        },
    ).one()
    return int(row.protein_id)


def _insert_proteoform(
    conn: Connection,
    *,
    dataset_id: int,
    cutoff_kind: str,
    source_seq_id: int,
    form_doc: dict[str, Any],
    fallback_sequence_name: Any,
) -> int:
    source_form_id = to_int(form_doc.get("proteoform_id"))
    form_prsms = ensure_list(form_doc.get("prsm"))
    form_best_id, form_best_e = best_prsm(form_prsms)
    proteoform_mass = _extract_proteoform_mass(form_prsms)
    sequence_name = str(form_doc.get("sequence_name") or fallback_sequence_name or "")
    row = conn.execute(
        text(
            """
            INSERT INTO proteoforms (
                dataset_id,
                modifications,
                start_res,
                end_res,
                theoretical_mass,
                extra_metadata
            )
            VALUES (
                :dataset_id,
                '[]'::jsonb,
                NULL,
                NULL,
                :theoretical_mass,
                CAST(:extra_metadata AS jsonb)
            )
            RETURNING proteoform_id
            """
        ),
        {
            "dataset_id": dataset_id,
            "theoretical_mass": proteoform_mass,
            "extra_metadata": _json_dumps(
                {
                    "source_sequence_id": source_seq_id,
                    "source_proteoform_id": source_form_id,
                    "sequence_name": sequence_name,
                    "source_cutoff": cutoff_kind,
                    "prsm_number": to_int(form_doc.get("prsm_number"), len(form_prsms)) or 0,
                    "best_prsm_id": form_best_id,
                    "best_prsm_e_value": form_best_e,
                }
            ),
        },
    ).one()
    return int(row.proteoform_id)


def _insert_relation(
    conn: Connection,
    *,
    dataset_id: int,
    protein_id: int,
    proteoform_id: int,
    cutoff_kind: str,
    source_seq_id: int,
    source_form_id: int,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO protein_relation_mapping (
                dataset_id,
                protein_id,
                entity_type,
                entity_id,
                start_position,
                end_position,
                is_unique,
                extra_metadata
            )
            VALUES (
                :dataset_id,
                :protein_id,
                'PROTEOFORM',
                :entity_id,
                NULL,
                NULL,
                FALSE,
                CAST(:extra_metadata AS jsonb)
            )
            """
        ),
        {
            "dataset_id": dataset_id,
            "protein_id": protein_id,
            "entity_id": proteoform_id,
            "extra_metadata": _json_dumps(
                {
                    "source_sequence_id": source_seq_id,
                    "source_proteoform_id": source_form_id,
                    "source_cutoff": cutoff_kind,
                }
            ),
        },
    )


def _import_fast_prsm_summaries(
    conn: Connection,
    *,
    dataset_id: int,
    run_id: int,
    cutoff_kind: str,
    cutoff_root: Path,
    source_seq_id: int,
    source_form_id: int,
    proteoform_id: int,
    sequence_name: str,
    form_doc: dict[str, Any],
    fast_match_keys: set[tuple[str, int]],
    stats: UniversalImportStats,
) -> None:
    """Register PrSM rows from proteins.js summaries without opening prsm*.js files."""
    prsms_dir = cutoff_root / "prsms"
    for prsm_summary in ensure_list(form_doc.get("prsm")):
        source_prsm_id = to_int(prsm_summary.get("prsm_id"))
        if source_prsm_id is None:
            stats.skipped_matches += 1
            continue
        detail_path = prsms_dir / f"prsm{source_prsm_id}.js"
        if not detail_path.exists():
            stats.skipped_matches += 1
            continue
        match_key = (cutoff_kind, source_prsm_id)
        if match_key in fast_match_keys:
            continue
        fast_match_keys.add(match_key)

        conn.execute(
            text(
                """
                INSERT INTO identification_matches (
                    dataset_id,
                    run_id,
                    scan_number,
                    spectrum_native_id,
                    retention_time,
                    ms_level,
                    entity_type,
                    entity_id,
                    modified_sequence,
                    experimental_mass,
                    precursor_mz,
                    precursor_charge,
                    intensity,
                    score,
                    e_value,
                    q_value,
                    pep,
                    is_decoy_match,
                    search_engine,
                    detail_path,
                    detail_cache,
                    extra_metadata
                )
                VALUES (
                    :dataset_id,
                    :run_id,
                    -1,
                    NULL,
                    NULL,
                    2,
                    'PROTEOFORM',
                    :entity_id,
                    :modified_sequence,
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    :e_value,
                    :q_value,
                    NULL,
                    :is_decoy_match,
                    'TopPIC',
                    :detail_path,
                    NULL,
                    CAST(:extra_metadata AS jsonb)
                )
                """
            ),
            {
                "dataset_id": dataset_id,
                "run_id": run_id,
                "entity_id": proteoform_id,
                "modified_sequence": sequence_name or None,
                "e_value": to_float(prsm_summary.get("e_value")),
                "q_value": to_float(prsm_summary.get("fdr")),
                "is_decoy_match": _looks_decoy(sequence_name, None),
                "detail_path": str(detail_path),
                "extra_metadata": _json_dumps(
                    {
                        "source_cutoff": cutoff_kind,
                        "source_prsm_id": source_prsm_id,
                        "p_value": to_float(prsm_summary.get("p_value")),
                        "matched_fragment_number": to_int(prsm_summary.get("matched_fragment_number")),
                        "matched_peak_number": to_int(prsm_summary.get("matched_peak_number")),
                        "ms1_ids": None,
                        "ms2_ids": None,
                        "ms1_scans": None,
                        "ms2_scans": None,
                        "source_sequence_id": source_seq_id,
                        "source_proteoform_id": source_form_id,
                        "import_mode": "fast",
                    }
                ),
            },
        )
        stats.matches += 1


def _import_prsm_matches(
    conn: Connection,
    *,
    dataset_id: int,
    run_id: int,
    cutoff_kind: str,
    cutoff_root: Path,
    proteoform_by_source_key: dict[tuple[int, int], int],
    stats: UniversalImportStats,
) -> None:
    prsms_dir = cutoff_root / "prsms"
    if not prsms_dir.exists():
        return

    files = sorted(prsms_dir.glob("prsm*.js"), key=_prsm_sort_key)
    bar = tqdm(files, desc=f"{cutoff_kind} universal matches", unit="prsm", ascii=True)
    for path in bar:
        try:
            doc = load_js_object(path)
        except Exception:
            stats.skipped_matches += 1
            continue

        prsm_root = doc.get("prsm") or doc
        annotated = prsm_root.get("annotated_protein", {}) or {}
        source_seq_id = to_int(annotated.get("sequence_id"))
        source_form_id = to_int(annotated.get("proteoform_id"))
        if source_seq_id is None or source_form_id is None:
            stats.skipped_matches += 1
            continue

        proteoform_id = proteoform_by_source_key.get((source_seq_id, source_form_id))
        if proteoform_id is None:
            stats.skipped_matches += 1
            continue

        ms = prsm_root.get("ms", {}) or {}
        header = ms.get("ms_header", {}) or {}
        ms2_scan = _first_int(header.get("scans"))
        if ms2_scan is None:
            stats.skipped_matches += 1
            continue

        conn.execute(
            text(
                """
                INSERT INTO identification_matches (
                    dataset_id,
                    run_id,
                    scan_number,
                    spectrum_native_id,
                    retention_time,
                    ms_level,
                    entity_type,
                    entity_id,
                    modified_sequence,
                    experimental_mass,
                    precursor_mz,
                    precursor_charge,
                    intensity,
                    score,
                    e_value,
                    q_value,
                    pep,
                    is_decoy_match,
                    search_engine,
                    detail_path,
                    detail_cache,
                    extra_metadata
                )
                VALUES (
                    :dataset_id,
                    :run_id,
                    :scan_number,
                    :spectrum_native_id,
                    NULL,
                    2,
                    'PROTEOFORM',
                    :entity_id,
                    :modified_sequence,
                    :experimental_mass,
                    :precursor_mz,
                    :precursor_charge,
                    :intensity,
                    NULL,
                    :e_value,
                    :q_value,
                    NULL,
                    :is_decoy_match,
                    'TopPIC',
                    :detail_path,
                    NULL,
                    CAST(:extra_metadata AS jsonb)
                )
                """
            ),
            {
                "dataset_id": dataset_id,
                "run_id": run_id,
                "scan_number": ms2_scan,
                "spectrum_native_id": _first_text(header.get("ids")),
                "entity_id": proteoform_id,
                "modified_sequence": _annotation_summary(annotated),
                "experimental_mass": to_float(header.get("precursor_mono_mass")),
                "precursor_mz": to_float(header.get("precursor_mz")),
                "precursor_charge": to_int(header.get("precursor_charge")),
                "intensity": to_float(header.get("feature_inte")),
                "e_value": to_float(prsm_root.get("e_value")),
                "q_value": to_float(prsm_root.get("fdr")),
                "is_decoy_match": _looks_decoy(annotated.get("sequence_name"), None),
                "detail_path": str(path),
                "extra_metadata": _json_dumps(
                    {
                        "source_cutoff": cutoff_kind,
                        "source_prsm_id": to_int(prsm_root.get("prsm_id")),
                        "p_value": to_float(prsm_root.get("p_value")),
                        "matched_fragment_number": to_int(prsm_root.get("matched_fragment_number")),
                        "matched_peak_number": to_int(prsm_root.get("matched_peak_number")),
                        "ms1_ids": _as_text(header.get("ms1_ids")),
                        "ms2_ids": _as_text(header.get("ids")),
                        "ms1_scans": _as_text(header.get("ms1_scans")),
                        "ms2_scans": _as_text(header.get("scans")),
                        "source_sequence_id": source_seq_id,
                        "source_proteoform_id": source_form_id,
                    }
                ),
            },
        )
        stats.matches += 1


def _extract_proteoform_mass(form_prsms: list[dict[str, Any]]) -> float | None:
    for prsm in form_prsms:
        annotated = prsm.get("annotated_protein")
        if annotated and annotated.get("proteoform_mass"):
            value = to_float(annotated.get("proteoform_mass"))
            if value is not None:
                return value
    return None


def _accession_from_sequence_name(sequence_name: str, source_seq_id: int | None) -> str:
    if sequence_name:
        return sequence_name[:255]
    return f"sequence_{source_seq_id or 'unknown'}"


def _looks_decoy(name: Any, description: Any) -> bool:
    text_value = f"{name or ''} {description or ''}".lower()
    return any(marker in text_value for marker in ("decoy", "reverse", "rev_", "rev-"))


def _annotation_summary(annotated: dict[str, Any]) -> str | None:
    annotation = annotated.get("annotation")
    if annotation is None:
        return annotated.get("sequence_name")
    if isinstance(annotation, str):
        return annotation
    return annotated.get("sequence_name")


def _prsm_sort_key(path: Path) -> int:
    try:
        return int(path.stem.removeprefix("prsm"))
    except ValueError:
        return 1 << 30


def _first_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return str(value[0]) if value else None
    text_value = str(value)
    for separator in (",", ";", " "):
        if separator in text_value:
            return next((part for part in text_value.split(separator) if part), None)
    return text_value or None


def _first_int(value: Any) -> int | None:
    return to_int(_first_text(value))


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _json_dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


if __name__ == "__main__":
    app()
