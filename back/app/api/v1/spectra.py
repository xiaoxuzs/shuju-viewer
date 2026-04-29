"""MS1 / MS2 原始谱 JSON API：从 universal dataset root 读取 TopFD spectrum files."""

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
    """返回 MS1 谱对象；路径相对 ``datasets.source_root`` 下 ``topfd/ms1_json``。"""
    dataset = require_dataset(session, slug)
    try:
        return get_ms1_spectrum(dataset["source_root"], spec_id)
    except SpectrumNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/datasets/{slug}/spectra/ms2/{spec_id}", response_model=dict[str, Any])
def ms2_spectrum(slug: str, spec_id: int, session: Session = Depends(get_db)) -> dict[str, Any]:
    """返回 MS2 谱对象；根目录同上，子路径为 ``topfd/ms2_json``。"""
    dataset = require_dataset(session, slug)
    try:
        return get_ms2_spectrum(dataset["source_root"], spec_id)
    except SpectrumNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
