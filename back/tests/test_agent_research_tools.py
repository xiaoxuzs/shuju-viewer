from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.agent_import.research_tools import AgentResearchToolbox


def test_research_tools_are_case_scoped_and_return_bounded_statistics(tmp_path: Path) -> None:
    (tmp_path / "table.tsv").write_text(
        "id\tvalue\tgroup\n1\t1.5\tA\n2\tNaN\tB\n3\t\tA\n",
        encoding="utf-8",
    )
    (tmp_path / "metadata.json").write_text(
        '{"path":"C:/private/source.raw","instrument":"Orbitrap"}',
        encoding="utf-8",
    )
    (tmp_path / "params.xml").write_text(
        "<Params><Mode>DDA</Mode><Nested><Mode>HCD</Mode></Nested></Params>",
        encoding="utf-8",
    )
    (tmp_path / "db.fasta").write_text(
        ">sp|P1|ONE Protein one\nPEPTIDE\n>P2 Protein two\nAAAA\n>P3 Duplicate\nAAAA\n",
        encoding="utf-8",
    )
    toolbox = AgentResearchToolbox(tmp_path)

    table = toolbox.execute("inspect_tabular_file", {"relative_path": "table.tsv", "columns": []})
    metadata = toolbox.execute("inspect_json_file", {"relative_path": "metadata.json"})
    xml = toolbox.execute("inspect_xml_file", {"relative_path": "params.xml", "tag_names": ["Mode"]})
    fasta = toolbox.execute("inspect_fasta", {"relative_path": "db.fasta", "accessions": ["P1", "P9"]})

    assert table["row_count"] == 3
    assert table["inspected_columns"]["value"]["nan_literal"] == 1
    assert metadata["value"]["path"].startswith("<redacted-absolute-path>")
    assert [item["value"] for item in xml["leaf_values"]] == ["DDA", "HCD"]
    assert fasta["record_count"] == 3
    assert fasta["duplicate_sequence_count"] == 1
    assert fasta["matched_accessions"] == ["P1"]
    assert fasta["sequences_returned_to_model"] is False

    with pytest.raises(ValueError):
        toolbox.execute("inspect_json_file", {"relative_path": "../metadata.json"})


def test_generic_inventory_and_inspection_tools_return_auditable_observations(tmp_path: Path) -> None:
    (tmp_path / "z.tsv").write_text("id\tscore\n1\t0.5\n", encoding="utf-8")
    (tmp_path / "a.jsonl").write_text('{"id":1}\n{"id":2}\n', encoding="utf-8")
    (tmp_path / "db.fasta").write_text(">P1\nPEPTIDE\n", encoding="utf-8")
    toolbox = AgentResearchToolbox(tmp_path)

    first = toolbox.execute("list_source_inventory", {"limit": 2})
    second = toolbox.execute(
        "list_source_inventory",
        {"limit": 2, "cursor": first["next_cursor"]},
    )
    table = toolbox.execute("inspect_source_file", {"relative_path": "z.tsv"})
    fasta = toolbox.execute("inspect_source_file", {"relative_path": "db.fasta"})

    assert first["total_count"] == 3
    assert second["total_count"] == 3
    assert [item["relative_path"] for item in first["items"] + second["items"]] == [
        "a.jsonl",
        "db.fasta",
        "z.tsv",
    ]
    assert second["next_cursor"] is None
    assert first["file_content_returned_to_model"] is False
    assert table["status"] == "COMPLETE"
    assert table["facts"]["row_count"] == 1
    assert table["budget"]["bytes_read"] > 0
    assert len(table["hashes"]["observation_sha256"]) == 64
    assert table["inspector_version"]
    assert fasta["facts"]["sequences_returned"] is False
    assert "PEPTIDE" not in str(fasta["facts"])


def test_generic_inspection_reports_opaque_binary_as_unsupported(tmp_path: Path) -> None:
    (tmp_path / "opaque.vendor").write_bytes(b"\x00\x01closed\x00format")
    toolbox = AgentResearchToolbox(tmp_path)

    observation = toolbox.execute("inspect_source_file", {"relative_path": "opaque.vendor"})

    assert observation["status"] == "UNSUPPORTED"
    assert observation["detected_format"] == "binary"
    assert observation["facts"]["file_content_returned"] is False
    assert observation["budget"]["bytes_read"] > 0
    assert len(observation["hashes"]["inspection_sample_sha256"]) == 64


def test_generic_inspection_never_returns_mzml_peak_arrays(tmp_path: Path) -> None:
    (tmp_path / "run.mzML").write_text(
        """<mzML xmlns="http://psi.hupo.org/ms/mzml"><run><spectrumList count="1">
<spectrum id="scan=1" defaultArrayLength="2">
<cvParam accession="MS:1000511" name="ms level" value="2"/>
<binaryDataArrayList><binaryDataArray><binary>AAAA</binary></binaryDataArray></binaryDataArrayList>
</spectrum></spectrumList></run></mzML>""",
        encoding="utf-8",
    )
    toolbox = AgentResearchToolbox(tmp_path)

    observation = toolbox.execute("inspect_source_file", {"relative_path": "run.mzML"})

    assert observation["facts"]["peak_arrays_returned"] is False
    assert observation["facts"]["binary_values_decoded"] is False
    assert "AAAA" not in str(observation["facts"])


def test_generic_research_tool_definitions_are_exposed(tmp_path: Path) -> None:
    toolbox = AgentResearchToolbox(tmp_path)

    definitions = {item["function"]["name"]: item["function"] for item in toolbox.definitions()}

    assert definitions["list_source_inventory"]["parameters"]["properties"]["limit"]["maximum"] == 200
    assert definitions["inspect_source_file"]["parameters"]["required"] == ["relative_path"]


def test_single_sample_mzml_research_summary_matches_real_data() -> None:
    configured = os.getenv("VIEWER_AGENT_MAXQUANT_FIXTURE_ROOT")
    base = (
        Path(configured)
        if configured
        else Path(__file__).resolve().parents[2].parent
        / "viewer-agent"
        / "maxquant"
        / "maxquant-viz-data"
    )
    root = base / "single-sample"
    if not root.is_dir():
        pytest.skip("single-sample research fixture is unavailable")
    toolbox = AgentResearchToolbox(root)

    summary = toolbox.execute(
        "inspect_mzml",
        {"relative_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML"},
    )
    scans = toolbox.execute(
        "validate_scan_relation",
        {
            "table_path": "evidence.txt",
            "scan_field": "MS/MS scan number",
            "mzml_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML",
            "split_semicolon": False,
        },
    )

    assert summary["spectrum_count"] == 7534
    assert summary["ms_level_counts"] == {"1": 1431, "2": 6103}
    assert summary["peak_pair_counts"]["total"] == 3949930
    assert summary["chromatograms"] == [
        {"id": "BasePeak_0", "type": "basepeak chromatogram", "point_count": 7534}
    ]
    assert summary["peak_values_returned_to_model"] is False
    assert scans["matched_count"] == 35
    assert scans["missing_count"] == 0
