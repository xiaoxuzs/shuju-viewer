from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.ingest.bu.diaclip_result_reader import (
    DIACLIP_REQUIRED_COLUMNS,
    DiaclipCandidate,
    DiaclipLayoutError,
    calculate_q_values,
    find_diaclip_result,
    normalize_modified_peptide,
    prepare_diaclip_source,
    read_diaclip_candidates,
)
from app.ingest.bu.diaclip_fdr_result_reader import (
    DIACLIP_FDR_COLUMNS,
    DIACLIP_FDR_SCHEMA_VERSION,
    detect_diaclip_fdr_parquet,
    prepare_diaclip_fdr_source,
)


def _write_tsv(path: Path, rows: list[list[object]], *, extra_column: bool = False) -> None:
    header = list(DIACLIP_REQUIRED_COLUMNS)
    if extra_column:
        header.append("future_column")
    lines = ["\t".join(header)]
    for row in rows:
        values = [str(value) for value in row]
        if extra_column:
            values.append("supported")
        lines.append("\t".join(values))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_report(path: Path, rows: list[dict[str, object]]) -> None:
    pq.write_table(pa.Table.from_pylist(rows), path)


def _fdr_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "Run.Index": 0,
        "Run": "run-one",
        "Precursor.Id": "PEPTIDE2",
        "Modified.Sequence": "PEPTIDE",
        "Stripped.Sequence": "PEPTIDE",
        "Precursor.Charge": 2,
        "Decoy": 0,
        "Proteotypic": 1,
        "Precursor.Mz": 456.25,
        "Protein.Ids": "P1",
        "Protein.Group": "P1",
        "Protein.Names": "",
        "Genes": "GENE1",
        "RT": 12.3,
        "iRT": 10.0,
        "Predicted.RT": 12.25,
        "Predicted.iRT": 10.1,
        "IM": 0.0,
        "iIM": 1.0,
        "Predicted.IM": 0.0,
        "Predicted.iIM": 1.1,
        "RT.Start": 12.0,
        "RT.Stop": 12.6,
        "FWHM": 0.1,
        "DIAClip.Score": 0.98,
        "DIAClip.Q.Value": 0.001,
        "DIAClip.Feature.Distance": -0.2,
        "DIAClip.Cosine.Similarity": 0.91,
        "DIAClip.Quantity": 1234.0,
        "DIAClip.Passed": True,
    }
    row.update(overrides)
    return row


def _write_fdr_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    schema = pa.schema(
        [
            pa.field("Run.Index", pa.int64()),
            pa.field("Run", pa.string()),
            pa.field("Precursor.Id", pa.string()),
            pa.field("Modified.Sequence", pa.string()),
            pa.field("Stripped.Sequence", pa.string()),
            pa.field("Precursor.Charge", pa.int64()),
            pa.field("Decoy", pa.int64()),
            pa.field("Proteotypic", pa.int64()),
            pa.field("Precursor.Mz", pa.float64()),
            pa.field("Protein.Ids", pa.string()),
            pa.field("Protein.Group", pa.string()),
            pa.field("Protein.Names", pa.string()),
            pa.field("Genes", pa.string()),
            pa.field("RT", pa.float64()),
            pa.field("iRT", pa.float64()),
            pa.field("Predicted.RT", pa.float64()),
            pa.field("Predicted.iRT", pa.float64()),
            pa.field("IM", pa.float64()),
            pa.field("iIM", pa.float64()),
            pa.field("Predicted.IM", pa.float64()),
            pa.field("Predicted.iIM", pa.float64()),
            pa.field("RT.Start", pa.float64()),
            pa.field("RT.Stop", pa.float64()),
            pa.field("FWHM", pa.float64()),
            pa.field("DIAClip.Score", pa.float64()),
            pa.field("DIAClip.Q.Value", pa.float64()),
            pa.field("DIAClip.Feature.Distance", pa.float64()),
            pa.field("DIAClip.Cosine.Similarity", pa.float64()),
            pa.field("DIAClip.Quantity", pa.float64()),
            pa.field("DIAClip.Passed", pa.bool_()),
        ]
    )
    table = pa.Table.from_pylist(
        [{name: row.get(name) for name in DIACLIP_FDR_COLUMNS} for row in rows],
        schema=schema,
    )
    pq.write_table(table, path)


def _candidate(score: float, label: int, suffix: str) -> DiaclipCandidate:
    key = (f"PEP{suffix}", 2, 1 - label)
    return DiaclipCandidate(
        key=key,
        label=label,
        score=score,
        feature_distance=0.1,
        cos_similarity=0.9,
        modified_peptide=key[0],
        normalized_modified_peptide=key[0],
        charge=2,
        quant_result=100.0,
        source_row=2,
    )


def test_result_detection_uses_header_not_filename_and_allows_extra_columns(tmp_path: Path) -> None:
    expected = tmp_path / "renamed-output.TSV"
    _write_tsv(expected, [[1, 0.9, 0.1, 0.8, "PEPTIDE", 2, 100]], extra_column=True)
    (tmp_path / "unrelated.tsv").write_text("Run\tQ.Value\nx\t0.1\n", encoding="utf-8")

    assert find_diaclip_result(tmp_path) == expected.resolve()


def test_result_detection_rejects_multiple_matching_tsv_files(tmp_path: Path) -> None:
    for name in ("one.tsv", "two.tsv"):
        _write_tsv(tmp_path / name, [[1, 0.9, 0.1, 0.8, "PEPTIDE", 2, 100]])

    with pytest.raises(DiaclipLayoutError, match="Multiple DIA-CLIP"):
        find_diaclip_result(tmp_path)


def test_reader_normalizes_modification_and_keeps_best_consistent_duplicate(tmp_path: Path) -> None:
    path = tmp_path / "clip.tsv"
    _write_tsv(
        path,
        [
            [1, 0.8, 0.3, 0.7, "AC(Carbamidomethyl)K", 2, 123],
            [1, 0.9, 0.2, 0.8, "AC(Carbamidomethyl)K", 2, 123],
        ],
    )

    rows, total = read_diaclip_candidates(path)

    assert total == 2
    assert len(rows) == 1
    assert rows[0].score == 0.9
    assert rows[0].duplicate_count == 2
    assert rows[0].normalized_modified_peptide == "AC(UniMod:4)K"
    assert normalize_modified_peptide("PEPTIDE") == "PEPTIDE"


def test_reader_rejects_duplicate_with_conflicting_quantity(tmp_path: Path) -> None:
    path = tmp_path / "clip.tsv"
    _write_tsv(
        path,
        [
            [1, 0.8, 0.3, 0.7, "PEPTIDE", 2, 100],
            [1, 0.9, 0.2, 0.8, "PEPTIDE", 2, 101],
        ],
    )

    with pytest.raises(DiaclipLayoutError, match="inconsistent quant_result"):
        read_diaclip_candidates(path)


def test_q_values_are_tie_aware_and_independent_of_input_order() -> None:
    rows = [
        _candidate(0.9, 1, "A"),
        _candidate(0.8, 1, "B"),
        _candidate(0.8, 0, "C"),
        _candidate(0.7, 1, "D"),
    ]

    forward = calculate_q_values(rows)
    reverse = calculate_q_values(list(reversed(rows)))

    assert forward == reverse
    assert forward[rows[0].key] == 0.0
    assert forward[rows[1].key] == pytest.approx(1 / 4)
    assert forward[rows[2].key] == pytest.approx(1 / 4)


def test_prepare_source_enriches_accepted_target_from_single_run_all_report(tmp_path: Path) -> None:
    _write_tsv(
        tmp_path / "model-output.TSV",
        [
            [1, 0.95, 0.2, 0.91, "AC(Carbamidomethyl)K", 2, 456.0],
            [0, 0.10, 0.7, 0.20, "DECOY", 2, 12.0],
        ],
    )
    _write_report(
        tmp_path / "ALL_REPORT.PARQUET",
        [
            {
                "Run": "run-one",
                "Precursor.Id": "AC(UniMod:4)K2",
                "Modified.Sequence": "AC(UniMod:4)K",
                "Stripped.Sequence": "ACK",
                "Precursor.Charge": 2,
                "Decoy": 0,
                "Precursor.Mz": 500.2,
                "Protein.Group": "P1",
                "Protein.Ids": "P1",
                "Genes": "GENE1",
                "RT": 12.3,
                "RT.Start": 12.0,
                "RT.Stop": 12.6,
                "Precursor.Quantity": 111.0,
                "Q.Value": 0.2,
                "Global.Q.Value": 0.3,
            },
            {
                "Run": "run-one",
                "Precursor.Id": "DECOY2",
                "Modified.Sequence": "DECOY",
                "Stripped.Sequence": "DECOY",
                "Precursor.Charge": 2,
                "Decoy": 1,
                "Precursor.Mz": 600.2,
                "Protein.Group": "DECOY_P1",
                "Precursor.Quantity": 10.0,
                "Q.Value": 0.8,
            },
        ],
    )

    prepared = prepare_diaclip_source(tmp_path)

    assert prepared.stats.accepted_targets == 1
    assert prepared.source.software == "DIA-CLIP"
    identification = prepared.source.identifications[0]
    assert identification.report_row["Run"] == "run-one"
    assert identification.score == 0.95
    assert identification.q_value == 0.0
    assert identification.intensity == 456.0
    assert identification.extra_metadata["diaclip"]["diann_q_value"] == 0.2


def test_prepare_source_rejects_multiple_report_runs(tmp_path: Path) -> None:
    _write_tsv(tmp_path / "clip.tsv", [[1, 0.95, 0.2, 0.91, "PEPTIDE", 2, 456]])
    _write_report(
        tmp_path / "all_report.parquet",
        [
            {
                "Run": "run-one",
                "Modified.Sequence": "PEPTIDE",
                "Stripped.Sequence": "PEPTIDE",
                "Precursor.Charge": 2,
                "Decoy": 0,
            },
            {
                "Run": "run-two",
                "Modified.Sequence": "OTHER",
                "Stripped.Sequence": "OTHER",
                "Precursor.Charge": 2,
                "Decoy": 0,
            },
        ],
    )

    with pytest.raises(DiaclipLayoutError, match="exactly one DIA-NN Run"):
        prepare_diaclip_source(tmp_path)


def test_fdr_parquet_detection_and_prepare_source_filters_to_passed_targets(tmp_path: Path) -> None:
    fdr = tmp_path / "sample.diaclip.fdr.parquet"
    _write_fdr_parquet(
        fdr,
        [
            _fdr_row(),
            _fdr_row(**{"Precursor.Id": "DECOY2", "Decoy": 1}),
            _fdr_row(**{"Precursor.Id": "FAILED2", "DIAClip.Passed": False}),
            _fdr_row(**{"Precursor.Id": "QHIGH2", "DIAClip.Q.Value": 0.02}),
        ],
    )
    (tmp_path / "run-one.mzML").write_text("<mzML />", encoding="utf-8")

    assert detect_diaclip_fdr_parquet(tmp_path) == fdr.resolve()
    prepared = prepare_diaclip_fdr_source(tmp_path)

    assert prepared.source.software == "DIA-CLIP"
    assert prepared.source.import_mode == "diaclip_fdr_parquet"
    assert prepared.source.extra_metadata["diaclip_schema_version"] == DIACLIP_FDR_SCHEMA_VERSION
    assert prepared.stats.parquet_total_rows == 4
    assert prepared.stats.accepted_targets == 1
    assert prepared.stats.decoy_rows == 1
    assert prepared.stats.failed_rows == 1
    identification = prepared.source.identifications[0]
    assert identification.report_row["Run"] == "run-one"
    assert identification.report_row["RT.Start"] == 12.0
    assert identification.score == 0.98
    assert identification.q_value == 0.001
    assert identification.intensity == 1234.0
    assert identification.extra_metadata["diaclip"]["source_format"] == "fdr_parquet"
    assert identification.extra_metadata["diaclip"]["quant_result"] == 1234.0


def test_fdr_parquet_requires_matching_mzml(tmp_path: Path) -> None:
    _write_fdr_parquet(tmp_path / "sample.diaclip.fdr.parquet", [_fdr_row()])

    with pytest.raises(DiaclipLayoutError, match="requires one matching mzML"):
        prepare_diaclip_fdr_source(tmp_path)
