"""聚合 v1 子路由，统一挂载在 ``/api/v1`` 前缀下。"""

from fastapi import APIRouter

from app.api.v1 import datasets, imports, lcms, mzml_spectra, proteins, proteoforms, prsms, spectra

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(datasets.router)
api_router.include_router(imports.router)
api_router.include_router(proteins.router)
api_router.include_router(proteoforms.router)
api_router.include_router(prsms.router)
api_router.include_router(spectra.router)
api_router.include_router(mzml_spectra.router)
api_router.include_router(lcms.router)
