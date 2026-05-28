"""MS1 / MS2 raw spectrum JSON API: reads TopFD spectrum files from the universal dataset root."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.universal_compat import require_dataset
from app.services.spectrum_cache import (
    SpectrumNotFoundError,
    get_ms1_spectrum,
    get_ms2_spectrum,
)

router = APIRouter(tags=["spectra"])


@router.get("/datasets/{slug}/spectra/ms1/{spec_id}", response_model=dict[str, Any])
def ms1_spectrum(slug: str, spec_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Return the MS1 spectrum object; use ``datasets.source_root`` first, else fall back to ``DATA_ROOT/slug``."""
    dataset = require_dataset(session, slug)
    try:
        return get_ms1_spectrum(dataset["slug"], dataset["source_root"], spec_id)
    except SpectrumNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/datasets/{slug}/spectra/ms2/{spec_id}", response_model=dict[str, Any])
def ms2_spectrum(slug: str, spec_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    """Return the MS2 spectrum object; resolve like MS1 with subpath ``topfd/ms2_json``."""
    dataset = require_dataset(session, slug)
    try:
        return get_ms2_spectrum(dataset["slug"], dataset["source_root"], spec_id)
    except SpectrumNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
