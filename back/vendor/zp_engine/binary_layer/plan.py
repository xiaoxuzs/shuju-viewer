from .source_adapters import (
    MOCK_MZML_STEPS,
    RAW_STEPS,
    REAL_DIA_RESULT_STEPS,
    REAL_MZML_STEPS,
    REAL_THERMO_RAW_STEPS,
    REAL_TOP_DOWN_INTERMEDIATE_STEPS,
    REAL_TOP_DOWN_STEPS,
    SourceAdapterRegistry,
    build_default_source_adapter_registry,
)
from .models import ConversionPlan, SourceProfile


class PlanBuilder:
    def __init__(self, adapters: SourceAdapterRegistry | None = None) -> None:
        self.adapters = adapters or build_default_source_adapter_registry()

    def build(self, profile: SourceProfile) -> ConversionPlan:
        return self.adapters.get(profile.source_type).build_plan(profile)
