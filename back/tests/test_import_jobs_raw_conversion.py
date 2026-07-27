from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.ingest.bu import universal_diann_adapter as diann_adapter
from app.ingest.td.toppic_native_output import PreparedTopPicNativeOutput
from app.raw_conversion.errors import RawConversionError
from app.services import import_jobs
from app.services.import_planner.types import DatasetShape, ImportPlan


class _FakeFingerprint:
    fingerprint = "a" * 32
    file_count = 3
    elapsed_seconds = 0.001


class _NoopResult:
    def mappings(self) -> "_NoopResult":
        return self

    def one_or_none(self) -> None:
        return None

    def all(self) -> list[dict[str, Any]]:
        return []


class _NoopConnection:
    def __init__(self, statements: list[tuple[str, dict[str, Any] | None]]) -> None:
        self.statements = statements

    def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _NoopResult:
        self.statements.append((str(stmt), params))
        return _NoopResult()


class _NoopBegin:
    def __init__(self, conn: _NoopConnection) -> None:
        self.conn = conn

    def __enter__(self) -> _NoopConnection:
        return self.conn

    def __exit__(self, *_args: Any) -> None:
        return None


class _NoopEngine:
    def __init__(self) -> None:
        self.statements: list[tuple[str, dict[str, Any] | None]] = []

    def begin(self) -> _NoopBegin:
        return _NoopBegin(_NoopConnection(self.statements))


class _RunInsertResult:
    def __init__(self, run_id: int) -> None:
        self.run_id = run_id

    def one(self) -> SimpleNamespace:
        return SimpleNamespace(run_id=self.run_id)


class _RunInsertConnection:
    def __init__(self, metadata_out: list[dict[str, Any]]) -> None:
        self.metadata_out = metadata_out

    def execute(self, _stmt: Any, params: dict[str, Any]) -> _RunInsertResult:
        self.metadata_out.append(json.loads(str(params["run_metadata"])))
        return _RunInsertResult(len(self.metadata_out))


def _command_value(command: list[str], prefix: str) -> str:
    for item in command:
        if item.startswith(prefix):
            return item[len(prefix) :]
    raise AssertionError(f"missing command argument: {prefix}")


def _make_diann_root(tmp_path: Path, *, raw: bool, mzml: bool) -> Path:
    root = tmp_path / "diann"
    report = root / "DIANN_2.0" / "all_report.parquet"
    report.parent.mkdir(parents=True)
    report.write_bytes(b"parquet marker")
    if raw:
        (root / "sample.raw").write_bytes(b"raw")
    if mzml:
        (root / "sample.mzML").write_text(
            "<mzML><indexListOffset>1</indexListOffset></mzML>",
            encoding="utf-8",
        )
    return root


def _install_common_patches(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    updates: list[dict[str, Any]] = []
    derived_calls: list[int] = []
    inserted_run_metadata: list[dict[str, Any]] = []
    mzml_only_calls: list[dict[str, Any]] = []
    engine = _NoopEngine()

    monkeypatch.setattr(import_jobs, "_db_engine", engine)
    monkeypatch.setattr(import_jobs, "_update_job", lambda _job_id, **kwargs: updates.append(kwargs))
    monkeypatch.setattr(import_jobs, "find_dataset_with_fingerprint", lambda _fingerprint, _import_kind: None)
    monkeypatch.setattr(
        import_jobs,
        "compute_dataset_metadata_fingerprint",
        lambda *_args, **_kwargs: _FakeFingerprint(),
    )
    monkeypatch.setattr(import_jobs, "_validate_bu_mzml_mapping", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        import_jobs,
        "prepare_bu_pfmb_sidecar",
        lambda *_args, **_kwargs: SimpleNamespace(status="skipped_no_pfmb", sidecar_dir=None, message="skipped"),
    )

    def fake_derived(_job_id: str, dataset_id: int) -> None:
        derived_calls.append(dataset_id)
        return None

    monkeypatch.setattr(import_jobs, "_run_post_import_derived_data", fake_derived)
    monkeypatch.setattr(import_jobs.settings, "raw_conversion_output_dir", None)
    monkeypatch.setattr(import_jobs.settings, "raw_conversion_timeout_seconds", 10)
    monkeypatch.setattr(import_jobs.settings, "raw_conversion_force", False)

    def fake_ingest_universal_diann(
        *,
        root: Path,
        database_url: str,
        slug: str,
        name: str,
        replace: bool,
        spectra_source: str | None,
        extra_mzml_roots: tuple[Path, ...] | None,
        raw_conversion_by_mzml_key: dict[str, dict[str, Any]] | None,
        pfmb_sidecar_dir: Path | None,
        progress_callback: Any,
        **_kwargs: Any,
    ) -> SimpleNamespace:
        del database_url, slug, name, replace, spectra_source, pfmb_sidecar_dir, progress_callback
        run_files = diann_adapter.discover_bu_runs(
            root,
            extra_mzml_roots=extra_mzml_roots,
            raw_conversion_by_mzml_key=raw_conversion_by_mzml_key,
        )
        diann_adapter._insert_runs(
            _RunInsertConnection(inserted_run_metadata),
            dataset_id=7,
            run_files=run_files,
        )
        return SimpleNamespace(dataset_id=7, run_id=1, proteins=1, proteoforms=0, matches=1)

    monkeypatch.setattr(import_jobs, "ingest_universal_diann", fake_ingest_universal_diann)
    monkeypatch.setattr(
        import_jobs,
        "ingest_mzml_only",
        lambda **kwargs: (
            mzml_only_calls.append(kwargs)
            or SimpleNamespace(dataset_id=7, run_id=1, runs=1, proteins=0, proteoforms=0, matches=0)
        ),
    )
    return {
        "updates": updates,
        "derived_calls": derived_calls,
        "inserted_run_metadata": inserted_run_metadata,
        "mzml_only_calls": mzml_only_calls,
        "engine": engine,
    }


def _run_job(root: Path, *, import_type: str | None = None) -> None:
    import_jobs.run_path_import_job(
        job_id="job-raw",
        source_path=str(root),
        slug="raw-test",
        name="RAW Test",
        description=None,
        import_type=import_type,
    )


def test_duplicate_lookup_uses_fingerprint_and_import_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _NoopEngine()
    monkeypatch.setattr(import_jobs, "_db_engine", engine)

    assert import_jobs.find_dataset_with_fingerprint("a" * 32, "DIA_CLIP") is None

    statement, params = engine.statements[-1]
    assert "source_import_kind = :import_kind" in statement
    assert params == {"h": "a" * 32, "import_kind": "DIA_CLIP"}


def test_raw_import_job_converts_and_records_run_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _make_diann_root(tmp_path, raw=True, mzml=False)
    converter = tmp_path / "ThermoRawFileParser.exe"
    converter.write_bytes(b"fake")
    state = _install_common_patches(monkeypatch)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(import_jobs.settings, "thermo_raw_file_parser_exe", converter)

    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append({"command": command, **kwargs})
        raw_path = Path(_command_value(command, "-i="))
        output_dir = Path(_command_value(command, "-o="))
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{raw_path.stem}.mzML").write_text(
            "<mzML><indexListOffset>1</indexListOffset></mzML>",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="converted", stderr="")

    monkeypatch.setattr("app.raw_conversion.thermo_raw_file_parser.subprocess.run", fake_run)

    _run_job(root)

    stages = [update.get("stage") for update in state["updates"]]
    assert "raw_conversion" in stages
    assert state["derived_calls"] == [7]
    assert calls and calls[0]["shell"] is False
    assert "-f=2" in calls[0]["command"]
    assert "-g" not in calls[0]["command"]
    metadata = state["inserted_run_metadata"][0]
    assert metadata["raw_format"] == "mzml"
    assert metadata["raw_path"] == str((root / "sample.raw").resolve())
    assert metadata["mzml_file_path"].endswith("sample.mzML")
    assert metadata["raw_conversion"]["status"] == "converted"
    assert metadata["raw_conversion"]["converter_name"] == "ThermoRawFileParser"
    assert not any(update.get("status") == "failed" for update in state["updates"])


def test_import_job_without_raw_does_not_call_converter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _make_diann_root(tmp_path, raw=False, mzml=True)
    state = _install_common_patches(monkeypatch)
    monkeypatch.setattr(import_jobs.settings, "thermo_raw_file_parser_exe", None)

    def fail_converter(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("RAW converter must not be called when plan contains no RAW files")

    monkeypatch.setattr(import_jobs, "convert_raw_files_for_import", fail_converter)

    _run_job(root)

    stages = [update.get("stage") for update in state["updates"]]
    assert "raw_conversion" not in stages
    assert state["derived_calls"] == [7]
    metadata = state["inserted_run_metadata"][0]
    assert metadata["raw_format"] == "mzml"
    assert "raw_conversion" not in metadata
    assert not any(update.get("status") == "failed" for update in state["updates"])


def test_explicit_diaclip_type_routes_the_shared_diann_layout_to_diaclip_adapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _make_diann_root(tmp_path, raw=False, mzml=True)
    state = _install_common_patches(monkeypatch)
    selections: list[tuple[str, Path]] = []
    clip_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        import_jobs,
        "validate_import_selection",
        lambda selected, ingest_root, _plan: selections.append((selected.value, ingest_root)),
    )
    monkeypatch.setattr(
        import_jobs,
        "ingest_universal_diann",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("DIA-NN adapter must not handle an explicit DIA_CLIP import")
        ),
    )
    monkeypatch.setattr(
        import_jobs,
        "ingest_universal_diaclip",
        lambda **kwargs: (
            clip_calls.append(kwargs)
            or SimpleNamespace(dataset_id=7, run_id=1, proteins=1, proteoforms=0, matches=1)
        ),
    )

    _run_job(root, import_type="BU_DIA_CLIP")

    assert selections == [("BU_DIA_CLIP", root.resolve())]
    assert clip_calls and clip_calls[0]["root"] == root.resolve()
    final_updates = [
        params
        for statement, params in state["engine"].statements
        if "source_import_kind" in statement and params and params.get("dataset_id") == 7
    ]
    assert final_updates[-1]["source_import_kind"] == "BU_DIA_CLIP"
    assert not any(update.get("status") == "failed" for update in state["updates"])


def test_toppic_native_type_prepares_details_and_uses_distinct_source_tag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "native"
    (root / "topfd").mkdir(parents=True)
    mzml = root / "run.mzML"
    mzml.write_text("<mzML />", encoding="utf-8")
    derived = tmp_path / "derived"
    (derived / "data" / "prsms").mkdir(parents=True)
    state = _install_common_patches(monkeypatch)
    prepare_calls: list[dict[str, Any]] = []
    ingest_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        import_jobs,
        "plan_zip_ingest",
        lambda _root: ImportPlan(
            shape=DatasetShape.TOPPIC_NATIVE,
            spectra_source="mzml_memory",
            need_toppic_multirun_pass=False,
        ),
    )
    monkeypatch.setattr(
        import_jobs,
        "prepare_toppic_native_output",
        lambda **kwargs: (
            prepare_calls.append(kwargs)
            or PreparedTopPicNativeOutput(
                root=derived,
                prsm_count=2,
                skipped_prsm_count=0,
                mzml_files=(mzml,),
            )
        ),
    )
    monkeypatch.setattr(
        import_jobs,
        "extract_spectrum_file_names_from_prsms",
        lambda _path: {"run.mzML"},
    )
    monkeypatch.setattr(
        import_jobs,
        "build_one_to_one_mapping",
        lambda **_kwargs: {"run": mzml},
    )
    monkeypatch.setattr(
        import_jobs,
        "ingest_universal_prsm_js",
        lambda **kwargs: (
            ingest_calls.append(kwargs)
            or SimpleNamespace(
                dataset_id=7,
                run_id=1,
                proteins=1,
                proteoforms=1,
                matches=2,
            )
        ),
    )

    _run_job(root, import_type="TD_TOPPIC_NATIVE")

    assert prepare_calls[0]["source_root"] == root.resolve()
    assert ingest_calls[0]["root"] == derived
    assert ingest_calls[0]["source_software"] == "TopPIC Native Output"
    assert ingest_calls[0]["import_mode"] == "toppic_native"
    final_updates = [
        params
        for statement, params in state["engine"].statements
        if "source_import_kind" in statement and params and params.get("dataset_id") == 7
    ]
    assert final_updates[-1]["source_import_kind"] == "TD_TOPPIC_NATIVE"
    assert not any(update.get("status") == "failed" for update in state["updates"])


def test_raw_import_job_fails_when_converter_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _make_diann_root(tmp_path, raw=True, mzml=False)
    state = _install_common_patches(monkeypatch)
    monkeypatch.setattr(import_jobs.settings, "thermo_raw_file_parser_exe", None)

    def fail_resolver(_configured_path: object) -> None:
        raise RawConversionError("raw_converter_missing", "test converter missing")

    monkeypatch.setattr("app.raw_conversion.service.resolve_thermo_raw_file_parser_exe", fail_resolver)

    _run_job(root)

    failed = [update for update in state["updates"] if update.get("status") == "failed"]
    assert failed
    assert "raw_converter_missing" in str(failed[-1].get("error"))
    assert state["derived_calls"] == []
    assert state["inserted_run_metadata"] == []


def test_raw_import_job_skips_existing_same_stem_mzml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _make_diann_root(tmp_path, raw=True, mzml=True)
    state = _install_common_patches(monkeypatch)
    monkeypatch.setattr(import_jobs.settings, "thermo_raw_file_parser_exe", None)

    def fail_resolver(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("RAW converter must not be discovered when same-stem mzML is reused")

    monkeypatch.setattr("app.raw_conversion.service.resolve_thermo_raw_file_parser_exe", fail_resolver)

    _run_job(root)

    metadata = state["inserted_run_metadata"][0]
    assert metadata["raw_format"] == "mzml"
    assert metadata["raw_path"] == str((root / "sample.raw").resolve())
    assert metadata["mzml_file_path"] == str((root / "sample.mzML").resolve())
    assert metadata["raw_conversion"]["status"] == "skipped_existing_mzml"
    assert metadata["raw_conversion"]["converter_name"] == "ThermoRawFileParser"
    assert state["derived_calls"] == [7]
    assert not any(update.get("status") == "failed" for update in state["updates"])


def test_raw_import_job_rejects_existing_same_stem_mzml_without_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _make_diann_root(tmp_path, raw=True, mzml=False)
    (root / "sample.mzML").write_text("<mzML></mzML>", encoding="utf-8")
    state = _install_common_patches(monkeypatch)
    monkeypatch.setattr(import_jobs.settings, "thermo_raw_file_parser_exe", None)

    def fail_resolver(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("RAW converter must not be discovered when force=false and same-stem mzML exists")

    monkeypatch.setattr("app.raw_conversion.service.resolve_thermo_raw_file_parser_exe", fail_resolver)

    _run_job(root)

    failed = [update for update in state["updates"] if update.get("status") == "failed"]
    assert failed
    assert "raw_conversion_output_invalid" in str(failed[-1].get("error"))
    assert "existing mzML is not indexed" in str(failed[-1].get("error"))
    assert state["derived_calls"] == []
    assert state["inserted_run_metadata"] == []


def test_mzml_only_import_job_does_not_call_converter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "spectra"
    root.mkdir()
    (root / "sample.mzML").write_text("<mzML><indexListOffset>1</indexListOffset></mzML>", encoding="utf-8")
    (root / "sample.json").write_text("{}", encoding="utf-8")
    state = _install_common_patches(monkeypatch)
    monkeypatch.setattr(import_jobs.settings, "thermo_raw_file_parser_exe", None)

    def fail_converter(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("RAW converter must not be called for mzML-only imports")

    monkeypatch.setattr(import_jobs, "convert_raw_files_for_import", fail_converter)

    _run_job(root, import_type="TD_MZML")

    stages = [update.get("stage") for update in state["updates"]]
    assert "raw_conversion" not in stages
    assert state["derived_calls"] == [7]
    assert state["mzml_only_calls"]
    assert state["mzml_only_calls"][0]["extra_mzml_roots"] is None
    assert state["mzml_only_calls"][0]["analysis_mode"] == "TOP_DOWN"
    assert state["mzml_only_calls"][0]["source_software"] == "Top-Down mzML"


def test_dda_raw_import_job_converts_before_mzml_only_adapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "raw-only"
    root.mkdir()
    (root / "sample.raw").write_bytes(b"raw")
    converter = tmp_path / "ThermoRawFileParser.exe"
    converter.write_bytes(b"fake")
    state = _install_common_patches(monkeypatch)
    monkeypatch.setattr(import_jobs.settings, "thermo_raw_file_parser_exe", converter)

    def fake_run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        raw_path = Path(_command_value(command, "-i="))
        output_dir = Path(_command_value(command, "-o="))
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{raw_path.stem}.mzML").write_text(
            "<mzML><indexListOffset>1</indexListOffset></mzML>",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="converted", stderr="")

    monkeypatch.setattr("app.raw_conversion.thermo_raw_file_parser.subprocess.run", fake_run)

    _run_job(root, import_type="DDA_RAW")

    stages = [update.get("stage") for update in state["updates"]]
    assert "raw_conversion" in stages
    assert state["derived_calls"] == [7]
    call = state["mzml_only_calls"][0]
    assert call["extra_mzml_roots"] is not None
    assert call["raw_conversion_by_mzml_key"]["sample"]["raw_conversion"]["status"] == "converted"
    assert call["analysis_mode"] == "BOTTOM_UP"
    assert call["source_software"] == "DDA Thermo RAW"


def test_raw_only_import_job_fails_when_converter_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "raw-only"
    root.mkdir()
    (root / "sample.raw").write_bytes(b"raw")
    state = _install_common_patches(monkeypatch)
    monkeypatch.setattr(import_jobs.settings, "thermo_raw_file_parser_exe", None)

    def fail_resolver(_configured_path: object) -> None:
        raise RawConversionError("raw_converter_missing", "test converter missing")

    monkeypatch.setattr("app.raw_conversion.service.resolve_thermo_raw_file_parser_exe", fail_resolver)

    _run_job(root)

    failed = [update for update in state["updates"] if update.get("status") == "failed"]
    assert failed
    assert "raw_converter_missing" in str(failed[-1].get("error"))
    assert state["derived_calls"] == []
    assert state["mzml_only_calls"] == []
