from __future__ import annotations

from typing import Any

import pytest

from app.bu.services import lists_service


class _EmptyMappings:
    def mappings(self) -> "_EmptyMappings":
        return self

    def all(self) -> list[Any]:
        return []


class _Session:
    def execute(self, *_args: Any, **_kwargs: Any) -> _EmptyMappings:
        return _EmptyMappings()


class _ProteinRows(_EmptyMappings):
    def all(self) -> list[dict[str, Any]]:
        return [
            {
                "id": 7,
                "accession": "P-UNKNOWN",
                "gene_name": None,
                "description": None,
                "is_decoy": False,
                "is_decoy_state": "MISSING",
                "protein_group": None,
                "peptide_count": 1,
                "match_count": 1,
                "best_q_value": None,
                "pg_max_lfq": None,
                "pg_q_value": None,
                "pg_quantity": None,
            }
        ]


class _ProteinListSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def scalar(self, statement: Any, _params: dict[str, Any]) -> int:
        self.statements.append(str(statement))
        return 1

    def execute(self, statement: Any, _params: dict[str, Any]) -> _ProteinRows:
        self.statements.append(str(statement))
        return _ProteinRows()


class _MatchRows(_EmptyMappings):
    def all(self) -> list[dict[str, Any]]:
        return [
            {
                "id": 11,
                "run_id": 10,
                "run_name": "run.mzML",
                "peptide_id": 5,
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
                "is_decoy_state": "AMBIGUOUS",
                "scan_number": -1,
                "protein_group": None,
                "genes": None,
                "search_engine": None,
            }
        ]


class _MatchListSession(_ProteinListSession):
    def execute(self, statement: Any, _params: dict[str, Any]) -> _MatchRows:
        self.statements.append(str(statement))
        return _MatchRows()


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


def test_match_detail_keeps_scan_sentinel_and_adds_display_safe_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lists_service, "get_binary_bottom_up_match", lambda *_args, **_kwargs: None)
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
    assert out.is_decoy_match is False
    assert out.is_decoy_state == "DIRECT"


def test_match_detail_marks_real_imported_scan_as_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lists_service, "get_binary_bottom_up_match", lambda *_args, **_kwargs: None)
    out = lists_service.get_match_detail(
        _Session(),  # type: ignore[arg-type]
        {"dataset_id": 39, "slug": "demo"},
        _match(70714),
    )

    assert out.scan_number == 70714
    assert out.scan_available is True
    assert out.scan_unavailable_reason is None


@pytest.mark.parametrize("state", ["MISSING", "AMBIGUOUS"])
def test_match_detail_does_not_expose_storage_false_as_a_target_call(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    monkeypatch.setattr(lists_service, "get_binary_bottom_up_match", lambda *_args, **_kwargs: None)
    match = _match(-1)
    match["extra_metadata"] = {"is_decoy_state": state}

    out = lists_service.get_match_detail(
        _Session(),  # type: ignore[arg-type]
        {"dataset_id": 39, "slug": "demo"},
        match,
    )

    assert out.is_decoy_match is None
    assert out.is_decoy_state == state


def test_default_protein_list_keeps_unknown_decoys_visible_without_calling_them_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _ProteinListSession()
    monkeypatch.setattr(lists_service, "_use_binary_entities", lambda *_args: False)

    page = lists_service.list_proteins(
        session,  # type: ignore[arg-type]
        {"dataset_id": 39},
        page=1,
        page_size=20,
        search=None,
        decoy=False,
    )

    assert page.total == 1
    assert page.items[0].accession == "P-UNKNOWN"
    assert page.items[0].is_decoy is None
    assert page.items[0].is_decoy_state == "MISSING"
    assert all("is_decoy_state" in statement for statement in session.statements)


def test_default_match_list_keeps_ambiguous_decoys_visible_without_calling_them_targets() -> None:
    session = _MatchListSession()

    page = lists_service.list_matches(
        session,  # type: ignore[arg-type]
        {"dataset_id": 39, "extra_metadata": {}},
        page=1,
        page_size=20,
        q_max=None,
        run_id=None,
        peptide_id=None,
        protein_id=None,
        charge=None,
        search=None,
        decoy=False,
        sort="q_value",
        order="asc",
    )

    assert page.total == 1
    assert page.items[0].sequence == "PEPTIDE"
    assert page.items[0].is_decoy_match is None
    assert page.items[0].is_decoy_state == "AMBIGUOUS"
    assert all("is_decoy_state" in statement for statement in session.statements)
