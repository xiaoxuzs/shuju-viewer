from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.ingest import mzml_only_adapter


class _Result:
    def __init__(self, value: int | None = None) -> None:
        self.value = value

    def one(self) -> SimpleNamespace:
        return SimpleNamespace(dataset_id=self.value, run_id=self.value)


class _Connection:
    def __init__(self) -> None:
        self.datasets: list[dict[str, Any]] = []
        self.runs: list[dict[str, Any]] = []
        self.statements: list[str] = []

    def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _Result:
        sql = str(stmt)
        self.statements.append(sql)
        if "INSERT INTO datasets" in sql:
            assert params is not None
            self.datasets.append(params)
            return _Result(7)
        if "INSERT INTO runs" in sql:
            assert params is not None
            self.runs.append(params)
            return _Result(len(self.runs))
        return _Result()


class _Begin:
    def __init__(self, conn: _Connection) -> None:
        self.conn = conn

    def __enter__(self) -> _Connection:
        return self.conn

    def __exit__(self, *_args: Any) -> None:
        return None


class _Engine:
    def __init__(self, conn: _Connection) -> None:
        self.conn = conn

    def begin(self) -> _Begin:
        return _Begin(self.conn)


def test_mzml_only_adapter_creates_dataset_and_runs(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "spectra"
    root.mkdir()
    mzml = root / "sample.mzML"
    mzml.write_text("<mzML />", encoding="utf-8")
    derived = root / ".viewer-derived" / "raw-converted-mzml" / "stale.mzML"
    derived.parent.mkdir(parents=True)
    derived.write_text("<mzML />", encoding="utf-8")
    conn = _Connection()
    monkeypatch.setattr(mzml_only_adapter, "create_engine", lambda *_args, **_kwargs: _Engine(conn))

    stats = mzml_only_adapter.ingest_mzml_only(
        root=root,
        database_url="postgresql://unused",
        slug="spectra",
        name="Spectra",
        replace=True,
    )

    assert stats.dataset_id == 7
    assert stats.run_id == 1
    assert stats.runs == 1
    caps = json.loads(conn.datasets[0]["capabilities"])
    assert caps["analysis_shape"] == "mzml_only"
    assert caps["has_identifications"] is False
    metadata = json.loads(conn.runs[0]["run_metadata"])
    assert metadata == {"raw_format": "mzml", "mzml_file_path": str(mzml.resolve())}
    assert not any("INSERT INTO proteins" in sql or "INSERT INTO identification_matches" in sql for sql in conn.statements)


def test_mzml_only_adapter_records_raw_conversion_metadata(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    converted = tmp_path / "converted" / "sample.mzML"
    converted.parent.mkdir()
    converted.write_text("<mzML />", encoding="utf-8")
    conn = _Connection()
    monkeypatch.setattr(mzml_only_adapter, "create_engine", lambda *_args, **_kwargs: _Engine(conn))

    mzml_only_adapter.ingest_mzml_only(
        root=root,
        database_url="postgresql://unused",
        slug="raw",
        name="Raw",
        replace=True,
        extra_mzml_roots=(converted.parent,),
        raw_conversion_by_mzml_key={
            "sample": {
                "raw_path": str((root / "sample.raw").resolve()),
                "raw_conversion": {"status": "converted", "converter_name": "ThermoRawFileParser"},
            }
        },
    )

    caps = json.loads(conn.datasets[0]["capabilities"])
    assert caps["analysis_shape"] == "raw_mzml_only"
    metadata = json.loads(conn.runs[0]["run_metadata"])
    assert metadata["raw_path"].endswith("sample.raw")
    assert metadata["raw_conversion"]["status"] == "converted"
