"""LC-MS 3D map builders.

This package is intentionally independent from FastAPI and SQLAlchemy. API
routes pass plain request data in; providers return normalized spectrum
frames; binning turns those frames into a bounded point cloud for WebGL.
"""

from app.lcms_map.contracts import LcmsMapRequest, SpectrumFrame
from app.lcms_map.service import build_lcms_map

__all__ = ["LcmsMapRequest", "SpectrumFrame", "build_lcms_map"]
