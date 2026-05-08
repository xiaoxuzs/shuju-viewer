"""Import prsm*.js-only datasets (plus mzML mapping) into universal schema.

This adapter exists for ZIPs that do NOT contain TopPIC HTML output trees
(`toppic_prsm_cutoff/data_js/...`). Instead, the archive provides:

- data/prsm*.js  (TopPIC prsm_data JS objects)
- one or more mzML(.gz) files (referenced by ms_header.spectrum_file_name)

We import a minimal yet usable subset for the main viewer:
- datasets (capabilities include has_prsms, etc.)
- runs (one per spectrum_file_name)
- proteins / proteoforms / protein_relation_mapping (derived from annotated_protein)
- identification_matches (one per prsm*.js, entity_type='PROTEOFORM')

Spectrum peak arrays remain on-demand via mzML in-memory store.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from app.ingest.utils import to_float, to_int
from app.services.js_parser import load_js_object


@dataclass
class UniversalImportStats:
    dataset_id: int
    run_id: int
    proteins: int = 0
    proteoforms: int = 0
    matches: int = 0


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _accession_from_sequence_name(name: str, seq_id: int | None) -> str:
    if name:
        return name[:255]
    return f"sequence_{seq_id or 'unknown'}"


def ingest_universal_prsm_js(
    *,
    root: Path,
    database_url: str,
    slug: str,
    name: str,
    replace: bool = True,
) -> UniversalImportStats:
    root = root.resolve()
    prsms_dir = root / "data"
    if not prsms_dir.exists():
        raise FileNotFoundError(prsms_dir)
    files = sorted(prsms_dir.glob("prsm*.js"), key=lambda p: p.name)
    if not files:
        raise ValueError(f"no prsm*.js under {prsms_dir}")

    engine = create_engine(database_url, future=True)
    with engine.begin() as conn:
        if replace:
            conn.execute(text("DELETE FROM datasets WHERE slug = :slug"), {"slug": slug})

        # Create dataset.
        row = conn.execute(
            text(
                """
                INSERT INTO datasets (
                    dataset_name, slug, analysis_mode, source_software,
                    source_root, status, description, capabilities
                )
                VALUES (
                    :name, :slug, 'TOP_DOWN', 'TopPIC_prsm_js',
                    :source_root, 'IMPORTED',
                    'Dataset imported from prsm*.js (no TopPIC HTML tree)',
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
                    '"spectra_in_database": false, "spectra_source": "mzml_memory"}'
                ),
            },
        ).one()
        dataset_id = int(row.dataset_id)

        # Runs by spectrum_file_name.
        run_by_file: dict[str, int] = {}

        def _get_or_create_run(file_name: str) -> int:
            key = file_name.strip()
            cached = run_by_file.get(key)
            if cached is not None:
                return cached
            r = conn.execute(
                text(
                    """
                    INSERT INTO runs (
                        dataset_id, file_path, file_name,
                        analysis_mode, software, status
                    )
                    VALUES (
                        :dataset_id, :file_path, :file_name,
                        'TOP_DOWN', 'TopPIC_prsm_js', 'IMPORTED'
                    )
                    RETURNING run_id
                    """
                ),
                {"dataset_id": dataset_id, "file_path": str(root), "file_name": key},
            ).one()
            run_id = int(r.run_id)
            run_by_file[key] = run_id
            return run_id

        protein_by_seq: dict[int, int] = {}
        proteoform_by_key: dict[tuple[int, int], int] = {}

        def _get_or_create_protein(annotated: dict[str, Any]) -> int:
            seq_id = to_int(annotated.get("sequence_id"), 0) or 0
            cached = protein_by_seq.get(seq_id)
            if cached is not None:
                return cached
            seq_name = str(annotated.get("sequence_name") or "")
            acc = _accession_from_sequence_name(seq_name, seq_id)
            r = conn.execute(
                text(
                    """
                    INSERT INTO proteins (
                        dataset_id, accession, description, base_sequence, is_decoy, extra_metadata
                    )
                    VALUES (
                        :dataset_id, :accession, :description, NULL, FALSE,
                        CAST(:extra_metadata AS jsonb)
                    )
                    RETURNING protein_id
                    """
                ),
                {
                    "dataset_id": dataset_id,
                    "accession": acc,
                    "description": annotated.get("sequence_description"),
                    "extra_metadata": _json({"source_sequence_id": seq_id, "source_sequence_name": seq_name}),
                },
            ).one()
            pid = int(r.protein_id)
            protein_by_seq[seq_id] = pid
            return pid

        def _get_or_create_proteoform(annotated: dict[str, Any]) -> int:
            seq_id = to_int(annotated.get("sequence_id"), 0) or 0
            form_id = to_int(annotated.get("proteoform_id"), 0) or 0
            key = (seq_id, form_id)
            cached = proteoform_by_key.get(key)
            if cached is not None:
                return cached
            mass = to_float(annotated.get("proteoform_mass"))
            seq_name = str(annotated.get("sequence_name") or "")
            r = conn.execute(
                text(
                    """
                    INSERT INTO proteoforms (
                        dataset_id, modifications, start_res, end_res, theoretical_mass, extra_metadata
                    )
                    VALUES (
                        :dataset_id, '[]'::jsonb, NULL, NULL, :mass,
                        CAST(:extra_metadata AS jsonb)
                    )
                    RETURNING proteoform_id
                    """
                ),
                {
                    "dataset_id": dataset_id,
                    "mass": mass,
                    "extra_metadata": _json(
                        {
                            "source_sequence_id": seq_id,
                            "source_proteoform_id": form_id,
                            "sequence_name": seq_name,
                            "source_cutoff": "prsm",
                        }
                    ),
                },
            ).one()
            pfid = int(r.proteoform_id)
            proteoform_by_key[key] = pfid
            return pfid

        relation_keys: set[tuple[int, int]] = set()

        # Insert matches.
        for path in files:
            doc = load_js_object(path)
            prsm_root = doc.get("prsm") or doc.get("prsm_data", {}).get("prsm") or doc
            annotated = prsm_root.get("annotated_protein", {}) or {}
            ms = prsm_root.get("ms", {}) or {}
            header = ms.get("ms_header", {}) or {}

            spectrum_file_name = str(header.get("spectrum_file_name") or "").strip()
            if not spectrum_file_name:
                raise ValueError(f"missing spectrum_file_name in {path}")
            run_id = _get_or_create_run(spectrum_file_name)

            protein_id = _get_or_create_protein(annotated)
            proteoform_id = _get_or_create_proteoform(annotated)

            if (protein_id, proteoform_id) not in relation_keys:
                conn.execute(
                    text(
                        """
                        INSERT INTO protein_relation_mapping (
                            dataset_id, protein_id, entity_type, entity_id,
                            start_position, end_position, is_unique, extra_metadata
                        )
                        VALUES (
                            :dataset_id, :protein_id, 'PROTEOFORM', :entity_id,
                            NULL, NULL, FALSE, CAST(:extra_metadata AS jsonb)
                        )
                        """
                    ),
                    {
                        "dataset_id": dataset_id,
                        "protein_id": protein_id,
                        "entity_id": proteoform_id,
                        "extra_metadata": _json({"source_cutoff": "prsm"}),
                    },
                )
                relation_keys.add((protein_id, proteoform_id))

            ms2_scan = to_int(header.get("scans"))
            if ms2_scan is None:
                raise ValueError(f"missing ms2 scans in {path}")

            conn.execute(
                text(
                    """
                    INSERT INTO identification_matches (
                        dataset_id, run_id, scan_number, spectrum_native_id,
                        retention_time, ms_level,
                        entity_type, entity_id,
                        modified_sequence,
                        experimental_mass, precursor_mz, precursor_charge,
                        intensity, score, e_value, q_value, pep,
                        is_decoy_match, search_engine,
                        detail_path, detail_cache, extra_metadata
                    )
                    VALUES (
                        :dataset_id, :run_id, :scan_number, NULL,
                        NULL, 2,
                        'PROTEOFORM', :entity_id,
                        :modified_sequence,
                        :experimental_mass, :precursor_mz, :precursor_charge,
                        :intensity, NULL, :e_value, :q_value, NULL,
                        FALSE, 'TopPIC',
                        :detail_path, NULL, CAST(:extra_metadata AS jsonb)
                    )
                    """
                ),
                {
                    "dataset_id": dataset_id,
                    "run_id": run_id,
                    "scan_number": ms2_scan,
                    "entity_id": proteoform_id,
                    "modified_sequence": annotated.get("sequence_name"),
                    "experimental_mass": to_float(header.get("precursor_mono_mass")),
                    "precursor_mz": to_float(header.get("precursor_mz")),
                    "precursor_charge": to_int(header.get("precursor_charge")),
                    "intensity": to_float(header.get("feature_inte")),
                    "e_value": to_float(prsm_root.get("e_value")),
                    "q_value": to_float(prsm_root.get("fdr")),
                    "detail_path": str(path),
                    "extra_metadata": _json(
                        {
                            "source_cutoff": "prsm",
                            "source_prsm_id": to_int(prsm_root.get("prsm_id")),
                            "source_sequence_id": to_int(annotated.get("sequence_id")),
                            "source_proteoform_id": to_int(annotated.get("proteoform_id")),
                            "p_value": to_float(prsm_root.get("p_value")),
                            "matched_fragment_number": to_int(prsm_root.get("matched_fragment_number")),
                            "matched_peak_number": to_int(prsm_root.get("matched_peak_number")),
                            "ms1_scans": str(header.get("ms1_scans") or ""),
                            "ms2_scans": str(header.get("scans") or ""),
                            "ms1_ids": str(header.get("ms1_ids") or ""),
                            "ms2_ids": str(header.get("ids") or ""),
                            "import_mode": "prsm_js",
                        }
                    ),
                },
            )

        # Mark READY
        conn.execute(text("UPDATE datasets SET status='READY' WHERE dataset_id=:dataset_id"), {"dataset_id": dataset_id})
        conn.execute(text("UPDATE runs SET status='READY' WHERE dataset_id=:dataset_id"), {"dataset_id": dataset_id})

        # pick a default run id for stats (first inserted)
        default_run_id = next(iter(run_by_file.values()))
        stats = UniversalImportStats(dataset_id=dataset_id, run_id=default_run_id)
        stats.proteins = len(protein_by_seq)
        stats.proteoforms = len(proteoform_by_key)
        stats.matches = len(files)
        return stats

