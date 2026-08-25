from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import uuid4

from .constants import ZP_EXTENSION
from .dia_resource_limits import DIA_V2_ARRAY_WRITE_LIMITS, DIA_V2_VALIDATION_LIMITS
from .exceptions import UnsupportedSourceError
from .models import ConversionPlan, PipelineContext, SourceProfile


REAL_MZML_STEPS = (
    "file_validate",
    "hash_input",
    "real_mzml_parse",
    "string_pool_build",
    "index_build",
    "zp_write",
    "zp_validate",
)
MOCK_MZML_STEPS = (
    "file_validate",
    "hash_input",
    "mock_mzml_parse",
    "string_pool_build",
    "index_build",
    "zp_write",
    "zp_validate",
)
RAW_STEPS = (
    "file_validate",
    "hash_input",
    "mock_raw_to_mzml",
    "mock_mzml_parse",
    "string_pool_build",
    "index_build",
    "zp_write",
    "zp_validate",
)
REAL_THERMO_RAW_STEPS = (
    "file_validate",
    "hash_input",
    "real_thermo_raw_parse",
    "string_pool_build",
    "index_build",
    "zp_write",
    "zp_validate",
)
REAL_TOP_DOWN_STEPS = (
    "file_validate",
    "hash_input",
    "real_top_down",
    "string_pool_build",
    "index_build",
    "zp_write",
    "zp_validate",
)
REAL_TOP_DOWN_INTERMEDIATE_STEPS = (
    "file_validate",
    "hash_input",
    "real_top_down_intermediate_parse",
    "string_pool_build",
    "index_build",
    "zp_write",
    "zp_validate",
)
REAL_TOPFD_JS_STEPS = (
    "file_validate",
    "hash_input",
    "real_topfd_js_parse",
    "string_pool_build",
    "index_build",
    "zp_write",
    "zp_validate",
)
REAL_DIA_RESULT_STEPS = (
    "file_validate",
    "hash_input",
    "real_dia_result",
    "string_pool_build",
    "index_build",
    "zp_write",
    "zp_validate",
)


ContextConfigurer = Callable[[PipelineContext], None]


@dataclass(frozen=True, slots=True)
class SourceAdapter:
    source_type: str
    required_steps: tuple[str, ...]
    output_extension: str = ZP_EXTENSION
    context_configurer: ContextConfigurer | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def build_plan(self, profile: SourceProfile) -> ConversionPlan:
        if profile.source_type != self.source_type:
            raise UnsupportedSourceError(
                f"Adapter {self.source_type} cannot plan source type: {profile.source_type}"
            )
        return ConversionPlan(
            plan_id=str(uuid4()),
            source_type=profile.source_type,
            required_steps=self.required_steps,
            output_extension=self.output_extension,
            notes=(
                f"Fixed named-step conversion plan for source_type={profile.source_type}; "
                "StepRegistry only resolves registered step names.",
            ),
        )

    def configure_context(self, context: PipelineContext) -> None:
        if self.context_configurer is not None:
            self.context_configurer(context)


class SourceAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        if not adapter.source_type:
            raise ValueError("source_type must be nonempty")
        if not adapter.required_steps:
            raise ValueError("required_steps must be nonempty")
        if adapter.source_type in self._adapters:
            raise ValueError(f"Source adapter already registered: {adapter.source_type}")
        self._adapters[adapter.source_type] = adapter

    def get(self, source_type: str) -> SourceAdapter:
        try:
            return self._adapters[source_type]
        except KeyError as exc:
            raise UnsupportedSourceError(f"Unsupported source type: {source_type}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(self._adapters)


def build_default_source_adapter_registry() -> SourceAdapterRegistry:
    registry = SourceAdapterRegistry()
    for adapter in (
        SourceAdapter("real_mzml", REAL_MZML_STEPS),
        SourceAdapter("real_thermo_raw", REAL_THERMO_RAW_STEPS),
        SourceAdapter("real_top_down_bundle", REAL_TOP_DOWN_STEPS),
        SourceAdapter(
            "real_top_down_intermediate_bundle",
            REAL_TOP_DOWN_INTERMEDIATE_STEPS,
        ),
        SourceAdapter("real_topfd_js_bundle", REAL_TOPFD_JS_STEPS),
        SourceAdapter(
            "real_dia_result_bundle",
            REAL_DIA_RESULT_STEPS,
            context_configurer=_configure_dia_result_context,
        ),
        SourceAdapter("mock_mzml", MOCK_MZML_STEPS),
        SourceAdapter("mock_raw", RAW_STEPS),
    ):
        registry.register(adapter)
    return registry


def _configure_dia_result_context(context: PipelineContext) -> None:
    context.metadata["v2_array_write_limits"] = DIA_V2_ARRAY_WRITE_LIMITS
    context.metadata["v2_validation_limits"] = DIA_V2_VALIDATION_LIMITS
