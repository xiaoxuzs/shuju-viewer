from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent_import.api import _analysis_category
from app.agent_import.errors import AgentImportError
from app.agent_import.schemas import AgentCaseFromPathIn
from app.api.v1 import build_api_router


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Top-Down", "TOP_DOWN"), ("Bottom-Up", "BOTTOM_UP"), ("Spectra Only", "SPECTRA_ONLY")],
)
def test_unknown_import_data_type_maps_to_the_binary_contract(value: str, expected: str) -> None:
    assert _analysis_category(value) == expected


def test_unknown_import_preserves_trimmed_free_form_analysis_category() -> None:
    assert _analysis_category("  DIA-CLIP quantitative imaging  ") == "DIA-CLIP quantitative imaging"


def test_unknown_import_rejects_blank_analysis_category() -> None:
    with pytest.raises(AgentImportError):
        _analysis_category("   ")


@pytest.mark.parametrize("value", ["DIA\nCLIP", "x" * 81])
def test_unknown_import_schema_rejects_unsafe_analysis_category(value: str) -> None:
    with pytest.raises(ValidationError):
        AgentCaseFromPathIn(
            source_path="C:/dataset",
            data_type=value,
            format_name="custom",
        )


def test_agent_case_routes_are_registered() -> None:
    paths = {route.path for route in build_api_router().routes}

    assert "/api/v1/agent-import-cases/from-path" in paths
    assert "/api/v1/agent-import-cases/{case_id}/review/approve" in paths
