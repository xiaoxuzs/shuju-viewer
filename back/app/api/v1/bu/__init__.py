"""Bottom-Up runtime API routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.bu import chromatogram, lists, matches, ms2_annotations, overview, proteins

router = APIRouter(tags=["bottom-up"])
router.include_router(overview.router)
router.include_router(lists.router)
router.include_router(matches.router)
router.include_router(ms2_annotations.router)
router.include_router(proteins.router)
router.include_router(chromatogram.router)

