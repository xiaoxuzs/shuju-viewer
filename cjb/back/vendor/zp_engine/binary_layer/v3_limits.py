from __future__ import annotations

from .v2_arrays_reader import ZpV2ArrayReadLimits
from .v2_arrays_writer import ZpV2ArrayWriteLimits
from .v2_validator import ZpV2ValidationLimits


V3_ARRAY_WRITE_LIMITS = ZpV2ArrayWriteLimits(
    max_arrays_block_length=128 * 1024**3,
    max_directory_length=2 * 1024**3,
    max_entry_count=4_000_000,
    max_array_value_count=1_000_000_000,
    max_array_id_utf8_length=4096,
    max_payload_length=128 * 1024**3,
)

V3_ARRAY_READ_LIMITS = ZpV2ArrayReadLimits(
    max_arrays_block_length=128 * 1024**3,
    max_directory_length=2 * 1024**3,
    max_entry_count=4_000_000,
    max_array_value_count=1_000_000_000,
    max_array_id_utf8_length=4096,
    max_payload_length=128 * 1024**3,
    max_decoded_memory=8 * 1024**3,
)

V3_VALIDATION_LIMITS = ZpV2ValidationLimits(
    max_arrays_block_length=128 * 1024**3,
    max_top_directory_length=64 * 1024**2,
    max_array_directory_length=2 * 1024**3,
    max_entry_count=4_000_000,
    max_array_value_count=1_000_000_000,
    max_array_id_utf8_length=4096,
    max_payload_length=128 * 1024**3,
    max_work_memory=8 * 1024**3,
    chunk_size=4 * 1024**2,
)
