"""Explicit q-value filtering without substituting missing measurements."""

import math
from typing import Any


def resolve_q_value_cutoff(dataset: dict[str, Any], q_max: float | None, *, enabled: bool = True) -> float | None:
    if not enabled:
        return None
    metadata = dataset.get("extra_metadata")
    value = q_max if q_max is not None else (metadata.get("q_value_cutoff") if isinstance(metadata, dict) else None)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0 <= number <= 1 else None
