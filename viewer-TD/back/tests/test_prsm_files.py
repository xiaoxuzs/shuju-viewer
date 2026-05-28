from __future__ import annotations

import json

from app.services.prsm_files import (
    extract_spectrum_file_name,
    get_prsm_root,
    has_prsm_files,
    iter_prsm_files,
    load_prsm_document,
    prsm_detail_path,
    prsm_paths_by_id,
)


def _prsm_doc(spectrum_file_name: str = "sample.mzML") -> dict:
    return {
        "prsm": {
            "ms": {
                "ms_header": {
                    "spectrum_file_name": spectrum_file_name,
                },
            },
        },
    }


def test_iter_prsm_files_supports_configured_suffixes(tmp_path):
    (tmp_path / "prsm2.json").write_text(json.dumps(_prsm_doc("b.mzML")), encoding="utf-8")
    (tmp_path / "prsm1.js").write_text(f"prsm_data = {json.dumps(_prsm_doc('a.mzML'))};", encoding="utf-8")
    (tmp_path / "prsm3.txt").write_text(json.dumps(_prsm_doc("c.mzML")), encoding="utf-8")
    (tmp_path / "other.js").write_text("{}", encoding="utf-8")

    assert has_prsm_files(tmp_path)
    assert [path.name for path in iter_prsm_files(tmp_path)] == ["prsm1.js", "prsm2.json", "prsm3.txt"]
    assert prsm_detail_path(tmp_path, 2) == tmp_path / "prsm2.json"


def test_prsm_paths_by_id_matches_prsm_detail_path(tmp_path):
    (tmp_path / "prsm2.json").write_text(json.dumps(_prsm_doc("b.mzML")), encoding="utf-8")
    (tmp_path / "prsm1.js").write_text(f"prsm_data = {json.dumps(_prsm_doc('a.mzML'))};", encoding="utf-8")
    (tmp_path / "prsm3.txt").write_text(json.dumps(_prsm_doc("c.mzML")), encoding="utf-8")

    by_id = prsm_paths_by_id(tmp_path)
    for pid in (1, 2, 3):
        assert by_id.get(pid) == prsm_detail_path(tmp_path, pid)


def test_load_prsm_document_normalizes_wrappers(tmp_path):
    path = tmp_path / "prsm4.js"
    path.write_text(f"prsm_data = {json.dumps(_prsm_doc('wrapped.mzML'))};", encoding="utf-8")

    doc = load_prsm_document(path)
    root = get_prsm_root(doc)

    assert root["ms"]["ms_header"]["spectrum_file_name"] == "wrapped.mzML"
    assert extract_spectrum_file_name(path) == "wrapped.mzML"
