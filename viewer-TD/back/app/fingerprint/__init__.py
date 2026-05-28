"""Dataset duplicate detection via fast metadata fingerprint (no file reads)."""

from app.fingerprint.dataset_metadata_fingerprint import (
    MetadataFingerprintResult,
    compute_dataset_metadata_fingerprint,
)

__all__ = [
    "MetadataFingerprintResult",
    "compute_dataset_metadata_fingerprint",
]
