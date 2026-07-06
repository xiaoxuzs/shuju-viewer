"""Route-matching regression tests for the run chromatogram endpoints.

Two endpoints share the ``/datasets/.../runs/.../chromatogram`` shape:

* ``mzml_spectra`` exposes the numeric ``/datasets/{dataset_id:int}/...`` route.
* the Bottom-Up module exposes the ``/datasets/{slug}/...`` route.

Because ``mzml_spectra`` is registered first, its path must be numeric-only so a
slug such as ``dia-shuju`` falls through to the Bottom-Up route instead of
failing ``int`` parsing with a 422. These tests pin that behaviour without a
database, on-disk derived files, or the optional ``httpx`` test client.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException, status
from starlette.routing import Match

from app.api.v1.bu import chromatogram as bu_chromatogram
from app.main import app
from app.schemas import BuChromatogramOut


def _matched_route_name(path: str, method: str = "GET") -> str | None:
    """Return the name of the first fully matching route, mirroring routing order."""
    scope = {"type": "http", "method": method, "path": path, "headers": []}
    for route in app.routes:
        match, _child = route.matches(scope)
        if match == Match.FULL:
            return route.name
    return None


def test_numeric_dataset_id_matches_mzml_chromatogram_route() -> None:
    assert (
        _matched_route_name("/api/v1/datasets/11/runs/13/chromatogram")
        == "mzml_run_chromatogram"
    )


def test_slug_dataset_matches_bu_chromatogram_route() -> None:
    # The slug must not be captured by the numeric mzml route (which caused 422).
    assert (
        _matched_route_name("/api/v1/datasets/dia-shuju/runs/13/chromatogram")
        == "chromatogram"
    )


@pytest.mark.parametrize("chrom_type", ["tic", "bpc"])
def test_bu_handler_passes_tic_and_bpc_through(
    monkeypatch: pytest.MonkeyPatch, chrom_type: str
) -> None:
    seen: dict[str, Any] = {}

    def get_chromatogram(_session: Any, dataset: Any, run_id: int, *, chrom_type: str) -> BuChromatogramOut:
        seen.update(dataset=dataset, run_id=run_id, chrom_type=chrom_type)
        return BuChromatogramOut(
            type=chrom_type,  # type: ignore[arg-type]
            rt=[1.0],
            intensity=[9.0],
            downsampled=False,
            point_count_original=1,
        )

    monkeypatch.setattr(
        bu_chromatogram,
        "require_bu_dataset",
        lambda _session, slug: {"dataset_id": 11, "slug": slug, "analysis_mode": "BOTTOM_UP"},
    )
    monkeypatch.setattr(bu_chromatogram.chromatogram_service, "get_chromatogram", get_chromatogram)

    out = bu_chromatogram.chromatogram("dia-shuju", 13, chrom_type, object())  # type: ignore[arg-type]

    assert seen["chrom_type"] == chrom_type
    assert seen["run_id"] == 13
    assert out.type == chrom_type


def test_bu_handler_propagates_409_for_missing_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    def get_chromatogram(*_args: Any, **_kwargs: Any) -> BuChromatogramOut:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="chromatogram_summary_missing")

    monkeypatch.setattr(
        bu_chromatogram,
        "require_bu_dataset",
        lambda _session, slug: {"dataset_id": 11, "slug": slug, "analysis_mode": "BOTTOM_UP"},
    )
    monkeypatch.setattr(bu_chromatogram.chromatogram_service, "get_chromatogram", get_chromatogram)

    with pytest.raises(HTTPException) as exc_info:
        bu_chromatogram.chromatogram("dia-shuju", 13, "tic", object())  # type: ignore[arg-type]

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert exc_info.value.detail == "chromatogram_summary_missing"
