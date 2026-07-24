from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest.bu.bottom_up_identification import BottomUpIdentification
from app.ingest.bu.diann_parquet_reader import DiannReportInfo
from app.ingest.bu import universal_diann_adapter
from app.ingest.bu.universal_diann_adapter import _collect_entities_and_matches


def test_shared_bottom_up_writer_uses_source_specific_identification_fields() -> None:
    identification = BottomUpIdentification(
        report_row={
            "Run": "sample",
            "Stripped.Sequence": "PEPTIDE",
            "Modified.Sequence": "PEPTIDE",
            "Precursor.Charge": 2,
            "Precursor.Mz": 400.2,
            "RT": 12.3,
            "Protein.Group": "P12345",
            "Q.Value": 0.9,
            "Precursor.Quantity": 999.0,
        },
        score=0.95,
        q_value=0.004,
        intensity=123.0,
        pep=None,
        search_engine="DIA-CLIP",
        extra_metadata={"diaclip": {"feature_distance": 0.12}},
    )

    _proteins, _peptides, _relations, matches = _collect_entities_and_matches(
        [identification],
        dataset_id=4,
        run_id_by_diann={"sample": 8},
        description_by_accession={},
    )

    assert len(matches) == 1
    match = matches[0]
    assert match["score"] == 0.95
    assert match["q_value"] == 0.004
    assert match["intensity"] == 123.0
    assert match["search_engine"] == "DIA-CLIP"
    assert match["extra_metadata"]["diaclip"]["feature_distance"] == 0.12


def test_diann_entrypoint_preserves_existing_values_through_shared_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = tmp_path / "all_report.parquet"
    report.write_bytes(b"marker")
    report_info = DiannReportInfo(path=report, total_rows=2, run_names={"run-one"})
    row = {
        "Run": "run-one",
        "Q.Value": 0.002,
        "Global.Q.Value": 0.003,
        "Precursor.Quantity": 123.0,
        "PEP": 0.004,
    }
    captured: dict[str, object] = {}
    sentinel = object()

    monkeypatch.setattr(universal_diann_adapter, "find_diann_report", lambda _root: report)
    monkeypatch.setattr(universal_diann_adapter, "inspect_report", lambda _path: report_info)
    monkeypatch.setattr(
        universal_diann_adapter,
        "iter_filtered_rows",
        lambda _path, q_value_cutoff: iter([row]),
    )

    def fake_shared_writer(**kwargs: object) -> object:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(universal_diann_adapter, "ingest_universal_bottom_up", fake_shared_writer)

    result = universal_diann_adapter.ingest_universal_diann(
        root=tmp_path,
        database_url="postgresql://unused",
        slug="diann",
        name="DIA-NN",
    )

    assert result is sentinel
    source = captured["source"]
    assert source.software == "DIA-NN_2.0"
    assert source.import_mode == "diann_parquet"
    assert source.source_total_rows == 2
    assert source.skipped_matches == 1
    identification = source.identifications[0]
    assert identification.report_row is row
    assert identification.score == 0.003
    assert identification.q_value == 0.002
    assert identification.intensity == 123.0
    assert identification.pep == 0.004
    assert identification.search_engine == "DIA-NN"
