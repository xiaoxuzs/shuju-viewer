from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.v1 import api_router
from app.bu import deps
from app.services.spectrum_memory_wiring import _is_mzml_memory_dataset


def test_require_bu_dataset_rejects_top_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        deps,
        "require_dataset",
        lambda _session, _slug: {"dataset_id": 1, "analysis_mode": "TOP_DOWN"},
    )

    with pytest.raises(HTTPException) as exc:
        deps.require_bu_dataset(None, "td")  # type: ignore[arg-type]

    assert exc.value.status_code == 404
    assert exc.value.detail == "not_bottom_up"


def test_mixed_dataset_is_mzml_resident_candidate() -> None:
    assert _is_mzml_memory_dataset({"spectra_source": "mixed"}) is True
    assert _is_mzml_memory_dataset({"spectra_source": "tdf_memory"}) is False


def test_bu_routes_have_no_bu_url_prefix() -> None:
    paths = {route.path for route in api_router.routes}
    assert "/api/v1/datasets/{slug}/overview" in paths
    assert "/api/v1/datasets/{slug}/matches" in paths
    assert "/api/v1/datasets/{slug}/matches/{match_id}/product-xics" in paths
    assert all("/bu/" not in path for path in paths)
