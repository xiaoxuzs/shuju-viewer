"""Managed .zp conversion jobs and artifact metadata for Viewer.

The module owns orchestration only. Final .zp bytes are produced by Viewer's
binary layer in an isolated worker process.
"""

from app.zp_conversion.contracts import ZpConversionError, ZpConversionJob
from app.zp_conversion.service import cancel_conversion, enqueue_conversion, get_conversion_job, run_conversion_job

__all__ = [
    "ZpConversionError",
    "ZpConversionJob",
    "cancel_conversion",
    "enqueue_conversion",
    "get_conversion_job",
    "run_conversion_job",
]
