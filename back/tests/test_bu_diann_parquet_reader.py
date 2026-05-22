from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from app.ingest.bu.diann_parquet_reader import inspect_report, iter_filtered_rows


def test_iter_filtered_rows_keeps_non_decoy_q_lt_cutoff(tmp_path: Path) -> None:
    path = tmp_path / "all_report.parquet"
    table = pa.table(
        {
            "Run": ["run_a", "run_a", "run_b"],
            "Precursor.Id": ["p1", "p2", "p3"],
            "Modified.Sequence": ["PEP", "PEP2", "PEP3"],
            "Stripped.Sequence": ["PEP", "PEP2", "PEP3"],
            "Precursor.Charge": [2, 2, 3],
            "Decoy": [0, 1, 0],
            "Precursor.Mz": [500.0, 600.0, 700.0],
            "Protein.Group": ["P1", "P2", "P3"],
            "Q.Value": [0.009, 0.001, 0.02],
        }
    )
    pq.write_table(table, path)

    info = inspect_report(path)
    rows = list(iter_filtered_rows(path))

    assert info.total_rows == 3
    assert info.run_names == {"run_a", "run_b"}
    assert [row["Precursor.Id"] for row in rows] == ["p1"]
