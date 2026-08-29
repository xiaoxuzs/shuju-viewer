from __future__ import annotations

import pytest

from app.agent_import.api import _analysis_category
from app.agent_import.errors import AgentImportError
from app.api.v1 import build_api_router


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Top-Down", "TOP_DOWN"), ("Bottom-Up", "BOTTOM_UP"), ("Spectra Only", "SPECTRA_ONLY")],
)
def test_unknown_import_data_type_maps_to_the_binary_contract(value: str, expected: str) -> None:
    assert _analysis_category(value) == expected


def test_unknown_import_rejects_free_form_analysis_categories() -> None:
    with pytest.raises(AgentImportError):
        _analysis_category("DIA-CLIP")


def test_agent_case_routes_are_registered() -> None:
    paths = {route.path for route in build_api_router().routes}

    assert "/api/v1/agent-import-cases/from-path" in paths
    assert "/api/v1/agent-import-cases/{case_id}/review/approve" in paths
