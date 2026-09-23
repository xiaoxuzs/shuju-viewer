from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.ingest.bu.bottom_up_identification import BottomUpSource
from app.ingest.bu.universal_diann_adapter import UniversalDiannImportStats
import app.ingest.bu.universal_diaclip_adapter as adapter


@pytest.mark.parametrize("replace_existing", [False, True])
def test_diaclip_adapter_enriches_source_without_shadowing_dataclass_replace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    replace_existing: bool,
) -> None:
    result_path = tmp_path / "results" / "clip.tsv"
    report_path = tmp_path / "all_report.parquet"
    source = BottomUpSource(
        software="DIA-CLIP",
        import_mode="diaclip_tsv_diann_context",
        dataset_description="DIA-CLIP test",
        identifications=[],
        source_total_rows=1,
        skipped_matches=0,
        extra_metadata={"preserved": "value"},
    )
    prepared = SimpleNamespace(
        source=source,
        bundle=SimpleNamespace(
            result_path=result_path,
            report_path=report_path,
            report_info=object(),
        ),
    )
    writer_calls: list[dict[str, Any]] = []
    expected_stats = UniversalDiannImportStats(dataset_id=7, run_id=11)
    extra_mzml_roots = (tmp_path / "converted",)
    raw_conversion_by_mzml_key = {"sample": {"raw_path": "sample.raw"}}
    pfmb_sidecar_dir = tmp_path / "pfmb"
    progress_callback = lambda _event: None

    monkeypatch.setattr(adapter, "prepare_diaclip_source", lambda *_args, **_kwargs: prepared)
    monkeypatch.setattr(
        adapter,
        "ingest_universal_bottom_up",
        lambda **kwargs: writer_calls.append(kwargs) or expected_stats,
    )

    result = adapter.ingest_universal_diaclip(
        root=tmp_path,
        database_url="postgresql://unused",
        slug="dia-clip",
        name="DIA-CLIP",
        replace=replace_existing,
        spectra_source="mzml_memory",
        extra_mzml_roots=extra_mzml_roots,
        raw_conversion_by_mzml_key=raw_conversion_by_mzml_key,
        pfmb_sidecar_dir=pfmb_sidecar_dir,
        progress_callback=progress_callback,
    )

    assert result is expected_stats
    assert len(writer_calls) == 1
    call = writer_calls[0]
    assert call["replace"] is replace_existing
    assert call["source"].extra_metadata == {
        "preserved": "value",
        "diaclip_result_path": str(result_path.resolve().relative_to(tmp_path.resolve())),
    }
    assert source.extra_metadata == {"preserved": "value"}
    assert call["extra_mzml_roots"] == extra_mzml_roots
    assert call["raw_conversion_by_mzml_key"] is raw_conversion_by_mzml_key
    assert call["pfmb_sidecar_dir"] == pfmb_sidecar_dir
    assert call["progress_callback"] is progress_callback
