import csv
import json
from pathlib import Path
import zipfile

import pytest

from app.agent_import.errors import AgentImportError
from app.agent_import.model_context import enforce_request, manifest_view, observation_views
from app.agent_import.research_tools import AgentResearchToolbox
from app.source_inspection.preview import preview_file


def test_parsed_multiline_csv_ten_records_and_late_anomaly(tmp_path):
    path = tmp_path / "input.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["id", "value"])
        for i in range(12):
            writer.writerow([i, "multiline\nvalue" if i == 0 else i])
        writer.writerow([13, "bad", "extra"])
    result = AgentResearchToolbox(tmp_path).execute("inspect_source_file", {"relative_path": path.name})
    assert len(result["preview"]["records"]) == 10
    assert result["preview"]["records"][0]["value"] == "multiline\nvalue"
    assert result["status"] == "INVALID"
    assert result["facts"]["rows_observed"] == 13
    assert result["facts"]["row_count"] is None
    assert result["preview"]["total_rows"] is None


def test_jsonl_native_null_zero_and_paging(tmp_path):
    path = tmp_path / "input.jsonl"
    path.write_text("\n".join(json.dumps({"x": i, "empty": None, "long": "z" * 1000}) for i in range(14)), encoding="utf-8")
    result = preview_file(path)
    assert len(result["records"]) == 10
    assert result["records"][0]["x"] == 0
    assert result["records"][0]["empty"] is None
    assert result["records"][0]["long"].endswith("[truncated]")
    with pytest.raises(ValueError, match="purpose"):
        preview_file(path, row_offset=10)
    assert len(preview_file(path, row_offset=10, purpose="inspect last rows")["records"]) == 4


def test_wide_table_pages_keep_field_identity(tmp_path):
    path = tmp_path / "wide.tsv"
    path.write_text("\t".join(f"field{i}" for i in range(80)) + "\n" + "\t".join("0" for _ in range(80)), encoding="utf-8")
    first = preview_file(path)
    second = preview_file(path, field_offset=first["next_field_offset"])
    assert first["fields"][0] == "field0"
    assert second["fields"][0] == "field32"
    assert len(second["fields"]) == 32
    assert len(preview_file(path, field_limit=2)["fields"]) == 2


def test_original_field_name_is_not_silently_trimmed(tmp_path):
    path = tmp_path / "names.tsv"
    path.write_text(" raw field \tzero\nabc\t0\n", encoding="utf-8")
    observation = AgentResearchToolbox(tmp_path).execute("inspect_source_file", {"relative_path": path.name})
    assert observation["preview"]["fields"] == [" raw field ", "zero"]
    assert observation["facts"]["columns"][0]["name"] == " raw field "


def test_cumulative_budget_cannot_be_reset_by_repeated_tool_calls(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text("\n".join(json.dumps({f"k{i}": "x" * 100 for i in range(10)}) for _ in range(12)))
    toolbox = AgentResearchToolbox(tmp_path)
    completed = 0
    with pytest.raises(ValueError, match="budget"):
        for _ in range(100):
            toolbox.execute("preview_source_file", {"relative_path": path.name})
            completed += 1
    assert 1 < completed < 30


def test_old_observations_and_manifests_do_not_expand_raw_history():
    observations = [{"call_id": "old", "payload": {"records": [{"x": i} for i in range(500)], "text": "z" * 100000}}]
    view = observation_views(observations)
    assert len(view[0]["payload"]["records"]) == 10
    assert view[0]["view_truncated"]
    assert len(observations[0]["payload"]["records"]) == 500
    manifest = manifest_view({"samples": [{"content": "DO_NOT_SEND"}], "files": []})
    assert "DO_NOT_SEND" not in json.dumps(manifest)
    for role in ("research", "implementation", "review"):
        with pytest.raises(AgentImportError, match="byte budget"):
            enforce_request({"messages": [{"role": role, "content": "x" * 200000}]})


def test_observation_schemas_survive_wide_fields_and_late_payload_budget(monkeypatch):
    import copy
    from app.agent_import import model_context

    observations = [{"call_id": str(i), "payload": {
        "relative_path": f"table-{i}.tsv",
        "facts": {"column_count": count, "columns": [{"name": f"field-{n}"} for n in range(count)],
                  "fields": [{"name": "field-69", "unit": "source_intensity"}] if count == 70 else []},
        "preview": {"records": [{"text": "x" * 1000} for _ in range(10)]}}}
        for i, count in enumerate((70, 41))]
    original = copy.deepcopy(observations)
    monkeypatch.setattr(model_context, "MAX_OBSERVATION_BYTES", 6000)
    views = observation_views(observations)
    assert len(views[0]["source_schema"]["physical_fields"]) == 70
    assert views[0]["source_schema"]["physical_fields"][-1]["unit"] == "source_intensity"
    assert len(views[1]["source_schema"]["physical_fields"]) == 41
    assert all(v["source_schema"]["field_names_complete"] for v in views)
    assert any("payload_omitted" in v for v in views)
    assert model_context.size(views) <= 6000
    assert observations == original


def test_candidate_transport_compacts_schema_without_removing_real_fields(monkeypatch):
    from app.agent_import import model_provider
    from app.core.config import settings
    bodies = []
    monkeypatch.setattr(settings, "agent_model_authorization_required", True)
    def capture(*args, **kwargs):
        bodies.append(kwargs["body"])
        return {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}
    monkeypatch.setattr(model_provider, "request_model_json", capture)
    schema = {"title": "Display name", "type": "object", "properties": {"title": {"type": "string", "maxLength": 20}}}
    model_provider._chat_json(base_url="http://fixture.invalid/v1", api_key="fixture", model="fixture", timeout=1,
        system_prompt="test", payload={"candidate_json_schema": schema}, max_tokens=100, role="implementation")
    supplied = json.loads(bodies[0]["messages"][1]["content"])["candidate_json_schema"]
    assert "title" not in supplied
    assert supplied["properties"]["title"] == schema["properties"]["title"]


def test_downstream_roles_keep_schema_units_and_facts_without_repeating_raw_preview():
    from copy import deepcopy
    observation = {"call_id": "field-observation", "payload": {"relative_path": "table.tsv",
        "facts": {"columns": [{"name": "RT", "unit": "minute"}], "row_count": 101, "acquisition_mode": "dda"},
        "preview": {"records": [{"RT": "RAW_PREVIEW_ONLY"}]}}}
    retained = deepcopy(observation)
    view = observation_views([observation], include_previews=False)[0]
    assert "RAW_PREVIEW_ONLY" not in json.dumps(view)
    assert view["source_schema"]["physical_fields"][0]["unit"] == "minute"
    assert view["payload"]["facts"]["row_count"] == 101
    assert view["payload"]["facts"]["acquisition_mode"] == "dda"
    assert observation == retained


def test_statistical_examples_are_omitted_but_scientific_sample_metadata_survives():
    observation = {"payload": {"facts": {"samples": ["biological-sample-A"],
        "columns": [{"name": "value", "samples": ["raw-statistical-example"], "null_count": 0}]}}}
    view = observation_views([observation], include_previews=False)[0]
    assert "raw-statistical-example" not in json.dumps(view)
    assert view["payload"]["facts"]["samples"] == ["biological-sample-A"]
    assert "samples" not in view["payload"]["facts"]["columns"][0]


def test_provenance_column_statistics_do_not_displace_executable_source_metadata():
    observations = [{"call_id": "summary", "payload": {"relative_path": "summary.tsv", "facts": {
        "column_count": 2, "row_count": 100, "columns": [{"name": "name", "null_count": 0}, {"name": "value", "null_count": 1}]}}}]
    views = observation_views(observations, include_previews=False, executed_source_paths={"identifications.tsv"})
    assert [field["name"] for field in views[0]["source_schema"]["physical_fields"]] == ["name", "value"]
    assert views[0]["payload"]["facts"]["row_count"] == 100
    assert "columns" not in views[0]["payload"]["facts"]
    assert len(observations[0]["payload"]["facts"]["columns"]) == 2


def test_runtime_capabilities_are_referenced_not_duplicated_in_research_payload():
    source = {"call_id": "capabilities", "tool_name": "inspect_viewer_capabilities", "result_sha256": "a" * 64,
              "payload": {"large_capability_schema": "x" * 20000}}
    view = observation_views([source], include_previews=False)[0]
    assert view["call_id"] == "capabilities" and view["result_sha256"] == "a" * 64
    assert "zp_capabilities" in view["payload"]["capability_reference"]
    assert "large_capability_schema" not in view["payload"]


def test_parquet_preview_reads_ten_but_metadata_reports_full_scope(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    path = tmp_path / "data.parquet"
    pq.write_table(pa.table({"id": list(range(30)), "value": [None, 0] * 15}), path)
    result = preview_file(path)
    assert result["total_rows"] == 30
    assert len(result["records"]) == 10
    assert result["records"][0]["value"] is None
    assert result["records"][1]["value"] == 0


def test_full_converter_and_real_zp_keep_records_beyond_preview(tmp_path):
    from test_declarative_ingest_contract import _payload
    from app.declarative_ingest import DeclarativeImportPlan, build_declarative_zp_artifact, read_semantic_zp
    source = tmp_path / "renamed-results.tsv"
    source.write_text("record\tsample\tpeptide\trt\tprotein\tscore\tunused\n" + "".join(
        f"p{i}\trun-{i % 2}\tPEPTIDE\t1.5\tP42\t0\tkeep-{i}\n" for i in range(17)), encoding="utf-8")
    assert len(preview_file(source)["records"]) == 10
    artifact = build_declarative_zp_artifact(source_root=tmp_path, source_fingerprint="0" * 32,
        plan=DeclarativeImportPlan.model_validate(_payload()), output_path=tmp_path / "full.zp")
    readback = read_semantic_zp(artifact.path)
    assert len(readback.identifications) == 17
    assert len(readback.runs) == 2
    assert all(x.rt_seconds == 90 for x in readback.identifications)
    assert any(x.source_record_id == "p16" for x in readback.identifications)
    assert "keep-16" in readback.model_dump_json()


def test_xlsx_sheet_selection_and_unknown_formula_cache(tmp_path):
    path = tmp_path / "book.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", '<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="First" r:id="r1"/><sheet name="Second" r:id="r2"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="worksheets/sheet2.xml"/></Relationships>')
        rows = '<row><c r="A1" t="inlineStr"><is><t>value</t></is></c></row>'
        rows += ''.join(f'<row><c r="A{i}"><f>1+1</f><v>2</v></c></row>' for i in range(2, 20))
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet><sheetData>{rows}</sheetData><mergeCells><mergeCell ref="A1:B1"/></mergeCells></worksheet>')
    assert preview_file(path)["status"] == "SELECT_SHEET"
    result = preview_file(path, sheet="First")
    assert result["merged_cells_present"]
    assert len(result["records"]) == 10
    assert result["records"][0]["A"]["cache_validity"] == "unknown"
    assert result["conversion_supported"] is False
    assert result["budget"]["elapsed_seconds"] < 5


def test_xlsx_real_hung_child_is_terminated_at_wall_deadline(tmp_path, monkeypatch):
    import subprocess
    import sys
    import time
    from app.source_inspection import preview_process
    real_popen = subprocess.Popen
    children = []
    def hanging_parser(_command, **kwargs):
        child = real_popen([sys.executable, "-c", "import time;time.sleep(30)"], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(preview_process.subprocess, "Popen", hanging_parser)
    started = time.monotonic()
    result = preview_process.preview_xlsx(tmp_path / "synthetic.xlsx", {"records": []}, None, 0, 0, 0, 32, seconds=0.25)
    assert result["status"] == "PARTIAL" and result["records"] == []
    assert time.monotonic() - started < 3
    assert children[0].poll() is not None
