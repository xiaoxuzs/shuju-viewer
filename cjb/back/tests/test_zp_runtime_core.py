from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.bu.services import lists_service
from app.bu.services.overview_service import get_overview
from app.services import mzml_scan_index, mzml_scan_reader
from app.zp_conversion import repository
from app.zp_runtime import core as zp_core
from app.zp_runtime import (
    ZpAssetReadError,
    clear_zp_runtime_caches,
    get_binary_bottom_up_peptide,
    get_binary_bottom_up_protein,
    get_binary_bottom_up_overview,
    get_binary_chromatogram,
    get_binary_extension_payload,
    get_binary_extension_summaries,
    get_binary_top_down_prsm,
    get_binary_top_down_protein,
    get_binary_top_down_proteoform,
)
from app.zp_runtime.assets import find_active_asset
from app.zp_runtime.package import ensure_binary_layer_importable


DATASET_ID = 93001
RUN_ID = 94001


@pytest.fixture(autouse=True)
def isolated_runtime_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "zp_management_enabled", True)
    repository.ensure_zp_conversion_schema()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_id INTEGER PRIMARY KEY,
                    slug TEXT,
                    name TEXT,
                    source_root TEXT,
                    capabilities TEXT,
                    status TEXT,
                    created_at TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id INTEGER PRIMARY KEY,
                    dataset_id INTEGER,
                    file_path TEXT,
                    file_name TEXT,
                    run_metadata TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS proteins (
                    protein_id INTEGER PRIMARY KEY,
                    dataset_id INTEGER,
                    accession TEXT,
                    gene_name TEXT,
                    description TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS protein_relation_mapping (
                    dataset_id INTEGER,
                    protein_id INTEGER,
                    entity_type TEXT,
                    entity_id INTEGER
                )
                """
            )
        )
        conn.execute(text("DELETE FROM dataset_zp_assets WHERE dataset_id = :dataset_id"), {"dataset_id": DATASET_ID})
        conn.execute(text("DELETE FROM runs WHERE dataset_id = :dataset_id"), {"dataset_id": DATASET_ID})
        conn.execute(text("DELETE FROM datasets WHERE dataset_id = :dataset_id"), {"dataset_id": DATASET_ID})
        conn.execute(text("DELETE FROM protein_relation_mapping WHERE dataset_id = :dataset_id"), {"dataset_id": DATASET_ID})
        conn.execute(text("DELETE FROM proteins WHERE dataset_id = :dataset_id"), {"dataset_id": DATASET_ID})
    clear_zp_runtime_caches()
    yield
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM dataset_zp_assets WHERE dataset_id = :dataset_id"), {"dataset_id": DATASET_ID})
        conn.execute(text("DELETE FROM runs WHERE dataset_id = :dataset_id"), {"dataset_id": DATASET_ID})
        conn.execute(text("DELETE FROM datasets WHERE dataset_id = :dataset_id"), {"dataset_id": DATASET_ID})
        conn.execute(text("DELETE FROM protein_relation_mapping WHERE dataset_id = :dataset_id"), {"dataset_id": DATASET_ID})
        conn.execute(text("DELETE FROM proteins WHERE dataset_id = :dataset_id"), {"dataset_id": DATASET_ID})
    clear_zp_runtime_caches()


def test_find_active_asset_skips_table_when_management_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "zp_management_enabled", False)

    class FailingSession:
        def execute(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("dataset_zp_assets must not be queried when ZP management is disabled")

    assert find_active_asset(FailingSession(), DATASET_ID) is None  # type: ignore[arg-type]


def test_find_active_asset_without_run_id_uses_dataset_level_asset(tmp_path: Path) -> None:
    dataset_zp = tmp_path / "dataset.zp"
    run_zp = tmp_path / "run.zp"
    dataset_zp.write_bytes(b"dataset")
    run_zp.write_bytes(b"run")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO dataset_zp_assets (
                    dataset_id, run_id, zp_path, format_version, source_fingerprint,
                    output_sha256, status, capabilities, created_at, updated_at
                )
                VALUES (
                    :dataset_id, NULL, :zp_path, 1, NULL,
                    :output_sha256, 'active', '{"spectra": true}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {"dataset_id": DATASET_ID, "zp_path": str(dataset_zp), "output_sha256": "a" * 64},
        )
        conn.execute(
            text(
                """
                INSERT INTO dataset_zp_assets (
                    dataset_id, run_id, zp_path, format_version, source_fingerprint,
                    output_sha256, status, capabilities, created_at, updated_at
                )
                VALUES (
                    :dataset_id, :run_id, :zp_path, 1, NULL,
                    :output_sha256, 'active', '{"spectra": true}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "dataset_id": DATASET_ID,
                "run_id": RUN_ID,
                "zp_path": str(run_zp),
                "output_sha256": "b" * 64,
            },
        )

    with SessionLocal() as session:
        dataset_asset = find_active_asset(session, DATASET_ID)
        run_asset = find_active_asset(session, DATASET_ID, run_id=RUN_ID)

    assert dataset_asset is not None
    assert dataset_asset.run_id is None
    assert dataset_asset.zp_path == dataset_zp
    assert run_asset is not None
    assert run_asset.run_id == RUN_ID
    assert run_asset.zp_path == run_zp


def test_spectrum_scan_index_and_chromatogram_are_binary_backed(tmp_path: Path) -> None:
    zp_path = _write_minimal_zp(tmp_path / "run.zp")
    _insert_dataset_with_asset(zp_path)

    with SessionLocal() as session:
        spectrum, committed = mzml_scan_reader.get_spectrum_by_scan(session, DATASET_ID, RUN_ID, 11)
        index = mzml_scan_index.load_scan_index(session, DATASET_ID, RUN_ID)
        trace = get_binary_chromatogram(session, DATASET_ID, RUN_ID, "bpc")

    assert committed is False
    assert spectrum["scan"] == 11
    assert spectrum["native_id"] == "controllerType=0 controllerNumber=1 scan=11"
    assert spectrum["rt_seconds"] == 60.0
    assert spectrum["mz"] == [150.0, 250.0]
    assert spectrum["intensity"] == [15.0, 25.0]
    assert spectrum["precursor"]["selected_mz"] == 500.2
    assert spectrum["precursor"]["charge"] == 2

    assert index.scan_count == 2
    assert index.scan_number.tolist() == [10, 11]
    assert index.retention_time.tolist() == [0.5, 1.0]
    assert index.tic.tolist() == [30.0, 40.0]
    assert index.bpc.tolist() == [20.0, 25.0]
    assert index.precursor_mz[1] == pytest.approx(500.2)

    assert trace is not None
    assert trace.rt == [0.5, 1.0]
    assert trace.intensity == [18.0, 28.0]
    assert trace.point_count_original == 2


def test_binary_spectrum_uses_indexed_array_ids_without_reparsing_spectra(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zp_path = _write_minimal_zp(tmp_path / "run.zp")
    _insert_dataset_with_asset(zp_path)
    with SessionLocal() as session:
        asset = find_active_asset(session, DATASET_ID)
    assert asset is not None
    handle = zp_core._reader_handle(asset)

    def fail_read_spectrum_arrays(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("single-spectrum reads must use the cached core index")

    monkeypatch.setattr(type(handle.reader), "read_spectrum_arrays", fail_read_spectrum_arrays)

    with SessionLocal() as session:
        spectrum = zp_core.get_binary_spectrum_by_scan(session, DATASET_ID, RUN_ID, 11)

    assert spectrum is not None
    assert spectrum["scan"] == 11
    assert spectrum["mz"] == [150.0, 250.0]


def test_binary_batch_spectrum_read_preserves_scan_mapping(tmp_path: Path) -> None:
    zp_path = _write_minimal_zp(tmp_path / "run.zp")
    _insert_dataset_with_asset(zp_path)

    with SessionLocal() as session:
        spectra = zp_core.get_binary_spectra_by_scans(
            session,
            DATASET_ID,
            RUN_ID,
            [11, 10],
        )

    assert spectra is not None
    assert list(spectra) == [11, 10]
    assert spectra[11]["intensity"] == [15.0, 25.0]
    assert spectra[10]["intensity"] == [10.0, 20.0]


def test_binary_batch_spectrum_read_defers_extension_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zp_path = _write_metadata_chromatogram_zp(
        tmp_path / "lazy-metadata.zp",
        format_version=3,
        metadata_record_count=100,
    )
    _insert_dataset_with_asset(zp_path)
    with SessionLocal() as session:
        asset = find_active_asset(session, DATASET_ID)
    assert asset is not None
    reader_type = type(zp_core._reader_handle(asset).reader)
    original = reader_type.read_extensions_by_types
    calls: list[list[str]] = []

    def track_extension_read(reader: Any, extension_types: list[str]) -> Any:
        calls.append(list(extension_types))
        return original(reader, extension_types)

    monkeypatch.setattr(reader_type, "read_extensions_by_types", track_extension_read)

    with SessionLocal() as session:
        spectra = zp_core.get_binary_spectra_by_scans(
            session,
            DATASET_ID,
            RUN_ID,
            [11, 10],
        )

    assert spectra is not None
    assert list(spectra) == [11, 10]
    assert calls == []


def test_binary_chromatogram_uses_spectrum_metadata_without_peak_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zp_path = _write_metadata_chromatogram_zp(tmp_path / "metadata-chromatogram.zp")
    _insert_dataset_with_asset(zp_path)

    def fail_peak_read(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("TIC/BPC metadata should avoid peak-array reads")

    monkeypatch.setattr(zp_core, "_read_spectrum_intensity_values", fail_peak_read)

    with SessionLocal() as session:
        tic = get_binary_chromatogram(session, DATASET_ID, RUN_ID, "tic")
        bpc = get_binary_chromatogram(session, DATASET_ID, RUN_ID, "bpc")

    assert tic is not None
    assert tic.rt == [0.5, 1.0]
    assert tic.intensity == [30.0, 40.0]
    assert bpc is not None
    assert bpc.rt == [0.5, 1.0]
    assert bpc.intensity == [20.0, 25.0]


def test_v3_spectrum_metadata_does_not_read_unrelated_extensions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zp_path = _write_metadata_chromatogram_zp(
        tmp_path / "selective-extensions.zp",
        format_version=3,
        metadata_record_count=100,
        unrelated_record_count=100,
    )
    _insert_dataset_with_asset(zp_path)
    with SessionLocal() as session:
        asset = find_active_asset(session, DATASET_ID)
    assert asset is not None
    reader_type = type(zp_core._reader_handle(asset).reader)
    original_read_block = reader_type.read_block

    def reject_full_extension_read(reader: Any, block_name: str) -> Any:
        if block_name == "extensions":
            raise AssertionError("spectrum metadata must not read the full extensions block")
        return original_read_block(reader, block_name)

    def fail_peak_read(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("selective metadata should avoid peak-array reads")

    monkeypatch.setattr(reader_type, "read_block", reject_full_extension_read)
    monkeypatch.setattr(zp_core, "_read_spectrum_intensity_values", fail_peak_read)

    with SessionLocal() as session:
        tic = get_binary_chromatogram(session, DATASET_ID, RUN_ID, "tic")

    assert tic is not None
    assert tic.rt == [0.5, 1.0]
    assert tic.intensity == [30.0, 40.0]


def test_active_binary_asset_failure_does_not_fall_back_to_mzml(tmp_path: Path) -> None:
    broken = tmp_path / "broken.zp"
    broken.write_bytes(b"not-a-zp-file")
    _insert_dataset_with_asset(broken)

    with SessionLocal() as session:
        with pytest.raises(mzml_scan_reader.MzmlIndexError, match="binary_zp_unreadable"):
            mzml_scan_reader.get_spectrum_by_scan(session, DATASET_ID, RUN_ID, 10)
        with pytest.raises(mzml_scan_index.ScanIndexError, match="binary_zp_unreadable"):
            mzml_scan_index.load_scan_index(session, DATASET_ID, RUN_ID)
        with pytest.raises(ZpAssetReadError, match="binary_zp_unreadable"):
            get_binary_chromatogram(session, DATASET_ID, RUN_ID, "tic")


def test_bottom_up_overview_is_binary_backed(tmp_path: Path) -> None:
    zp_path = _write_bottom_up_zp(tmp_path / "bottom-up.zp")
    _insert_dataset_with_asset(zp_path)

    with SessionLocal() as session:
        binary = get_binary_bottom_up_overview(session, DATASET_ID)
        overview = get_overview(session, _bottom_up_dataset())

    assert binary is not None
    assert binary.summary["identification"] == 1
    assert overview.counts.matches == 1
    assert overview.counts.peptides == 1
    assert overview.counts.proteins == 1
    assert overview.counts.protein_groups == 1
    assert overview.counts.runs == 1
    assert overview.runs[0].match_count == 1
    assert overview.q_value_cutoff == 0.01
    assert overview.capabilities["binary_layer"]["identifications"] is True


def test_v3_bottom_up_index_reuses_selective_business_extensions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zp_path = _write_bottom_up_zp(tmp_path / "bottom-up-v3.zp", format_version=3)
    _insert_dataset_with_asset(zp_path)
    with SessionLocal() as session:
        asset = find_active_asset(session, DATASET_ID)
    assert asset is not None
    reader_type = type(zp_core._reader_handle(asset).reader)

    def reject_full_extension_read(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Bottom-Up runtime must use selective extension reads")

    monkeypatch.setattr(reader_type, "read_extensions", reject_full_extension_read)

    with SessionLocal() as session:
        overview = get_binary_bottom_up_overview(session, DATASET_ID)

    assert overview is not None
    assert overview.summary["identification"] == 1


def test_bottom_up_match_detail_uses_binary_identification(tmp_path: Path) -> None:
    zp_path = _write_bottom_up_zp(tmp_path / "bottom-up.zp")
    _insert_dataset_with_asset(zp_path)

    with SessionLocal() as session:
        out = lists_service.get_match_detail(session, _bottom_up_dataset(), _bottom_up_match())

    assert out.id == 95001
    assert out.scan_number == 11
    assert out.scan_available is True
    assert out.spectrum_native_id == "controllerType=0 controllerNumber=1 scan=11"
    assert out.modified_sequence == "PEPTIDE"
    assert out.precursor_mz == 500.2
    assert out.precursor_charge == 2
    assert out.retention_time == 1.0
    assert out.rt_window.rt_start == pytest.approx(55.0 / 60.0)
    assert out.rt_window.rt_stop == pytest.approx(65.0 / 60.0)
    assert out.q_value == 0.005
    assert out.extra_metadata["binary_identification_id"] == "identification:1"
    assert out.diann["binary_spectrum_id"] == "spectrum_2"


def test_bottom_up_entity_details_and_extensions_are_binary_backed(tmp_path: Path) -> None:
    zp_path = _write_bottom_up_zp(tmp_path / "bottom-up.zp")
    _insert_dataset_with_asset(zp_path)

    with SessionLocal() as session:
        peptide = get_binary_bottom_up_peptide(session, DATASET_ID, "PEPTIDE")
        protein = get_binary_bottom_up_protein(session, DATASET_ID, "P1")
        summaries = get_binary_extension_summaries(session, DATASET_ID)
        payload = get_binary_extension_payload(session, DATASET_ID, "bottom_up_peptides")

    assert peptide is not None
    assert peptide.peptide["peptide_id"] == "peptide:PEPTIDE"
    assert peptide.identifications[0]["identification_id"] == "identification:1"
    assert peptide.proteins[0]["accession"] == "P1"

    assert protein is not None
    assert protein.protein["protein_id"] == "protein:P1"
    assert protein.peptides[0]["sequence"] == "PEPTIDE"
    assert protein.identifications[0]["source_precursor_id"] == "PEPTIDE2"

    assert summaries is not None
    assert {item.extension_type for item in summaries} >= {"bottom_up_metadata", "bottom_up_peptides"}
    assert payload is not None
    assert payload.payload["records"][0]["sequence"] == "PEPTIDE"


def test_top_down_entities_are_binary_backed(tmp_path: Path) -> None:
    zp_path = _write_top_down_zp(tmp_path / "top-down.zp")
    _insert_dataset_with_asset(zp_path)

    with SessionLocal() as session:
        prsm = get_binary_top_down_prsm(session, DATASET_ID, 7)
        proteoform = get_binary_top_down_proteoform(session, DATASET_ID, 8, sequence_id=12)
        protein = get_binary_top_down_protein(session, DATASET_ID, sequence_id=12, sequence_name="P12345")

    assert prsm is not None
    assert prsm.prsm["prsm_id"] == "7"
    assert prsm.proteoform is not None
    assert prsm.proteoform["proteoform_id"] == "12:8"
    assert prsm.spectrum is not None
    assert prsm.spectrum["scan_number"] == 22

    assert proteoform is not None
    assert proteoform.proteoform["protein_accession"] == "P12345"
    assert proteoform.prsms[0]["e_value"] == 0.002

    assert protein is not None
    assert protein.sequence_id == "12"
    assert protein.protein_accession == "P12345"
    assert protein.prsms[0]["feature_intensity"] == 1234.5


def _insert_dataset_with_asset(zp_path: Path) -> None:
    payload = zp_path.read_bytes()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO datasets (
                    dataset_id, slug, name, source_root, capabilities, status, created_at
                )
                VALUES (
                    :dataset_id, 'zp-runtime-test', 'ZP Runtime Test', '', '{}', 'READY', CURRENT_TIMESTAMP
                )
                """
            ),
            {"dataset_id": DATASET_ID},
        )
        conn.execute(
            text(
                """
                INSERT INTO runs (run_id, dataset_id, file_path, file_name, run_metadata)
                VALUES (:run_id, :dataset_id, :file_path, :file_name, :run_metadata)
                """
            ),
            {
                "run_id": RUN_ID,
                "dataset_id": DATASET_ID,
                "file_path": "run.mzML",
                "file_name": "run.mzML",
                "run_metadata": json.dumps({"raw_format": "mzml", "mzml_file_path": "run.mzML"}),
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO dataset_zp_assets (
                    dataset_id, run_id, zp_path, format_version, source_fingerprint,
                    output_sha256, status, capabilities, created_at, updated_at
                )
                VALUES (
                    :dataset_id, NULL, :zp_path, 1, NULL,
                    :output_sha256, 'active', '{"spectra": true}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "dataset_id": DATASET_ID,
                "zp_path": str(zp_path),
                "output_sha256": hashlib.sha256(payload).hexdigest(),
            },
        )


def _bottom_up_dataset() -> dict[str, Any]:
    return {
        "dataset_id": DATASET_ID,
        "slug": "zp-runtime-test",
        "dataset_name": "ZP Runtime Test",
        "source_software": None,
        "status": "READY",
        "source_root": "",
        "capabilities": {},
        "extra_metadata": {},
        "created_at": datetime.now(timezone.utc),
    }


def _bottom_up_match() -> dict[str, Any]:
    return {
        "match_id": 95001,
        "run_id": RUN_ID,
        "run_name": "run.mzML",
        "entity_id": 96001,
        "sequence": "STALE",
        "modified_sequence": "STALE",
        "precursor_mz": 1.0,
        "precursor_charge": 1,
        "retention_time": 99.0,
        "experimental_mass": None,
        "q_value": 0.99,
        "score": 0.99,
        "intensity": 1.0,
        "is_decoy_match": False,
        "scan_number": -1,
        "search_engine": "DIA-NN",
        "spectrum_native_id": None,
        "ms_level": 2,
        "file_path": "run.mzML",
        "run_metadata": {"raw_format": "mzml", "diann_run_name": "run.mzML"},
        "extra_metadata": {"precursor_id": "PEPTIDE2"},
    }


def _write_minimal_zp(path: Path) -> Path:
    ensure_binary_layer_importable()
    from binary_layer import (  # type: ignore[import-not-found]
        ArrayBlock,
        BlockCollection,
        ChromatogramBlock,
        GlobalMetaBlock,
        IndexBlock,
        PrecursorBlock,
        RunBlock,
        SpectrumBlock,
        StringPoolBlock,
        ZpWriter,
    )

    blocks = BlockCollection(
        global_meta=GlobalMetaBlock(
            format_version=1,
            source_type="real_mzml",
            source_file_name="run.mzML",
            source_file_hash="0" * 64,
            run_count=1,
            spectrum_count=2,
            chromatogram_count=2,
            array_count=8,
            created_at=datetime.now(timezone.utc),
            generator_name="zp-binary-layer",
            generator_version="test",
            notes=[],
        ),
        runs=[RunBlock("run_1", "run.mzML", "run_1", 2, 2, 30.0, 60.0)],
        spectra=[
            SpectrumBlock(
                "spectrum_1",
                "run_1",
                1,
                10,
                "controllerType=0 controllerNumber=1 scan=10",
                30.0,
                None,
                "spectrum_1:mz",
                "spectrum_1:intensity",
            ),
            SpectrumBlock(
                "spectrum_2",
                "run_1",
                2,
                11,
                "controllerType=0 controllerNumber=1 scan=11",
                60.0,
                "spectrum_2:precursor",
                "spectrum_2:mz",
                "spectrum_2:intensity",
            ),
        ],
        precursors=[PrecursorBlock("spectrum_2:precursor", "spectrum_2", 500.2, 2, 1000.0)],
        chromatograms=[
            ChromatogramBlock("chromatogram_1", "run_1", "tic", "chromatogram_1:time", "chromatogram_1:intensity", "tic"),
            ChromatogramBlock("chromatogram_2", "run_1", "bpc", "chromatogram_2:time", "chromatogram_2:intensity", "bpc"),
        ],
        arrays=[
            ArrayBlock("spectrum_1:mz", "mz", "float64", [100.0, 200.0]),
            ArrayBlock("spectrum_1:intensity", "intensity", "float64", [10.0, 20.0]),
            ArrayBlock("spectrum_2:mz", "mz", "float64", [150.0, 250.0]),
            ArrayBlock("spectrum_2:intensity", "intensity", "float64", [15.0, 25.0]),
            ArrayBlock("chromatogram_1:time", "time", "float64", [30.0, 60.0]),
            ArrayBlock("chromatogram_1:intensity", "intensity", "float64", [100.0, 200.0]),
            ArrayBlock("chromatogram_2:time", "time", "float64", [30.0, 60.0]),
            ArrayBlock("chromatogram_2:intensity", "intensity", "float64", [18.0, 28.0]),
        ],
        string_pool=StringPoolBlock(
            [
                "run.mzML",
                "run_1",
                "controllerType=0 controllerNumber=1 scan=10",
                "controllerType=0 controllerNumber=1 scan=11",
                "tic",
                "bpc",
            ]
        ),
        indexes=IndexBlock(
            scan_index=[
                {"scan_number": 10, "spectrum_id": "spectrum_1"},
                {"scan_number": 11, "spectrum_id": "spectrum_2"},
            ],
            rt_index=[
                {"rt": 30.0, "spectrum_id": "spectrum_1"},
                {"rt": 60.0, "spectrum_id": "spectrum_2"},
            ],
            spectrum_id_index=[
                {"spectrum_id": "spectrum_1", "position": 0},
                {"spectrum_id": "spectrum_2", "position": 1},
            ],
        ),
        extensions=[],
    )
    return ZpWriter().write(path, blocks, format_version=1)


def _write_metadata_chromatogram_zp(
    path: Path,
    *,
    format_version: int = 1,
    metadata_record_count: int = 2,
    unrelated_record_count: int = 0,
) -> Path:
    ensure_binary_layer_importable()
    from binary_layer import (  # type: ignore[import-not-found]
        ArrayBlock,
        BlockCollection,
        ExtensionBlock,
        GlobalMetaBlock,
        IndexBlock,
        RunBlock,
        SpectrumBlock,
        StringPoolBlock,
        ZpWriter,
    )

    spectra = [
        SpectrumBlock(
            "spectrum_1",
            "run_1",
            1,
            10,
            "controllerType=0 controllerNumber=1 scan=10",
            30.0,
            None,
            "spectrum_1:mz",
            "spectrum_1:intensity",
        ),
        SpectrumBlock(
            "spectrum_2",
            "run_1",
            1,
            11,
            "controllerType=0 controllerNumber=1 scan=11",
            60.0,
            None,
            "spectrum_2:mz",
            "spectrum_2:intensity",
        ),
    ]
    metadata_spectra = [
        {
            "spectrum_id": "spectrum_1",
            "total_ion_current": 30.0,
            "base_peak_intensity": 20.0,
        },
        {
            "spectrum_id": "spectrum_2",
            "total_ion_current": 40.0,
            "base_peak_intensity": 25.0,
        },
    ]
    metadata_spectra.extend(
        {
            "spectrum_id": f"unmapped_spectrum_{position}",
            "total_ion_current": float(position),
            "base_peak_intensity": float(position),
        }
        for position in range(2, metadata_record_count)
    )
    extensions = [
        ExtensionBlock(
            "mzml_metadata",
            "1",
            {
                "owner": "mzml",
                "schema_name": "mzml_metadata",
                "schema_version": 1,
                "record_count": metadata_record_count,
                "spectra": metadata_spectra,
            },
        )
    ]
    if unrelated_record_count:
        extensions.append(
            ExtensionBlock(
                "bottom_up_identifications",
                "1",
                {
                    "records": [
                        {"identification_id": f"identification:{position}"}
                        for position in range(unrelated_record_count)
                    ]
                },
            )
        )

    blocks = BlockCollection(
        global_meta=GlobalMetaBlock(
            format_version=format_version,
            source_type="real_mzml",
            source_file_name="run.mzML",
            source_file_hash="0" * 64,
            run_count=1,
            spectrum_count=2,
            chromatogram_count=0,
            array_count=4,
            created_at=datetime.now(timezone.utc),
            generator_name="zp-binary-layer",
            generator_version="test",
            notes=[],
        ),
        runs=[RunBlock("run_1", "run.mzML", "run_1", 2, 0, 30.0, 60.0)],
        spectra=spectra,
        arrays=[
            ArrayBlock("spectrum_1:mz", "mz", "float64", [100.0, 200.0]),
            ArrayBlock("spectrum_1:intensity", "intensity", "float64", [10.0, 20.0]),
            ArrayBlock("spectrum_2:mz", "mz", "float64", [150.0, 250.0]),
            ArrayBlock("spectrum_2:intensity", "intensity", "float64", [15.0, 25.0]),
        ],
        string_pool=StringPoolBlock(
            [
                "run.mzML",
                "run_1",
                "controllerType=0 controllerNumber=1 scan=10",
                "controllerType=0 controllerNumber=1 scan=11",
            ]
        ),
        indexes=IndexBlock(
            scan_index=[
                {"scan_number": 10, "spectrum_id": "spectrum_1"},
                {"scan_number": 11, "spectrum_id": "spectrum_2"},
            ],
            rt_index=[
                {"rt": 30.0, "spectrum_id": "spectrum_1"},
                {"rt": 60.0, "spectrum_id": "spectrum_2"},
            ],
            spectrum_id_index=[
                {"spectrum_id": "spectrum_1", "position": 0},
                {"spectrum_id": "spectrum_2", "position": 1},
            ],
        ),
        extensions=extensions,
    )
    return ZpWriter().write(path, blocks, format_version=format_version)


def _write_bottom_up_zp(path: Path, *, format_version: int = 1) -> Path:
    ensure_binary_layer_importable()
    from binary_layer import (  # type: ignore[import-not-found]
        ArrayBlock,
        BlockCollection,
        GlobalMetaBlock,
        IndexBlock,
        PrecursorBlock,
        RunBlock,
        SpectrumBlock,
        StringPoolBlock,
        ZpWriter,
    )

    identification_id = "identification:1"
    peptide_id = "peptide:PEPTIDE"
    protein_id = "protein:P1"
    group_id = "protein_group:P1"
    metadata = {
        "source_type": "real_dia_result_bundle",
        "adapter_flavor": "diann_2_parquet",
        "identification_kind": "dia_precursor_identification",
        "analysis_mode": "bottom_up_dia",
        "report_run_name": "run.mzML",
        "core_run_id": "run_1",
        "source_software": "DIA-NN",
        "selection_policy": {"q_value_cutoff": 0.01},
        "field_coverage": {"unexplained_column_count": 0},
        "entity_counts": {
            "identification": 1,
            "peptide": 1,
            "protein": 1,
            "protein_group": 1,
            "modification": 0,
            "fragment_match": 0,
            "quantification": 0,
        },
        "association": {
            "identification_count": 1,
            "associated_identification_count": 1,
            "distinct_ms2_count": 1,
            "dangling_spectrum_reference_count": 0,
        },
        "source_files": [
            {"source_file": "report.parquet", "size": 1, "sha256": "a" * 64},
            {"source_file": "run.mzML", "size": 1, "sha256": "b" * 64},
        ],
        "fragment_support": {"status": "not_available", "reason": "test"},
        "extension_status": {
            "bottom_up_identifications": "available",
            "bottom_up_peptides": "available",
            "bottom_up_proteins": "available",
            "bottom_up_protein_groups": "available",
            "bottom_up_modifications": "not_present",
            "bottom_up_fragment_matches": "not_available",
            "bottom_up_quantification": "not_present",
        },
    }
    extensions = [
        _bottom_up_extension("bottom_up_metadata", metadata=metadata),
        _bottom_up_extension(
            "bottom_up_identifications",
            records=[
                {
                    "identification_id": identification_id,
                    "identification_kind": "dia_precursor_identification",
                    "run_id": "run_1",
                    "source_run_name": "run.mzML",
                    "source_precursor_id": "PEPTIDE2",
                    "spectrum_id": "spectrum_2",
                    "association_kind": "nearest_rt_precursor_window",
                    "association_rt_delta_seconds": 0.0,
                    "association_precursor_mz": 500.2,
                    "peptide_id": peptide_id,
                    "protein_group_id": group_id,
                    "protein_ids": [protein_id],
                    "modified_sequence": "PEPTIDE",
                    "stripped_sequence": "PEPTIDE",
                    "charge": 2,
                    "precursor_mz": 500.2,
                    "neutral_mass": 998.385,
                    "rt_seconds": 60.0,
                    "rt_start_seconds": 55.0,
                    "rt_stop_seconds": 65.0,
                    "typed_fields": {"q_value": 0.005},
                    "modification_ids": [],
                    "quantification_ids": [],
                    "source_fields": {"Q.Value": 0.005},
                }
            ],
        ),
        _bottom_up_extension(
            "bottom_up_peptides",
            records=[
                {
                    "peptide_id": peptide_id,
                    "sequence": "PEPTIDE",
                    "length": 7,
                    "identification_ids": [identification_id],
                    "modified_sequences": ["PEPTIDE"],
                    "precursor_charges": [2],
                    "protein_ids": [protein_id],
                    "protein_group_ids": [group_id],
                    "modification_ids": [],
                }
            ],
        ),
        _bottom_up_extension(
            "bottom_up_proteins",
            records=[
                {
                    "protein_id": protein_id,
                    "accession": "P1",
                    "is_decoy": False,
                    "name": None,
                    "gene": "GENE1",
                    "description": "Protein one",
                    "sequence": None,
                    "q_value": 0.005,
                    "peptide_ids": [peptide_id],
                    "identification_ids": [identification_id],
                    "protein_group_ids": [group_id],
                    "source_fields": {},
                }
            ],
        ),
        _bottom_up_extension(
            "bottom_up_protein_groups",
            records=[
                {
                    "protein_group_id": group_id,
                    "source_group": "P1",
                    "member_protein_ids": [protein_id],
                    "leading_protein_id": None,
                    "identification_ids": [identification_id],
                    "peptide_ids": [peptide_id],
                    "q_value": 0.005,
                    "pep": None,
                    "global_q_value": None,
                    "lib_q_value": None,
                    "quantification_ids": [],
                    "source_fields": {},
                }
            ],
        ),
    ]
    blocks = BlockCollection(
        global_meta=GlobalMetaBlock(
            format_version=format_version,
            source_type="real_dia_result_bundle",
            source_file_name="report.parquet",
            source_file_hash="0" * 64,
            run_count=1,
            spectrum_count=2,
            chromatogram_count=0,
            array_count=4,
            created_at=datetime.now(timezone.utc),
            generator_name="zp-binary-layer",
            generator_version="test",
            notes=[],
        ),
        runs=[RunBlock("run_1", "run.mzML", "run_1", 2, 0, 30.0, 60.0)],
        spectra=[
            SpectrumBlock(
                "spectrum_1",
                "run_1",
                1,
                10,
                "controllerType=0 controllerNumber=1 scan=10",
                30.0,
                None,
                "spectrum_1:mz",
                "spectrum_1:intensity",
            ),
            SpectrumBlock(
                "spectrum_2",
                "run_1",
                2,
                11,
                "controllerType=0 controllerNumber=1 scan=11",
                60.0,
                "spectrum_2:window",
                "spectrum_2:mz",
                "spectrum_2:intensity",
            ),
        ],
        precursors=[
            PrecursorBlock(
                "spectrum_2:window",
                "spectrum_2",
                None,
                None,
                None,
                "isolation_window",
                480.0,
                520.0,
            )
        ],
        arrays=[
            ArrayBlock("spectrum_1:mz", "mz", "float64", [100.0, 200.0]),
            ArrayBlock("spectrum_1:intensity", "intensity", "float64", [10.0, 20.0]),
            ArrayBlock("spectrum_2:mz", "mz", "float64", [150.0, 250.0]),
            ArrayBlock("spectrum_2:intensity", "intensity", "float64", [15.0, 25.0]),
        ],
        string_pool=StringPoolBlock(
            [
                "run.mzML",
                "run_1",
                "controllerType=0 controllerNumber=1 scan=10",
                "controllerType=0 controllerNumber=1 scan=11",
            ]
        ),
        indexes=IndexBlock(
            scan_index=[
                {"scan_number": 10, "spectrum_id": "spectrum_1"},
                {"scan_number": 11, "spectrum_id": "spectrum_2"},
            ],
            rt_index=[
                {"rt": 30.0, "spectrum_id": "spectrum_1"},
                {"rt": 60.0, "spectrum_id": "spectrum_2"},
            ],
            spectrum_id_index=[
                {"spectrum_id": "spectrum_1", "position": 0},
                {"spectrum_id": "spectrum_2", "position": 1},
            ],
        ),
        extensions=extensions,
    )
    return ZpWriter().write(path, blocks, format_version=format_version)


def _write_top_down_zp(path: Path) -> Path:
    ensure_binary_layer_importable()
    from binary_layer import (  # type: ignore[import-not-found]
        ArrayBlock,
        BlockCollection,
        GlobalMetaBlock,
        IndexBlock,
        PrecursorBlock,
        RunBlock,
        SpectrumBlock,
        StringPoolBlock,
        ZpWriter,
    )

    prsm_detail = {
        "annotated_protein": {
            "sequence_id": "12",
            "proteoform_id": "8",
            "sequence_name": "P12345",
            "sequence_description": "Top-down protein",
            "proteoform_mass": 800.1,
            "annotation": {
                "annotated_seq": "PEPTIDE",
                "first_residue_position": 1,
                "last_residue_position": 7,
                "protein_length": 100,
            },
        },
        "ms": {
            "ms_header": {
                "spectrum_file_name": "run.mzML",
                "precursor_mz": 700.2,
                "precursor_charge": 5,
                "precursor_mono_mass": 3500.0,
                "ms1_scans": [21],
                "ms1_ids": ["controllerType=0 controllerNumber=1 scan=21"],
                "scans": [22],
                "ids": ["controllerType=0 controllerNumber=1 scan=22"],
                "feature_inte": 1234.5,
            },
            "peaks": {"peak": []},
        },
        "matched_fragment_number": 1,
        "matched_peak_number": 1,
        "p_value": 0.001,
        "e_value": 0.002,
        "fdr": 0.003,
    }
    extensions = [
        _top_down_extension(
            "top_down_metadata",
            record_count=1,
            metadata={
                "run_name": "run.mzML",
                "spectrum_source_type": "mzml",
                "detected_roles": ["prsm_detail"],
                "source_files": [{"source_file": "run.mzML", "size": 1, "sha256": "c" * 64}],
                "source_tables": [],
                "source_field_coverage": {},
                "warnings": [],
            },
        ),
        _top_down_extension(
            "top_down_proteoforms",
            records=[
                {
                    "proteoform_id": "12:8",
                    "sequence_id": "12",
                    "protein_accession": "P12345",
                    "protein_description": "Top-down protein",
                    "sequence": "PEPTIDE",
                    "start_position": 1,
                    "end_position": 7,
                    "protein_length": 100,
                    "experimental_mass": 800.1,
                    "theoretical_mass": 799.9,
                    "mass_error": 0.2,
                    "terminal_state": "NONE",
                    "best_prsm_id": "7",
                    "score_summary": {"p_value": 0.001, "e_value": 0.002, "q_value": 0.003, "score": 42.0},
                    "annotated_sequence": "PEPTIDE",
                    "residues": [],
                    "cleavages": [],
                    "modification_ids": [],
                    "source_fields": {"prsm_detail": {"source_file": "prsms/prsm7.js", "value": prsm_detail}},
                }
            ],
        ),
        _top_down_extension(
            "top_down_prsms",
            records=[
                {
                    "prsm_id": "7",
                    "spectrum_id": "spectrum_1",
                    "spectrum_reference": {
                        "run_name": "run.mzML",
                        "spectrum_file_name": "run.mzML",
                        "scan_numbers": [22],
                        "native_ids": ["controllerType=0 controllerNumber=1 scan=22"],
                        "ms1_scan_numbers": [21],
                        "ms1_ids": ["controllerType=0 controllerNumber=1 scan=21"],
                    },
                    "proteoform_id": "12:8",
                    "precursor_mz": 700.2,
                    "charge": 5,
                    "precursor_mass": 3500.0,
                    "adjusted_mass": 3500.1,
                    "matched_fragment_count": 1,
                    "matched_peak_count": 1,
                    "total_fragment_count": 2,
                    "p_value": 0.001,
                    "e_value": 0.002,
                    "q_value": 0.003,
                    "score": 42.0,
                    "rank": 1,
                    "feature_intensity": 1234.5,
                    "source_fields": {"prsm_detail": {"source_file": "prsms/prsm7.js", "value": prsm_detail}},
                }
            ],
        ),
        _top_down_extension("top_down_modifications", records=[]),
        _top_down_extension("top_down_fragment_matches", records=[], peaks=[], peak_count=0),
        _top_down_extension(
            "top_down_features",
            records=[
                {
                    "feature_id": "feature:7",
                    "source_feature_id": "7",
                    "prsm_id": "7",
                    "spectrum_id": "spectrum_1",
                    "intensity": 1234.5,
                    "score": 10.0,
                    "min_rt_seconds": 118.0,
                    "max_rt_seconds": 122.0,
                    "apex_rt_seconds": 120.0,
                    "source_fields": {},
                }
            ],
        ),
    ]
    blocks = BlockCollection(
        global_meta=GlobalMetaBlock(
            format_version=1,
            source_type="real_top_down_bundle",
            source_file_name="topdown",
            source_file_hash="0" * 64,
            run_count=1,
            spectrum_count=1,
            chromatogram_count=0,
            array_count=2,
            created_at=datetime.now(timezone.utc),
            generator_name="zp-binary-layer",
            generator_version="test",
            notes=[],
        ),
        runs=[RunBlock("run_1", "run.mzML", "run_1", 1, 0, 120.0, 120.0)],
        spectra=[
            SpectrumBlock(
                "spectrum_1",
                "run_1",
                2,
                22,
                "controllerType=0 controllerNumber=1 scan=22",
                120.0,
                "spectrum_1:precursor",
                "spectrum_1:mz",
                "spectrum_1:intensity",
            ),
        ],
        precursors=[PrecursorBlock("spectrum_1:precursor", "spectrum_1", 700.2, 5, 1234.5)],
        arrays=[
            ArrayBlock("spectrum_1:mz", "mz", "float64", [700.1, 701.2]),
            ArrayBlock("spectrum_1:intensity", "intensity", "float64", [100.0, 200.0]),
        ],
        string_pool=StringPoolBlock(
            [
                "run.mzML",
                "run_1",
                "controllerType=0 controllerNumber=1 scan=22",
            ]
        ),
        indexes=IndexBlock(
            scan_index=[{"scan_number": 22, "spectrum_id": "spectrum_1"}],
            rt_index=[{"rt": 120.0, "spectrum_id": "spectrum_1"}],
            spectrum_id_index=[{"spectrum_id": "spectrum_1", "position": 0}],
        ),
        extensions=extensions,
    )
    return ZpWriter().write(path, blocks, format_version=1)


def _bottom_up_extension(extension_type: str, **values: object) -> Any:
    from binary_layer import ExtensionBlock  # type: ignore[import-not-found]

    record_count = 1 if extension_type == "bottom_up_metadata" else len(values.get("records", []))
    payload = {
        "owner": "bottom_up",
        "schema_name": extension_type,
        "schema_version": 1,
        "record_count": record_count,
        **values,
    }
    return ExtensionBlock(extension_type, "1", payload)


def _top_down_extension(extension_type: str, **values: object) -> Any:
    from binary_layer import ExtensionBlock  # type: ignore[import-not-found]

    record_count = values.pop("record_count", len(values.get("records", [])))
    payload = {
        "owner": "top_down",
        "schema_name": extension_type,
        "schema_version": 1,
        "record_count": record_count,
        **values,
    }
    return ExtensionBlock(extension_type, "1", payload)
