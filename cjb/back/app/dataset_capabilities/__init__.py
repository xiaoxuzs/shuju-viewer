"""Public API for evidence-backed dataset capability reports."""

from .catalog import VIEWER_VIEW_CATALOG, ViewerViewSpec, get_view_catalog
from .compiler import (
    compile_capability_report,
    compile_legacy_capability_report,
    validate_capability_report,
)
from .contracts import (
    CapabilityAmbiguity,
    CapabilityWarning,
    DatasetCapabilityReport,
    EntityCapability,
    FactState,
    MissingInput,
    ValidatedDatasetFacts,
    ViewAvailability,
    ViewCapability,
    ViewRequirement,
)
from .semantic_compiler import compile_semantic_capability_report

__all__ = [
    "CapabilityAmbiguity",
    "CapabilityWarning",
    "DatasetCapabilityReport",
    "EntityCapability",
    "FactState",
    "MissingInput",
    "ValidatedDatasetFacts",
    "VIEWER_VIEW_CATALOG",
    "ViewAvailability",
    "ViewCapability",
    "ViewRequirement",
    "ViewerViewSpec",
    "compile_capability_report",
    "compile_legacy_capability_report",
    "compile_semantic_capability_report",
    "get_view_catalog",
    "validate_capability_report",
]
