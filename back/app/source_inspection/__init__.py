"""Bounded, Case-scoped source inspection public API."""

from .contracts import (
    BudgetUsage,
    InspectionLimits,
    InventoryItem,
    InventoryPage,
    ObservationArtifact,
    ObservationHashes,
    ObservationStatus,
    SniffResult,
    TruncationInfo,
)
from .inspectors import InspectionContext, SourceInspector
from .inventory import InvalidInventoryCursor, InventoryService, StaleInventoryCursor
from .observation import InspectionOutcome
from .paths import CasePathResolver, SourcePathError
from .registry import InspectorRegistry, inspect_file
from .sniff import sniff_file

__all__ = [
    "BudgetUsage",
    "CasePathResolver",
    "InspectionContext",
    "InspectionLimits",
    "InspectionOutcome",
    "InspectorRegistry",
    "InvalidInventoryCursor",
    "InventoryItem",
    "InventoryPage",
    "InventoryService",
    "ObservationArtifact",
    "ObservationHashes",
    "ObservationStatus",
    "SniffResult",
    "SourceInspector",
    "SourcePathError",
    "StaleInventoryCursor",
    "TruncationInfo",
    "inspect_file",
    "sniff_file",
]
