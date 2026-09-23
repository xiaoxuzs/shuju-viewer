"""Format-neutral, declarative ingestion contracts and execution helpers."""

from .contracts import DeclarativeImportPlan
from .executor import DeclarativeExecutionError, execute_plan_to_semantic_dataset
from .preflight import (
    DeclarativePreflightReport,
    build_declarative_ingest_capabilities,
    preflight_declarative_plan,
)
from .semantic_schema import SemanticDataset
from .zp_artifact import DeclarativeZpArtifact, build_declarative_zp_artifact, read_semantic_zp

__all__ = [
    "DeclarativeImportPlan",
    "DeclarativeExecutionError",
    "DeclarativePreflightReport",
    "DeclarativeZpArtifact",
    "SemanticDataset",
    "build_declarative_zp_artifact",
    "build_declarative_ingest_capabilities",
    "execute_plan_to_semantic_dataset",
    "preflight_declarative_plan",
    "read_semantic_zp",
]
