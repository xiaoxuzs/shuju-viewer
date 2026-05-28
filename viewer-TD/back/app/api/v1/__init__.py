"""Aggregate v1 sub-routers under the ``/api/v1`` prefix."""

from fastapi import APIRouter

from app.api.v1 import datasets, imports, mzml_spectra, proteins, proteoforms, prsms, spectra

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(datasets.router)
api_router.include_router(imports.router)
api_router.include_router(proteins.router)
api_router.include_router(proteoforms.router)
api_router.include_router(prsms.router)
api_router.include_router(spectra.router)
api_router.include_router(mzml_spectra.router)
