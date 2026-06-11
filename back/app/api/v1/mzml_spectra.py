"""Dynamic spectra API backed by indexed mzML access."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.mzml_scan_reader import (
    MzmlFileNotFoundError,
    MzmlIndexError,
    MzmlMappingError,
    RunNotFoundError,
    SpectrumNotFoundError,
    UnsupportedMzmlError,
    get_spectrum_by_scan,
)
from app.spectrum_memory import release_dataset


router = APIRouter(tags=["mzml-spectra"])


@router.get(
    "/datasets/{dataset_id}/runs/{run_id}/spectra/{scan_number}",
    response_model=dict[str, Any],
)
def mzml_spectrum(
    dataset_id: int,
    run_id: int,
    scan_number: int,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        spec, path_committed = get_spectrum_by_scan(session, dataset_id, run_id, scan_number)
    except (RunNotFoundError, MzmlFileNotFoundError, SpectrumNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except MzmlMappingError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except UnsupportedMzmlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except MzmlIndexError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc

    if path_committed:
        release_dataset(dataset_id)

    return {
        "run_id": run_id,
        "dataset_id": dataset_id,
        **spec,
    }
