from __future__ import annotations

import json
import pickle
import struct
from pathlib import Path
from typing import Any

from app.pfmb.index_builder import build_index_json_from_pos_pkl, read_pfmb_record_count
from app.pfmb.locator import detect_sidecar
from app.pfmb.sidecar_prepare import generate_pfmb_sidecar, prepare_bu_pfmb_sidecar


def _write_pos_pkl(path: Path) -> None:
    rows = [
        {
            "peptide": "PEPTIDE",
            "precursor_charge": 2,
            "frag.RT": [10.0, 15.0],
            "frag.chrom": [[1.0, 5.0], [0.0, 2.0]],
        },
        {
            "Modified.Sequence": "AC[+57.021464]DK",
            "Precursor.Charge": 3,
            "frag": {"RT": [20.0]},
            "apex_slot": 0,
        },
    ]
    with open(path, "wb") as handle:
        pickle.dump(rows, handle)


def _write_pfmb_header(path: Path, record_count: int) -> None:
    header = struct.pack("<III", 3, 1, record_count)
    path.write_bytes(b"PFMB" + struct.pack("<I", len(header)) + header)


def _write_sidecar_dir(path: Path, *, record_count: int = 0) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _write_pfmb_header(path / "results.pfmb", record_count)
    (path / "index.json").write_text('{"items":[]}', encoding="utf-8")


def _source_manifest(pos: Path) -> dict[str, Any]:
    stat = pos.stat()
    return {
        "source": {
            "pos_pkl": str(pos.resolve()),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    }


def test_detect_sidecar_accepts_delivery_data_subdir(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "results.pfmb").write_bytes(b"PFMB")
    (data / "index.json").write_text("{}", encoding="utf-8")

    sidecar = detect_sidecar(tmp_path)

    assert sidecar is not None
    assert sidecar["pfmb_path"].endswith("results.pfmb")
    assert sidecar["index_path"].endswith("index.json")


def test_build_index_json_from_pos_pkl_expands_rt_slots(tmp_path: Path) -> None:
    pos = tmp_path / "run.pos.pkl"
    index = tmp_path / "index.json"
    _write_pos_pkl(pos)

    result = build_index_json_from_pos_pkl(pos, index, expected_record_count=2)
    data = json.loads(index.read_text(encoding="utf-8"))

    assert result.item_count == 3
    assert result.source_row_count == 2
    assert data["items"][0]["source_row"] == 0
    assert data["items"][0]["slot_index"] == 0
    assert data["items"][1]["slot_rt"] == 15.0
    assert data["items"][1]["apex_slot"] == 1
    assert data["items"][2]["peptide"] == "AC[+57.021464]DK"
    assert data["items"][2]["precursor_charge"] == 3


def test_build_index_json_from_columnar_pos_pkl(tmp_path: Path) -> None:
    pos = tmp_path / "run.pos.pkl"
    index = tmp_path / "index.json"
    with open(pos, "wb") as handle:
        pickle.dump(
            {
                "peptide": ["PEPTIDE", "ACDK"],
                "precursor_charge": [2, 3],
                "frag.RT": [[10.0, 15.0], [20.0]],
                "frag.chrom": [[[1.0, 5.0]], [[4.0]]],
            },
            handle,
        )

    result = build_index_json_from_pos_pkl(pos, index, expected_record_count=2)
    data = json.loads(index.read_text(encoding="utf-8"))

    assert result.item_count == 3
    assert result.source_row_count == 2
    assert data["items"][0]["peptide"] == "PEPTIDE"
    assert data["items"][2]["peptide"] == "ACDK"
    assert data["items"][2]["precursor_charge"] == 3


def test_build_index_json_from_nested_pre_frag_pos_pkl(tmp_path: Path) -> None:
    pos = tmp_path / "run.pos.pkl"
    index = tmp_path / "index.json"
    with open(pos, "wb") as handle:
        pickle.dump(
            [
                {
                    "pre": {"peptide": "PEPTIDE", "charge": 2},
                    "frag": {
                        "RT": [10.0, 15.0],
                        "chrom": [[1.0, 5.0], [0.0, 2.0]],
                    },
                    "label": 1,
                }
            ],
            handle,
        )

    result = build_index_json_from_pos_pkl(pos, index, expected_record_count=1)
    data = json.loads(index.read_text(encoding="utf-8"))

    assert result.item_count == 2
    assert result.source_row_count == 1
    assert data["items"][0]["peptide"] == "PEPTIDE"
    assert data["items"][0]["precursor_charge"] == 2
    assert data["items"][1]["apex_slot"] == 1


def test_generate_pfmb_sidecar_runs_bridge_and_builds_index(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    pos = tmp_path / "run.pos.pkl"
    out = tmp_path / "pfmb"
    bridge = tmp_path / "pfmb_bridge.exe"
    bridge.write_text("fake", encoding="utf-8")
    _write_pos_pkl(pos)
    calls: list[list[str]] = []

    def fake_run_bridge(args: list[str], *, cwd: Path, env: dict[str, str]) -> None:
        calls.append(args)
        if "ingest" in args:
            (out / "prsm.cache").write_bytes(b"cache")
            (out / "ingest_manifest.json").write_text("{}", encoding="utf-8")
        if "run" in args:
            _write_pfmb_header(out / "results.pfmb", 3)
            (out / "summary.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr("app.pfmb.sidecar_prepare._run_bridge", fake_run_bridge)

    sidecar_dir = generate_pfmb_sidecar(
        pos_pkl=pos,
        output_dir=out,
        bridge_exe=bridge,
        disable_jit=True,
    )

    assert sidecar_dir == out.resolve()
    assert detect_sidecar(out) is not None
    assert read_pfmb_record_count(out / "results.pfmb") == 3
    assert (out / "generation_manifest.json").is_file()
    assert calls[0][1] == "ingest"
    assert calls[1][1] == "run"


def test_prepare_bu_pfmb_sidecar_skips_when_no_pos_pkl(tmp_path: Path) -> None:
    result = prepare_bu_pfmb_sidecar(
        tmp_path,
        slug="demo",
        output_root=tmp_path / "BU- Fragment Match",
        bridge_exe=tmp_path / "missing.exe",
    )

    assert result.sidecar_dir is None
    assert result.status == "skipped_no_pos_pkl"


def test_prepare_bu_pfmb_sidecar_prefers_source_pfmb(tmp_path: Path) -> None:
    source_sidecar = tmp_path / "data"
    generated_root = tmp_path / "BU- Fragment Match"
    generated_sidecar = generated_root / "demo"
    _write_sidecar_dir(source_sidecar)
    _write_sidecar_dir(generated_sidecar)

    result = prepare_bu_pfmb_sidecar(
        tmp_path,
        slug="demo",
        output_root=generated_root,
        bridge_exe=tmp_path / "missing.exe",
    )

    assert result.sidecar_dir == tmp_path.resolve()
    assert result.status == "existing"


def test_build_index_json_rejects_expanded_count_mismatch(tmp_path: Path) -> None:
    pos = tmp_path / "run.pos.pkl"
    index = tmp_path / "index.json"
    _write_pos_pkl(pos)

    try:
        build_index_json_from_pos_pkl(
            pos,
            index,
            expected_record_count=2,
            expected_expanded_record_count=99,
        )
    except ValueError as exc:
        assert "expanded slot count mismatch" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_find_generated_sidecar_rejects_v1_cache(tmp_path: Path) -> None:
    pos = tmp_path / "run.pos.pkl"
    generated_root = tmp_path / "BU- Fragment Match"
    generated_sidecar = generated_root / "demo"
    _write_pos_pkl(pos)
    _write_sidecar_dir(generated_sidecar, record_count=2)
    (generated_sidecar / "generation_manifest.json").write_text(
        json.dumps(_source_manifest(pos)),
        encoding="utf-8",
    )

    from app.pfmb.sidecar_prepare import find_generated_sidecar_dir

    assert find_generated_sidecar_dir(slug="demo", output_root=generated_root, pos_pkl=pos) is None


def test_prepare_bu_pfmb_sidecar_reuses_matching_generated_pfmb(tmp_path: Path) -> None:
    pos = tmp_path / "run.pos.pkl"
    generated_root = tmp_path / "BU- Fragment Match"
    generated_sidecar = generated_root / "demo"
    _write_pos_pkl(pos)
    _write_sidecar_dir(generated_sidecar, record_count=3)
    manifest = _source_manifest(pos)
    manifest["pfmb_schema_version"] = 2
    manifest["counts"] = {"expanded_records": 3, "source_rows": 2}
    (generated_sidecar / "generation_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    result = prepare_bu_pfmb_sidecar(
        tmp_path,
        slug="demo",
        output_root=generated_root,
        bridge_exe=tmp_path / "missing.exe",
    )

    assert result.sidecar_dir == generated_sidecar.resolve()
    assert result.status == "existing_generated"


def test_prepare_bu_pfmb_sidecar_ignores_stale_generated_pfmb(tmp_path: Path) -> None:
    pos = tmp_path / "run.pos.pkl"
    stale_pos = tmp_path / "other.pos.pkl"
    generated_root = tmp_path / "BU- Fragment Match"
    generated_sidecar = generated_root / "demo"
    _write_pos_pkl(pos)
    _write_sidecar_dir(generated_sidecar)
    (generated_sidecar / "generation_manifest.json").write_text(
        json.dumps({"source": {"pos_pkl": str(stale_pos.resolve())}}),
        encoding="utf-8",
    )

    result = prepare_bu_pfmb_sidecar(
        tmp_path,
        slug="demo",
        output_root=generated_root,
        bridge_exe=tmp_path / "missing.exe",
    )

    assert result.sidecar_dir is None
    assert result.status == "skipped_bridge_missing"
