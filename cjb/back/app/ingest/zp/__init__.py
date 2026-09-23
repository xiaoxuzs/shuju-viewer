"""Version-neutral projection from validated ZP payloads into Viewer tables."""

from .semantic_projection import SemanticProjectionStats, project_semantic_zp

__all__ = ["SemanticProjectionStats", "project_semantic_zp"]
