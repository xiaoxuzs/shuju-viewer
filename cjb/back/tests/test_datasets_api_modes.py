from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from app.api.v1 import datasets as datasets_api
from app.api.v1.datasets import _cutoffs_payload, _dataset_out
from app.schemas import BuRunSummary, CutoffOut, DatasetRunSummary
from app.services import spectrum_memory_wiring


class _NoExecuteSession:
    def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("BU cutoffs must not execute TD cutoff SQL")


class _RowsResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> "_RowsResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _RowsSession:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def execute(self, *_args: Any, **_kwargs: Any) -> _RowsResult:
        return _RowsResult(self._rows)


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "dataset_id": 1,
        "slug": "dataset",
        "dataset_name": "Dataset",
        "description": None,
        "source_root": "D:\\data",
        "capabilities": {},
        "analysis_mode": "TOP_DOWN",
        "status": "READY",
        "source_software": "TopPIC_TopFD",
        "extra_metadata": {},
        "created_at": datetime(2026, 5, 22, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def test_bu_dataset_json_contract() -> None:
    cutoffs = _cutoffs_payload(_NoExecuteSession(), 39, analysis_mode="BOTTOM_UP")
    out = _dataset_out(
        row=_row(
            dataset_id=39,
            slug="bu_pr1_dia",
            dataset_name="BU PR1 DIA",
            analysis_mode="BOTTOM_UP",
            source_software="DIA-NN_2.0",
            extra_metadata={"q_value_cutoff": 0.01},
        ),
        cutoffs=cutoffs,
        bu_runs=[
            BuRunSummary(
                run_id=10,
                file_name="run.mzML",
                raw_format="mzml",
                diann_run_name="run",
            ),
            BuRunSummary(
                run_id=11,
                file_name="sample.d",
                raw_format="bruker_d",
                diann_run_name="sample",
            ),
        ],
    )

    data = out.model_dump(mode="json")
    assert data["analysis_mode"] == "BOTTOM_UP"
    assert data["status"] == "READY"
    assert data["source_software"] == "DIA-NN_2.0"
    assert data["cutoffs"] == []
    assert data["extra_metadata"]["q_value_cutoff"] == 0.01
    assert [r["raw_format"] for r in data["bu_runs"]] == ["mzml", "bruker_d"]
    assert [r["diann_run_name"] for r in data["bu_runs"]] == ["run", "sample"]


def test_td_dataset_json_contract_keeps_cutoffs_and_omits_bu_runs() -> None:
    out = _dataset_out(
        row=_row(slug="mz20160222ds_histone49_html"),
        cutoffs=[
            CutoffOut(id=1, kind="prsm", label="TopPIC PrSM cutoff"),
            CutoffOut(id=2, kind="proteoform", label="TopPIC Proteoform cutoff"),
        ],
        bu_runs=None,
    )

    data = out.model_dump(mode="json")
    assert data["analysis_mode"] == "TOP_DOWN"
    assert data["cutoffs"][0]["kind"] == "prsm"
    assert data["cutoffs"][1]["kind"] == "proteoform"
    assert data["bu_runs"] is None
    assert data["dataset_mode"] == "top_down"


def test_spectra_only_dataset_json_contract_includes_generic_runs() -> None:
    out = _dataset_out(
        row=_row(
            slug="spectra",
            dataset_name="Spectra",
            analysis_mode="TOP_DOWN",
            source_software="mzML_only",
            capabilities={
                "analysis_shape": "mzml_only",
                "spectra_source": "mzml_memory",
                "has_chromatogram": True,
            },
        ),
        cutoffs=[],
        bu_runs=None,
        runs=[
            DatasetRunSummary(
                run_id=10,
                run_name="run.mzML",
                raw_format="mzml",
                mzml_file_path="D:\\data\\run.mzML",
                raw_path=None,
                metadata={"raw_format": "mzml", "mzml_file_path": "D:\\data\\run.mzML"},
            )
        ],
    )

    data = out.model_dump(mode="json")
    assert data["analysis_mode"] == "TOP_DOWN"
    assert data["dataset_mode"] == "spectra_only"
    assert data["cutoffs"] == []
    assert data["bu_runs"] is None
    assert data["runs"][0]["run_name"] == "run.mzML"
    assert data["runs"][0]["raw_format"] == "mzml"


def test_raw_only_bottom_up_detail_uses_spectra_mode_and_generic_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row(
        dataset_id=55,
        slug="dda_raw",
        dataset_name="DDA RAW",
        analysis_mode="BOTTOM_UP",
        source_software="DDA Thermo RAW",
        capabilities={
            "analysis_shape": "raw_mzml_only",
            "has_identifications": False,
            "spectra_source": "zp",
        },
    )
    run = DatasetRunSummary(
        run_id=55,
        run_name="run.mzML",
        raw_format="thermo_raw",
        mzml_file_path=None,
        raw_path="D:\\data\\run.raw",
        metadata={"raw_format": "thermo_raw"},
    )

    monkeypatch.setattr(datasets_api, "require_dataset", lambda *_args: row)
    monkeypatch.setattr(datasets_api, "_cutoffs_payload", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        datasets_api,
        "_bu_runs_by_dataset",
        lambda *_args: pytest.fail("raw-only datasets must not load BU run summaries"),
    )
    monkeypatch.setattr(datasets_api, "_runs_by_dataset", lambda *_args: {55: [run]})

    out = datasets_api.get_dataset_detail("dda_raw", _NoExecuteSession())  # type: ignore[arg-type]
    data = out.model_dump(mode="json")

    assert data["analysis_mode"] == "BOTTOM_UP"
    assert data["dataset_mode"] == "spectra_only"
    assert data["bu_runs"] is None
    assert data["runs"][0]["run_id"] == 55
    assert data["runs"][0]["raw_format"] == "thermo_raw"


def test_td_cutoffs_payload_omits_empty_cutoff() -> None:
    cutoffs = _cutoffs_payload(
        _RowsSession(
            [
                {"cutoff": "prsm", "protein_count": 1, "proteoform_count": 30, "prsm_count": 30},
                {"cutoff": "proteoform", "protein_count": 0, "proteoform_count": 0, "prsm_count": 0},
            ]
        ),
        1,
        analysis_mode="TOP_DOWN",
    )

    assert [c.kind for c in cutoffs] == ["prsm"]


def test_get_dataset_detail_does_not_load_mzml_spectra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row(
        dataset_id=39,
        slug="bu_pr1_dia",
        dataset_name="BU PR1 DIA",
        analysis_mode="BOTTOM_UP",
    )
    run = BuRunSummary(
        run_id=10,
        file_name="run.mzML",
        raw_format="mzml",
        diann_run_name="run",
    )
    loader_called = False

    def fail_if_loaded(*_args: Any, **_kwargs: Any) -> None:
        nonlocal loader_called
        loader_called = True
        raise AssertionError("dataset detail must not load mzML spectra")

    monkeypatch.setattr(datasets_api, "require_dataset", lambda *_args: row)
    monkeypatch.setattr(datasets_api, "_cutoffs_payload", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(datasets_api, "_bu_runs_by_dataset", lambda *_args: {39: [run]})
    monkeypatch.setattr(
        spectrum_memory_wiring,
        "ensure_mzml_dataset_resident",
        fail_if_loaded,
    )

    out = datasets_api.get_dataset_detail("bu_pr1_dia", _NoExecuteSession())  # type: ignore[arg-type]
    data = out.model_dump(mode="json")

    assert loader_called is False
    assert data["id"] == 39
    assert data["slug"] == "bu_pr1_dia"
    assert data["name"] == "BU PR1 DIA"
    assert data["analysis_mode"] == "BOTTOM_UP"
    assert data["cutoffs"] == []
    assert len(data["bu_runs"]) == 1
    assert data["bu_runs"][0]["run_id"] == 10
    assert data["bu_runs"][0]["file_name"] == "run.mzML"
    assert data["bu_runs"][0]["raw_format"] == "mzml"
    assert data["bu_runs"][0]["diann_run_name"] == "run"
