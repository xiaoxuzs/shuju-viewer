from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.bu.decoy_truth import roll_up_decoy_values
from app.declarative_ingest import DeclarativeImportPlan, build_declarative_zp_artifact
from app.ingest.zp import project_semantic_zp


def _plan(*, with_fasta: bool) -> DeclarativeImportPlan:
    sources: list[dict[str, object]] = [
        {
            "source_id": "ids",
            "relative_path": "results.tsv",
            "role": "identifications",
            "reader": "delimited",
            "delimiter": "\t",
            "required": True,
            "required_fields": ["id", "run", "sequence", "proteins", "intensity"],
        }
    ]
    if with_fasta:
        sources.append(
            {
                "source_id": "fasta",
                "relative_path": "search.fasta",
                "role": "reference_sequences",
                "reader": "fasta",
                "required": False,
                "required_fields": [],
            }
        )
    mappings = [
        ("id", "identification", "source_id", "string", "identity", None),
        ("run", "run", "name", "string", "identity", None),
        ("sequence", "peptide", "sequence", "string", "identity", None),
        ("proteins", "identification", "protein_accessions", "string", "semicolon_split", None),
        ("intensity", "quantification", "value", "float", "identity", "source_intensity"),
    ]
    return DeclarativeImportPlan.model_validate(
        {
            "schema_version": 1,
            "plan_id": "generic-projection-v1",
            "analysis_mode": "BOTTOM_UP",
            "sources": sources,
            "field_mappings": [
                {
                    "mapping_id": f"map-{field}",
                    "source_id": "ids",
                    "source_field": field,
                    "target_entity": entity,
                    "target_field": target,
                    "value_kind": value_kind,
                    "required": field != "intensity",
                    "transform": transform,
                    "unit": unit,
                    "evidence_refs": [f"observation:{field}"],
                }
                for field, entity, target, value_kind, transform, unit in mappings
            ],
            "unmapped_fields": {"ids": []},
            "requested_views": [
                {"view_id": "bu.matches"},
                {"view_id": "bu.peptides"},
                {"view_id": "bu.proteins"},
                {"view_id": "bu.protein_coverage"},
            ],
        }
    )


def _schema(session: Session) -> None:
    for ddl in (
        """
        CREATE TABLE proteins (
            protein_id INTEGER PRIMARY KEY AUTOINCREMENT, dataset_id INTEGER NOT NULL,
            accession TEXT NOT NULL, gene_name TEXT, description TEXT, base_sequence TEXT,
            is_decoy INTEGER NOT NULL, extra_metadata TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE peptides (
            peptide_id INTEGER PRIMARY KEY AUTOINCREMENT, dataset_id INTEGER NOT NULL,
            sequence TEXT NOT NULL, theoretical_mass REAL, length INTEGER,
            extra_metadata TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE identification_matches (
            match_id INTEGER PRIMARY KEY AUTOINCREMENT, dataset_id INTEGER NOT NULL,
            run_id INTEGER NOT NULL, scan_number INTEGER NOT NULL, spectrum_native_id TEXT,
            retention_time REAL, ms_level INTEGER NOT NULL, entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL, modified_sequence TEXT, experimental_mass REAL,
            precursor_mz REAL, precursor_charge INTEGER, intensity REAL, score REAL,
            e_value REAL, q_value REAL, pep REAL, is_decoy_match INTEGER NOT NULL,
            search_engine TEXT, detail_path TEXT, detail_cache TEXT, extra_metadata TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE protein_relation_mapping (
            mapping_id INTEGER PRIMARY KEY AUTOINCREMENT, dataset_id INTEGER NOT NULL,
            protein_id INTEGER NOT NULL, entity_type TEXT NOT NULL, entity_id INTEGER NOT NULL,
            start_position INTEGER, end_position INTEGER, is_unique INTEGER NOT NULL,
            extra_metadata TEXT NOT NULL
        )
        """,
    ):
        session.execute(text(ddl))
    session.commit()


def _artifact(tmp_path: Path, *, with_fasta: bool):
    source = tmp_path / "source"
    source.mkdir()
    (source / "results.tsv").write_text(
        "id\trun\tsequence\tproteins\tintensity\n"
        "1\trun-a\tPEPTIDE\tP1\t0\n",
        encoding="utf-8",
    )
    if with_fasta:
        (source / "search.fasta").write_text(">P1\nXXPEPTIDEXX\n", encoding="utf-8")
    artifact = build_declarative_zp_artifact(
        source_root=source,
        source_fingerprint="e" * 32,
        plan=_plan(with_fasta=with_fasta),
        output_path=tmp_path / "candidate.zp",
    )
    return artifact


def test_projection_keeps_entities_when_fasta_and_spectra_are_missing(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path, with_fasta=False)
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with Session(engine) as session:
        _schema(session)
        semantic, stats = project_semantic_zp(
            session,
            dataset_id=7,
            zp_path=artifact.path,
            run_id_by_semantic_id={artifact.semantic_dataset.runs[0].run_id: 11},
        )
        session.commit()

        assert stats.as_dict() == {
            "proteins": 1,
            "peptides": 1,
            "identifications": 1,
            "protein_relations": 1,
            "exact_peptide_positions": 0,
            "ambiguous_peptide_positions": 0,
            "missing_peptide_positions": 1,
        }
        assert semantic.proteins[0].sequence_state == "MISSING"
        protein = session.execute(
            text("SELECT is_decoy, extra_metadata FROM proteins")
        ).mappings().one()
        assert protein["is_decoy"] == 0
        assert json.loads(protein["extra_metadata"])["is_decoy_state"] == "MISSING"
        assert session.scalar(text("SELECT count(*) FROM identification_matches")) == 1
        match = session.execute(
            text("SELECT scan_number, intensity, is_decoy_match, extra_metadata FROM identification_matches")
        ).mappings().one()
        assert match["scan_number"] == -1
        assert match["intensity"] == 0
        match_metadata = json.loads(match["extra_metadata"])
        assert match["is_decoy_match"] == 0
        assert match_metadata["is_decoy_state"] == "MISSING"
        assert match_metadata["spectrum_link_state"] == "MISSING"


@pytest.mark.parametrize(
    ("values", "storage_value", "state"),
    [
        ([True, True], True, "DIRECT"),
        ([True, False], False, "DIRECT"),
        ([None, None], False, "MISSING"),
        ([True, None], False, "AMBIGUOUS"),
    ],
)
def test_projection_rolls_up_decoy_truth_without_asserting_unknowns_are_targets(
    values: list[bool | None],
    storage_value: bool,
    state: str,
) -> None:
    assert roll_up_decoy_values(values) == (storage_value, state)


def test_projection_derives_unique_peptide_position_only_from_supplied_sequence(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path, with_fasta=True)
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with Session(engine) as session:
        _schema(session)
        _, stats = project_semantic_zp(
            session,
            dataset_id=8,
            zp_path=artifact.path,
            run_id_by_semantic_id={artifact.semantic_dataset.runs[0].run_id: 12},
        )
        session.commit()

        assert stats.exact_peptide_positions == 1
        relation = session.execute(
            text("SELECT start_position, end_position, is_unique, extra_metadata FROM protein_relation_mapping")
        ).mappings().one()
        assert (relation["start_position"], relation["end_position"], relation["is_unique"]) == (2, 9, 1)
        assert '"position_derivation": "exact_peptide_substring_v1"' in relation["extra_metadata"]
