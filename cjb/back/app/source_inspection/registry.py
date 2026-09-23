"""Inspector selection with explicit unsupported and invalid observations."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .budget import BudgetTracker, InspectionBudgetExceeded
from .contracts import InspectionLimits, ObservationArtifact
from .inspectors import (
    DelimitedInspector,
    FastaInspector,
    InspectionContext,
    JsonInspector,
    JsonLinesInspector,
    MzmlInspector,
    ParquetInspector,
    SourceInspector,
    XmlInspector,
)
from .observation import InspectionOutcome, finalize_observation
from .paths import CasePathResolver
from .sniff import SNIFFER_VERSION, sniff_resolved


REGISTRY_VERSION = "1.0.0"


class InspectorRegistry:
    """A small dependency-injection boundary for source format inspectors."""

    def __init__(self, inspectors: Iterable[SourceInspector] = ()) -> None:
        self._inspectors: dict[str, SourceInspector] = {}
        for inspector in inspectors:
            self.register(inspector)

    @classmethod
    def default(cls) -> "InspectorRegistry":
        return cls(
            [
                DelimitedInspector(),
                JsonLinesInspector(),
                ParquetInspector(),
                JsonInspector(),
                XmlInspector(),
                MzmlInspector(),
                FastaInspector(),
            ]
        )

    @property
    def formats(self) -> frozenset[str]:
        return frozenset(self._inspectors)

    def register(self, inspector: SourceInspector) -> None:
        for source_format in inspector.formats:
            if source_format in self._inspectors:
                raise ValueError(f"source inspector already registered for format: {source_format}")
        for source_format in inspector.formats:
            self._inspectors[source_format] = inspector

    def inspect(
        self,
        case_root: str | Path,
        relative_path: str,
        *,
        limits: InspectionLimits | None = None,
    ) -> ObservationArtifact:
        resolver = CasePathResolver(case_root)
        path = resolver.resolve_file(relative_path)
        relative = resolver.relative(path)
        tracker = BudgetTracker(limits or InspectionLimits())
        try:
            sniff, _whole_hash, sampled_only = sniff_resolved(path, relative, tracker)
        except InspectionBudgetExceeded:
            return finalize_observation(
                path=path,
                relative_path=relative,
                detected_format="unknown",
                inspector_id="source-inspector-registry",
                inspector_version=REGISTRY_VERSION,
                tracker=tracker,
                outcome=InspectionOutcome(
                    status="PARTIAL",
                    facts={"file_content_returned": False},
                    warnings=["The inspection budget was exhausted before file classification completed."],
                    truncation_reasons=["sniff_incomplete"],
                ),
            )

        inspector = self._inspectors.get(sniff.detected_format)
        if inspector is None:
            reason = (
                "The file is a recognized but unsupported or closed binary format."
                if sniff.is_binary
                else "No safe source inspector is registered for the detected format."
            )
            return finalize_observation(
                path=path,
                relative_path=relative,
                detected_format=sniff.detected_format,
                inspector_id="source-inspector-registry",
                inspector_version=REGISTRY_VERSION,
                tracker=tracker,
                outcome=InspectionOutcome(
                    status="UNSUPPORTED",
                    facts={
                        "sniff": sniff.model_dump(mode="json"),
                        "sniffer_version": SNIFFER_VERSION,
                        "file_content_returned": False,
                    },
                    warnings=[reason],
                    truncation_reasons=["content_sampled_by_design"] if sampled_only else [],
                ),
            )

        context = InspectionContext(path=path, relative_path=relative, sniff=sniff, tracker=tracker)
        try:
            inspected = inspector.inspect(context)
        except InspectionBudgetExceeded:
            inspected = InspectionOutcome(
                status="PARTIAL",
                warnings=["The inspector stopped at its configured resource budget."],
                truncation_reasons=["inspector_budget_exhausted"],
            )
        except Exception as exc:  # registry boundary must not turn a parser failure into success
            inspected = InspectionOutcome(
                status="INVALID",
                warnings=[f"The source inspector failed safely: {str(exc)[:300]}"],
            )
        facts = {
            "sniff": sniff.model_dump(mode="json"),
            "sniffer_version": SNIFFER_VERSION,
            **inspected.facts,
        }
        outcome = InspectionOutcome(
            status=inspected.status,
            facts=facts,
            warnings=inspected.warnings,
            truncation_reasons=inspected.truncation_reasons,
            source_content_sha256=inspected.source_content_sha256,
        )
        return finalize_observation(
            path=path,
            relative_path=relative,
            detected_format=sniff.detected_format,
            inspector_id=inspector.inspector_id,
            inspector_version=inspector.inspector_version,
            tracker=tracker,
            outcome=outcome,
        )


def inspect_file(
    case_root: str | Path,
    relative_path: str,
    *,
    limits: InspectionLimits | None = None,
    registry: InspectorRegistry | None = None,
) -> ObservationArtifact:
    return (registry or InspectorRegistry.default()).inspect(case_root, relative_path, limits=limits)
