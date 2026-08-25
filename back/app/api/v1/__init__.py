"""聚合 v1 子路由，统一挂载在 ``/api/v1`` 前缀下。"""

from fastapi import APIRouter

from app.core.config import settings
from app.api.v1 import (
    bu,
    datasets,
    import_uploads,
    imports,
    mzml_spectra,
    proteins,
    proteoforms,
    prsms,
    spectra,
)


def build_api_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    router.include_router(datasets.router)
    router.include_router(imports.router)
    router.include_router(import_uploads.router)
    router.include_router(proteins.router)
    router.include_router(proteoforms.router)
    router.include_router(prsms.router)
    router.include_router(spectra.router)
    router.include_router(mzml_spectra.router)
    router.include_router(bu.router)
    if settings.zp_management_enabled:
        # ZP endpoints are part of the normal binary main path; the flag is an emergency fallback.
        from app.api.v1 import zp_conversions

        router.include_router(zp_conversions.router)
        if settings.zp_import_conversion_enabled:
            from app.api.v1 import agent_zp

            router.include_router(agent_zp.router)
    return router


api_router = build_api_router()
