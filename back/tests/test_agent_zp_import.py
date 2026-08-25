from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.agent_zp.service import AgentZpError, import_agent_zp_candidate
from app.api.v1 import build_api_router
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.schemas.agent_zp import AgentZpImportCreateIn
from app.services.mzml_scan_index import load_scan_index
from app.services.mzml_scan_reader import get_spectrum_by_scan
from app.zp_conversion import repository
from app.zp_runtime import clear_zp_runtime_caches
from app.zp_runtime.package import ensure_binary_layer_importable


@pytest.fixture(autouse=True)
def isolated_agent_zp_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    monkeypatch.setattr(settings, "data_root", data_root)
    monkeypatch.setattr(settings, "zp_output_root", data_root / ".viewer-zp")
    monkeypatch.setattr(settings, "zp_temp_root", Path(".tmp"))
    monkeypatch.setattr(settings, "zp_allowed_source_roots", "")
    monkeypatch.setattr(settings, "zp_management_enabled", True)
    monkeypatch.setattr(settings, "zp_import_conversion_enabled", True)
    repository.ensure_zp_conversion_schema()
    _ensure_universal_tables()
    _clear_rows()
    clear_zp_runtime_caches()
    yield
    _clear_rows()
    clear_zp_runtime_caches()


def test_import_existing_zp_creates_verified_spectra_dataset() -> None:
    source_root = settings.resolved_data_root / "incoming"
    source_root.mkdir()
    zp_path = _write_minimal_zp(source_root / "candidate.zp")
    expected_sha256 = hashlib.sha256(zp_path.read_bytes()).hexdigest()

    with SessionLocal() as session:
        result = import_agent_zp_candidate(
            session,
            AgentZpImportCreateIn(
                source_path=str(zp_path),
                slug="agent-zp-sample",
                name="Agent ZP Sample",
                analysis_category="SPECTRA_ONLY",
                source_profile="minimal_fixture",
                binary_operation="register_existing_zp",
                replace_existing=False,
            ),
        )

    assert result.status == "success"
    assert result.dataset_slug == "agent-zp-sample"
    assert result.zp_output_sha256 == expected_sha256
    assert result.verification.scan_index_total == 2
    assert result.verification.readable_run_count == 1
    assert result.verification.runs[0].sample_peak_count == 2

    with SessionLocal() as session:
        dataset = session.execute(
            text("SELECT dataset_id, status, capabilities, extra_metadata FROM datasets WHERE slug = :slug"),
            {"slug": "agent-zp-sample"},
        ).mappings().one()
        runs = session.execute(
            text("SELECT run_id, file_name, run_metadata FROM runs WHERE dataset_id = :dataset_id"),
            {"dataset_id": dataset["dataset_id"]},
        ).mappings().all()
        asset = session.execute(
            text("SELECT zp_path, output_sha256, status FROM dataset_zp_assets WHERE dataset_id = :dataset_id"),
            {"dataset_id": dataset["dataset_id"]},
        ).mappings().one()
        index = load_scan_index(session, result.dataset_id, result.run_ids[0])
        spectrum, committed = get_spectrum_by_scan(session, result.dataset_id, result.run_ids[0], 10)

    caps = _json_object(dataset["capabilities"])
    extra = _json_object(dataset["extra_metadata"])
    run_meta = _json_object(runs[0]["run_metadata"])

    assert dataset["status"] == "READY"
    assert caps["spectra_source"] == "zp"
    assert caps["analysis_shape"] == "zp_spectra_only"
    assert extra["agent_zp"]["source_profile"] == "minimal_fixture"
    assert len(runs) == 1
    assert run_meta["raw_format"] == "zp"
    assert run_meta["zp_run_id"] == "run_1"
    assert asset["status"] == "active"
    assert asset["output_sha256"] == expected_sha256
    assert Path(str(asset["zp_path"])) == zp_path
    assert index.scan_number.tolist() == [10, 11]
    assert committed is False
    assert spectrum["scan"] == 10
    assert spectrum["mz"] == [100.0, 200.0]
    assert spectrum["intensity"] == [10.0, 20.0]


def test_import_existing_zp_requires_enabled_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "zp_import_conversion_enabled", False)

    with SessionLocal() as session, pytest.raises(AgentZpError) as exc_info:
        import_agent_zp_candidate(
            session,
            AgentZpImportCreateIn(
                source_path=str(settings.resolved_data_root),
                slug="disabled",
                name="Disabled",
                analysis_category="SPECTRA_ONLY",
                source_profile="minimal_fixture",
                binary_operation="register_existing_zp",
                replace_existing=False,
            ),
        )

    assert exc_info.value.code == "AGENT_ZP_DISABLED"


def test_agent_zp_route_is_registered_only_when_import_guard_is_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "zp_management_enabled", True)
    monkeypatch.setattr(settings, "zp_import_conversion_enabled", True)
    enabled_paths = {route.path for route in build_api_router().routes}

    monkeypatch.setattr(settings, "zp_import_conversion_enabled", False)
    disabled_paths = {route.path for route in build_api_router().routes}

    assert "/api/v1/agent-zp/imports" in enabled_paths
    assert "/api/v1/agent-zp/imports" not in disabled_paths


def _ensure_universal_tables() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_name TEXT NULL,
                    name TEXT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    analysis_mode TEXT NOT NULL DEFAULT 'TOP_DOWN',
                    source_software TEXT NULL,
                    source_root TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'IMPORTED',
                    description TEXT NULL,
                    capabilities TEXT NOT NULL DEFAULT '{}',
                    extra_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    source_dataset_fingerprint TEXT NULL,
                    source_import_kind TEXT NOT NULL DEFAULT 'LEGACY'
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_id INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    analysis_mode TEXT NOT NULL DEFAULT 'TOP_DOWN',
                    software TEXT NULL,
                    status TEXT NOT NULL DEFAULT 'IMPORTED',
                    run_metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )


def _clear_rows() -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM dataset_zp_assets"))
        conn.execute(text("DELETE FROM zp_conversion_jobs"))
        conn.execute(text("DELETE FROM runs"))
        conn.execute(text("DELETE FROM datasets"))


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        return json.loads(raw)
    return {}


def _write_minimal_zp(path: Path) -> Path:
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

    blocks = BlockCollection(
        global_meta=GlobalMetaBlock(
            format_version=1,
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
        extensions=[],
    )
    return ZpWriter().write(path, blocks, format_version=1)
