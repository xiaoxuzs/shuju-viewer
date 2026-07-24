from __future__ import annotations

from pathlib import Path

import pytest

from app.import_types import ImportType
from app.services import import_selection
from app.services.import_planner.types import DatasetShape, ImportPlan
from app.services.import_selection import ImportSelectionError, default_import_kind, validate_import_selection


def _plan(shape: DatasetShape, *, contains_raw: bool = False) -> ImportPlan:
    return ImportPlan(
        shape=shape,
        spectra_source="mzml_memory",
        need_toppic_multirun_pass=False,
        contains_raw=contains_raw,
    )


def test_dia_nn_and_dia_clip_share_physical_diann_layout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checked: list[Path] = []
    monkeypatch.setattr(
        import_selection,
        "inspect_diaclip_bundle",
        lambda root: checked.append(root),
    )

    validate_import_selection(ImportType.DIA_NN, tmp_path, _plan(DatasetShape.DIANN_DIA))
    assert checked == []
    validate_import_selection(ImportType.DIA_CLIP, tmp_path, _plan(DatasetShape.DIANN_DIA))
    assert checked == [tmp_path]


def test_selected_type_mismatch_is_rejected_before_import(tmp_path: Path) -> None:
    with pytest.raises(ImportSelectionError, match="does not match"):
        validate_import_selection(ImportType.DIA_CLIP, tmp_path, _plan(DatasetShape.MZML_ONLY))


def test_legacy_default_kind_preserves_raw_vs_mzml_semantics() -> None:
    assert default_import_kind(_plan(DatasetShape.MZML_ONLY, contains_raw=True)) == "RAW_ONLY"
    assert default_import_kind(_plan(DatasetShape.MZML_ONLY)) == "MZML_ONLY"
