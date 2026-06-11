from __future__ import annotations

from typing import Any

import pytest

from app.services import derived_data_backfill
from scripts import backfill_dataset_derived_data


class _Result:
    def __init__(self, *, one: dict[str, Any] | None = None, all_rows: list[dict[str, Any]] | None = None) -> None:
        self._one = one
        self._all = all_rows or []

    def mappings(self) -> "_Result":
        return self

    def one_or_none(self) -> dict[str, Any] | None:
        return self._one

    def all(self) -> list[dict[str, Any]]:
        return self._all


class _Session:
    def __init__(
        self,
        *,
        datasets_by_id: dict[int, dict[str, Any]],
        datasets_by_slug: dict[str, dict[str, Any]],
        runs: list[dict[str, Any]],
    ) -> None:
        self.datasets_by_id = datasets_by_id
        self.datasets_by_slug = datasets_by_slug
        self.runs = runs

    def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
        sql = str(statement)
        if "FROM datasets" in sql:
            if "dataset_id" in params:
                return _Result(one=self.datasets_by_id.get(int(params["dataset_id"])))
            return _Result(one=self.datasets_by_slug.get(str(params["slug"])))
        selected = [
            run
            for run in self.runs
            if int(run["dataset_id"]) == int(params["dataset_id"])
            and ("run_id" not in params or int(run["run_id"]) == int(params["run_id"]))
        ]
        return _Result(all_rows=selected)


def _dataset(
    dataset_id: int = 40,
    slug: str = "bu",
    analysis_mode: str = "BOTTOM_UP",
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "slug": slug,
        "analysis_mode": analysis_mode,
    }


def _run(
    run_id: int,
    *,
    dataset_id: int = 40,
    raw_format: str = "mzml",
    mzml_path: str | None = "run.mzML",
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"raw_format": raw_format}
    if mzml_path is not None:
        metadata["mzml_file_path"] = mzml_path
    return {
        "dataset_id": dataset_id,
        "run_id": run_id,
        "file_name": f"run-{run_id}",
        "file_path": mzml_path,
        "run_metadata": metadata,
    }


def _session(
    *,
    dataset: dict[str, Any] | None = None,
    runs: list[dict[str, Any]] | None = None,
    extra_datasets: list[dict[str, Any]] | None = None,
) -> _Session:
    datasets = [dataset or _dataset(), *(extra_datasets or [])]
    return _Session(
        datasets_by_id={int(item["dataset_id"]): item for item in datasets},
        datasets_by_slug={str(item["slug"]): item for item in datasets},
        runs=runs or [],
    )


def _install_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        derived_data_backfill,
        "resolve_run_mzml_path",
        lambda _session, _dataset_id, run_id: (
            __import__("pathlib").Path(f"run-{run_id}.mzML"),
            False,
        ),
    )
    monkeypatch.setattr(
        derived_data_backfill,
        "resolve_run_source_path",
        lambda run: __import__("pathlib").Path(
            str(run["run_metadata"]["mzml_file_path"])
        ),
    )


def test_dataset_target_requires_id_or_slug() -> None:
    with pytest.raises(
        derived_data_backfill.DerivedDataBackfillArgumentError,
        match="required",
    ):
        derived_data_backfill.resolve_dataset(
            _session(),  # type: ignore[arg-type]
            dataset_id=None,
            slug=None,
        )


def test_dataset_target_supports_id_slug_and_matching_pair() -> None:
    session = _session()

    assert derived_data_backfill.resolve_dataset(
        session,  # type: ignore[arg-type]
        dataset_id=40,
        slug=None,
    )["slug"] == "bu"
    assert derived_data_backfill.resolve_dataset(
        session,  # type: ignore[arg-type]
        dataset_id=None,
        slug="bu",
    )["dataset_id"] == 40
    assert derived_data_backfill.resolve_dataset(
        session,  # type: ignore[arg-type]
        dataset_id=40,
        slug="bu",
    )["dataset_id"] == 40


def test_dataset_target_rejects_mismatched_id_and_slug() -> None:
    session = _session(extra_datasets=[_dataset(41, "other", "TOP_DOWN")])

    with pytest.raises(
        derived_data_backfill.DerivedDataBackfillArgumentError,
        match="different datasets",
    ):
        derived_data_backfill.resolve_dataset(
            session,  # type: ignore[arg-type]
            dataset_id=40,
            slug="other",
        )


def test_run_id_must_belong_to_dataset() -> None:
    with pytest.raises(
        derived_data_backfill.DerivedDataBackfillArgumentError,
        match="does not belong",
    ):
        derived_data_backfill.select_runs(
            _session(runs=[_run(1, dataset_id=41)]),  # type: ignore[arg-type]
            dataset_id=40,
            run_id=1,
        )


def test_default_processes_mzml_and_skips_non_mzml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_paths(monkeypatch)
    monkeypatch.setattr(derived_data_backfill, "_scan_index_state", lambda *_args, **_kwargs: "missing")
    monkeypatch.setattr(derived_data_backfill, "_chromatogram_state", lambda **_kwargs: "missing")
    generated_scan: list[int] = []
    generated_chrom: list[int] = []
    monkeypatch.setattr(
        derived_data_backfill,
        "_generate_scan_index",
        lambda _session, *, dataset_id, run_id, source_path: generated_scan.append(run_id),
    )
    monkeypatch.setattr(
        derived_data_backfill,
        "_generate_chromatogram",
        lambda *, dataset_id, run_id, source_path: generated_chrom.append(run_id),
    )

    result = derived_data_backfill.backfill_dataset_derived_data(
        _session(runs=[_run(1), _run(2, raw_format="tdf", mzml_path=None)]),  # type: ignore[arg-type]
        dataset_id=40,
    )

    assert generated_scan == [1]
    assert generated_chrom == [1]
    assert result.runs[0].scan_index_status == "generated"
    assert result.runs[0].chromatogram_summary_status == "generated"
    assert result.runs[1].scan_index_status == "skipped_not_mzml"
    assert result.runs[1].chromatogram_summary_status == "skipped_not_mzml"


def test_non_bu_only_generates_scan_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_paths(monkeypatch)
    monkeypatch.setattr(derived_data_backfill, "_scan_index_state", lambda *_args, **_kwargs: "missing")
    generated: list[str] = []
    monkeypatch.setattr(
        derived_data_backfill,
        "_generate_scan_index",
        lambda *_args, **_kwargs: generated.append("scan"),
    )
    monkeypatch.setattr(
        derived_data_backfill,
        "_generate_chromatogram",
        lambda *_args, **_kwargs: generated.append("chrom"),
    )

    result = derived_data_backfill.backfill_dataset_derived_data(
        _session(dataset=_dataset(40, "td", "TOP_DOWN"), runs=[_run(1)]),  # type: ignore[arg-type]
        dataset_id=40,
    )

    assert generated == ["scan"]
    assert result.runs[0].chromatogram_summary_status == "skipped_not_bu"


def test_ready_skips_and_force_regenerates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_paths(monkeypatch)
    monkeypatch.setattr(derived_data_backfill, "_scan_index_state", lambda *_args, **_kwargs: "ready")
    monkeypatch.setattr(derived_data_backfill, "_chromatogram_state", lambda **_kwargs: "ready")
    generated: list[str] = []
    monkeypatch.setattr(
        derived_data_backfill,
        "_generate_scan_index",
        lambda *_args, **_kwargs: generated.append("scan"),
    )
    monkeypatch.setattr(
        derived_data_backfill,
        "_generate_chromatogram",
        lambda *_args, **_kwargs: generated.append("chrom"),
    )
    session = _session(runs=[_run(1)])

    ready = derived_data_backfill.backfill_dataset_derived_data(
        session,  # type: ignore[arg-type]
        dataset_id=40,
    )
    forced = derived_data_backfill.backfill_dataset_derived_data(
        session,  # type: ignore[arg-type]
        dataset_id=40,
        force=True,
    )

    assert ready.runs[0].scan_index_status == "ready"
    assert ready.runs[0].chromatogram_summary_status == "ready"
    assert generated == ["scan", "chrom"]
    assert forced.runs[0].scan_index_status == "generated"
    assert forced.runs[0].chromatogram_summary_status == "generated"


@pytest.mark.parametrize("state", ["missing", "stale"])
def test_missing_or_stale_generates(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    _install_paths(monkeypatch)
    monkeypatch.setattr(derived_data_backfill, "_scan_index_state", lambda *_args, **_kwargs: state)
    monkeypatch.setattr(derived_data_backfill, "_chromatogram_state", lambda **_kwargs: state)
    generated: list[str] = []
    monkeypatch.setattr(
        derived_data_backfill,
        "_generate_scan_index",
        lambda *_args, **_kwargs: generated.append("scan"),
    )
    monkeypatch.setattr(
        derived_data_backfill,
        "_generate_chromatogram",
        lambda *_args, **_kwargs: generated.append("chrom"),
    )

    derived_data_backfill.backfill_dataset_derived_data(
        _session(runs=[_run(1)]),  # type: ignore[arg-type]
        dataset_id=40,
    )

    assert generated == ["scan", "chrom"]


def test_check_only_never_generates_even_with_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_paths(monkeypatch)
    monkeypatch.setattr(derived_data_backfill, "_scan_index_state", lambda *_args, **_kwargs: "stale")
    monkeypatch.setattr(derived_data_backfill, "_chromatogram_state", lambda **_kwargs: "missing")
    monkeypatch.setattr(derived_data_backfill, "_generate_scan_index", lambda *_args, **_kwargs: pytest.fail("write"))
    monkeypatch.setattr(derived_data_backfill, "_generate_chromatogram", lambda *_args, **_kwargs: pytest.fail("write"))

    result = derived_data_backfill.backfill_dataset_derived_data(
        _session(runs=[_run(1)]),  # type: ignore[arg-type]
        dataset_id=40,
        force=True,
        check_only=True,
    )

    assert result.runs[0].scan_index_status == "stale"
    assert result.runs[0].chromatogram_summary_status == "missing"


@pytest.mark.parametrize(
    ("only", "scan_status", "chrom_status"),
    [
        ("scan-index", "generated", "skipped_not_selected"),
        ("chromatogram", "skipped_not_selected", "generated"),
    ],
)
def test_only_selects_one_derived_type(
    monkeypatch: pytest.MonkeyPatch,
    only: str,
    scan_status: str,
    chrom_status: str,
) -> None:
    _install_paths(monkeypatch)
    monkeypatch.setattr(derived_data_backfill, "_scan_index_state", lambda *_args, **_kwargs: "missing")
    monkeypatch.setattr(derived_data_backfill, "_chromatogram_state", lambda **_kwargs: "missing")
    monkeypatch.setattr(derived_data_backfill, "_generate_scan_index", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(derived_data_backfill, "_generate_chromatogram", lambda *_args, **_kwargs: None)

    result = derived_data_backfill.backfill_dataset_derived_data(
        _session(runs=[_run(1)]),  # type: ignore[arg-type]
        dataset_id=40,
        only=only,  # type: ignore[arg-type]
    )

    assert result.runs[0].scan_index_status == scan_status
    assert result.runs[0].chromatogram_summary_status == chrom_status


def test_one_run_failure_does_not_stop_later_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_paths(monkeypatch)
    monkeypatch.setattr(derived_data_backfill, "_scan_index_state", lambda *_args, **_kwargs: "missing")
    processed: list[int] = []

    def generate(_session: Any, *, dataset_id: int, run_id: int, source_path: Any) -> None:
        processed.append(run_id)
        if run_id == 1:
            raise RuntimeError("broken run")

    monkeypatch.setattr(derived_data_backfill, "_generate_scan_index", generate)

    result = derived_data_backfill.backfill_dataset_derived_data(
        _session(runs=[_run(1), _run(2)]),  # type: ignore[arg-type]
        dataset_id=40,
        only="scan-index",
    )

    assert processed == [1, 2]
    assert result.runs[0].scan_index_status == "error"
    assert result.runs[0].error == "broken run"
    assert result.runs[1].scan_index_status == "generated"
    assert result.has_errors is True


def test_cli_returns_nonzero_for_argument_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Context:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, *_args: Any) -> None:
            return None

    monkeypatch.setattr(
        backfill_dataset_derived_data,
        "session_scope",
        lambda: _Context(),
    )

    exit_code = backfill_dataset_derived_data.main([])

    assert exit_code == 2
    assert "--dataset-id or --slug is required" in capsys.readouterr().err


def test_cli_returns_nonzero_when_any_run_failed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Context:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, *_args: Any) -> None:
            return None

    result = derived_data_backfill.DerivedDataBackfillResult(
        dataset_id=40,
        dataset_slug="bu",
        runs=[
            derived_data_backfill.DerivedDataRunResult(
                dataset_id=40,
                dataset_slug="bu",
                run_id=1,
                run_name="run-1",
                raw_format="mzml",
                mzml_path="run-1.mzML",
                scan_index_status="error",
                chromatogram_summary_status="skipped_not_selected",
                elapsed_ms=1.0,
                error="broken",
            )
        ],
    )
    monkeypatch.setattr(
        backfill_dataset_derived_data,
        "session_scope",
        lambda: _Context(),
    )
    monkeypatch.setattr(
        backfill_dataset_derived_data,
        "backfill_dataset_derived_data",
        lambda *_args, **_kwargs: result,
    )

    exit_code = backfill_dataset_derived_data.main(["--dataset-id", "40"])

    assert exit_code == 1
    assert '"error": "broken"' in capsys.readouterr().out
