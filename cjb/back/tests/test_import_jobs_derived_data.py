from __future__ import annotations

from app.services import import_jobs
from app.services.derived_data_backfill import (
    DerivedDataBackfillResult,
    DerivedDataRunResult,
)


def _result(*, error: str | None = None) -> DerivedDataBackfillResult:
    return DerivedDataBackfillResult(
        dataset_id=40,
        dataset_slug="bu",
        runs=[
            DerivedDataRunResult(
                dataset_id=40,
                dataset_slug="bu",
                run_id=39,
                run_name="run-39",
                raw_format="mzml",
                mzml_path="run-39.mzML",
                scan_index_status="error" if error else "generated",
                chromatogram_summary_status="generated",
                elapsed_ms=1.0,
                error=error,
            )
        ],
    )


def test_post_import_derived_data_runs_after_import_without_warning(
    monkeypatch,
) -> None:
    updates: list[dict[str, object]] = []
    monkeypatch.setattr(
        import_jobs,
        "_update_job",
        lambda _job_id, **kwargs: updates.append(kwargs),
    )
    monkeypatch.setattr(
        import_jobs,
        "build_post_import_derived_data",
        lambda dataset_id: _result(),
    )

    warning = import_jobs._run_post_import_derived_data("job-1", 40)

    assert warning is None
    assert updates == [
        {
            "stage": "derived_data",
            "stage_label": "Building derived data",
            "stage_detail": (
                "Generating mzML scan indexes and applicable chromatogram summaries..."
            ),
            "message": "Building derived data...",
            "progress": 99.6,
        }
    ]


def test_post_import_derived_data_run_error_is_a_recoverable_warning(
    monkeypatch,
) -> None:
    monkeypatch.setattr(import_jobs, "_update_job", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        import_jobs,
        "build_post_import_derived_data",
        lambda dataset_id: _result(error="broken index"),
    )

    warning = import_jobs._run_post_import_derived_data("job-1", 40)

    assert warning is not None
    assert "run(s): 39" in warning
    assert (
        "python scripts/backfill_dataset_derived_data.py --dataset-id 40"
        in warning
    )


def test_post_import_derived_data_global_failure_is_a_recoverable_warning(
    monkeypatch,
) -> None:
    monkeypatch.setattr(import_jobs, "_update_job", lambda *_args, **_kwargs: None)

    def fail(_dataset_id: int) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(import_jobs, "build_post_import_derived_data", fail)

    warning = import_jobs._run_post_import_derived_data("job-1", 40)

    assert warning is not None
    assert "database unavailable" in warning
    assert (
        "python scripts/backfill_dataset_derived_data.py --dataset-id 40"
        in warning
    )
