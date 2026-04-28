"""MS1 / MS2 原始谱 JSON API：从数据集磁盘目录读取 TopFD 导出的 ``spectrum*.js``。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_dataset
from app.models import Dataset
from app.services.spectrum_cache import (
    SpectrumNotFoundError,
    get_ms1_spectrum,
    get_ms2_spectrum,
)

router = APIRouter(tags=["spectra"])


@router.get("/datasets/{slug}/spectra/ms1/{spec_id}", response_model=dict[str, Any])
def ms1_spectrum(spec_id: int, dataset: Dataset = Depends(get_dataset)) -> dict[str, Any]:
    """返回 MS1 谱对象；路径相对 ``dataset.source_path`` 下 ``topfd/ms1_json``。文件缺失时 404。"""
    try:
        return get_ms1_spectrum(dataset.source_path, spec_id)
    except SpectrumNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/datasets/{slug}/spectra/ms2/{spec_id}", response_model=dict[str, Any])
def ms2_spectrum(spec_id: int, dataset: Dataset = Depends(get_dataset)) -> dict[str, Any]:
    """返回 MS2 谱对象；根目录同上，子路径为 ``topfd/ms2_json``。"""
    try:
        return get_ms2_spectrum(dataset.source_path, spec_id)
    except SpectrumNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
