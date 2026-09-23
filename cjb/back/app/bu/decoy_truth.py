"""Truth-preserving helpers for legacy non-null decoy columns."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal, cast


DecoyTruthState = Literal["DIRECT", "MISSING", "AMBIGUOUS"]

_DECOY_TRUTH_STATES = frozenset({"DIRECT", "MISSING", "AMBIGUOUS"})


def roll_up_decoy_values(values: Iterable[bool | None]) -> tuple[bool, DecoyTruthState]:
    """Return the storage value plus its scientific state for linked records."""

    observed = tuple(values)
    known = tuple(value for value in observed if value is not None)
    if not known:
        return False, "MISSING"
    if len(known) != len(observed):
        return False, "AMBIGUOUS"
    return all(known), "DIRECT"


def decoy_value_for_api(storage_value: Any, raw_state: Any) -> tuple[bool | None, DecoyTruthState]:
    """Hide a non-null storage placeholder unless its state is DIRECT.

    Rows written before explicit truth states existed are treated as DIRECT so
    their historical boolean semantics remain unchanged.  An invalid explicit
    state is conservative rather than silently becoming a target assertion.
    """

    if raw_state is None:
        state: DecoyTruthState = "DIRECT" if storage_value is not None else "MISSING"
    else:
        normalized = str(raw_state).upper()
        state = cast(DecoyTruthState, normalized) if normalized in _DECOY_TRUTH_STATES else "AMBIGUOUS"
    if state != "DIRECT":
        return None, state
    return bool(storage_value), state


def confirmed_decoy_sql(value_expression: str, metadata_expression: str) -> str:
    """SQL predicate that is true only for a scientifically confirmed decoy."""

    return (
        f"(COALESCE({value_expression}, false) = true AND "
        f"COALESCE(jsonb_extract_path_text({metadata_expression}, 'is_decoy_state'), 'DIRECT') = 'DIRECT')"
    )
