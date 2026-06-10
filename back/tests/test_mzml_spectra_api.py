from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.api.v1 import mzml_spectra as mzml_spectra_api


class _OneRowResult:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    def mappings(self) -> "_OneRowResult":
        return self

    def one_or_none(self) -> dict[str, Any]:
        return self._row


class _OneRowSession:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    def execute(self, *_args: Any, **_kwargs: Any) -> _OneRowResult:
        return _OneRowResult(self._row)


def test_mzml_spectrum_explicitly_loads_dataset_when_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mzml_path = Path(__file__).resolve()
    session = _OneRowSession(
        {
            "run_id": 10,
            "dataset_id": 39,
            "file_name": "run.mzML",
            "run_metadata": {"mzml_file_path": str(mzml_path)},
        }
    )
    loaded: list[tuple[Any, int]] = []

    monkeypatch.setattr(
        mzml_spectra_api.spectrum_memory_wiring,
        "ensure_mzml_dataset_resident",
        lambda current_session, dataset_id: loaded.append((current_session, dataset_id)),
    )
    monkeypatch.setattr(
        mzml_spectra_api,
        "get_mzml_spectrum",
        lambda dataset_id, run_id, scan_number: {
            "scan": scan_number,
            "ms_level": 2,
            "mz": [100.0],
            "intensity": [200.0],
        },
    )

    out = mzml_spectra_api.mzml_spectrum(39, 10, 123, session)  # type: ignore[arg-type]

    assert loaded == [(session, 39)]
    assert out["dataset_id"] == 39
    assert out["run_id"] == 10
    assert out["scan"] == 123
