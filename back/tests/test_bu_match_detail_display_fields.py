from __future__ import annotations

from typing import Any

from app.bu.services import lists_service


class _EmptyMappings:
    def mappings(self) -> "_EmptyMappings":
        return self

    def all(self) -> list[Any]:
        return []


class _Session:
    def execute(self, *_args: Any, **_kwargs: Any) -> _EmptyMappings:
        return _EmptyMappings()


def _match(scan_number: int) -> dict[str, Any]:
    return {
        "match_id": 1,
        "run_id": 10,
        "run_name": "run.mzML",
        "entity_id": 5,
        "sequence": "PEPTIDE",
        "modified_sequence": None,
        "precursor_mz": 477.3051,
        "precursor_charge": 2,
        "retention_time": 92.46,
        "experimental_mass": None,
        "q_value": 0.001,
        "score": 10.0,
        "intensity": 1000.0,
        "is_decoy_match": False,
        "scan_number": scan_number,
        "search_engine": "DIA-NN",
        "spectrum_native_id": None,
        "ms_level": 2,
        "file_path": "run.mzML",
        "run_metadata": {"raw_format": "mzml", "diann_run_name": "run"},
        "extra_metadata": {"rt_start": 92.15, "rt_stop": 93.08},
    }


def test_match_detail_keeps_scan_sentinel_and_adds_display_safe_fields() -> None:
    out = lists_service.get_match_detail(
        _Session(),  # type: ignore[arg-type]
        {"dataset_id": 39, "slug": "demo"},
        _match(-1),
    )

    assert out.scan_number == -1
    assert out.scan_available is False
    assert out.scan_unavailable_reason == "Not available from imported match metadata"
    assert out.identification_rt_apex == 92.46
    assert out.rt_window.rt_apex == 92.46


def test_match_detail_marks_real_imported_scan_as_available() -> None:
    out = lists_service.get_match_detail(
        _Session(),  # type: ignore[arg-type]
        {"dataset_id": 39, "slug": "demo"},
        _match(70714),
    )

    assert out.scan_number == 70714
    assert out.scan_available is True
    assert out.scan_unavailable_reason is None
