from __future__ import annotations

from pathlib import Path

from app.agent_import.admission import admit_unknown_source_path


def test_unknown_source_admission_uses_the_shared_metadata_fingerprint(tmp_path: Path) -> None:
    source = tmp_path / "unknown"
    source.mkdir()
    (source / "candidate.zp").write_bytes(b"not-validated-at-admission")

    admitted = admit_unknown_source_path(source)

    assert admitted.source_root == source.resolve()
    assert admitted.file_count == 1
    assert len(admitted.dataset_fingerprint) == 32


def test_mzml_with_unknown_results_is_admitted_for_agent_inspection(tmp_path: Path) -> None:
    source = tmp_path / "unknown-with-spectra"
    source.mkdir()
    (source / "sample.mzML").write_text("<mzML />", encoding="utf-8")
    (source / "vendor-results.tsv").write_text("feature\tintensity\nA\t12\n", encoding="utf-8")

    admitted = admit_unknown_source_path(source)

    assert admitted.source_root == source.resolve()
    assert admitted.file_count == 2
