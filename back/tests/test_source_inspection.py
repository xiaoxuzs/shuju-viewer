from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.source_inspection import (
    InspectionLimits,
    InspectorRegistry,
    InventoryService,
    SourcePathError,
    StaleInventoryCursor,
    inspect_file,
    sniff_file,
)


def test_inventory_pages_real_total_and_does_not_follow_links(tmp_path: Path) -> None:
    (tmp_path / "z.txt").write_text("z", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "c.txt").write_text("c", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link_created = False
    try:
        (tmp_path / "outside-link.txt").symlink_to(outside)
        link_created = True
    except OSError:
        pass

    inventory = InventoryService(tmp_path)
    first = inventory.list_files(limit=2)
    second = inventory.list_files(limit=2, cursor=first.next_cursor)

    assert first.total_count == 3
    assert second.total_count == 3
    assert [item.relative_path for item in first.items + second.items] == [
        "a.txt",
        "nested/c.txt",
        "z.txt",
    ]
    assert second.next_cursor is None
    assert first.skipped_link_count == int(link_created)


def test_inventory_cursor_is_rejected_after_tree_changes(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    inventory = InventoryService(tmp_path)
    first = inventory.list_files(limit=1)
    assert first.next_cursor is not None
    (tmp_path / "c.txt").write_text("c", encoding="utf-8")

    with pytest.raises(StaleInventoryCursor):
        inventory.list_files(limit=1, cursor=first.next_cursor)


@pytest.mark.parametrize("relative_path", ["../outside.txt", "/outside.txt", "C:/outside.txt"])
def test_inspection_rejects_paths_outside_case_root(tmp_path: Path, relative_path: str) -> None:
    with pytest.raises(SourcePathError):
        inspect_file(tmp_path, relative_path)


def test_sniff_is_bounded_and_records_scoped_hashes(tmp_path: Path) -> None:
    path = tmp_path / "large.csv"
    path.write_text("id,value\n" + "1,alpha\n" * 200, encoding="utf-8")

    observation = sniff_file(
        tmp_path,
        "large.csv",
        limits=InspectionLimits(max_bytes_read=128, sniff_bytes=128),
    )

    assert observation.status == "COMPLETE"
    assert observation.detected_format == "csv"
    assert observation.budget.bytes_read <= 128
    assert observation.truncation.reasons == ["content_sampled_by_design"]
    assert observation.hashes.source_content_sha256 is None
    assert len(observation.hashes.inspection_sample_sha256) == 64
    assert len(observation.hashes.observation_sha256) == 64


def test_csv_schema_nulls_types_and_row_budget_are_streamed(tmp_path: Path) -> None:
    (tmp_path / "table.csv").write_text(
        "id,value,note\n1,1.5,alpha\n2,,beta\n3,4.0,gamma\n",
        encoding="utf-8",
    )
    limits = InspectionLimits(max_bytes_read=4_096, sniff_bytes=64, max_rows=2)

    observation = inspect_file(tmp_path, "table.csv", limits=limits)

    assert observation.status == "PARTIAL"
    assert observation.facts["rows_observed"] == 2
    assert observation.facts["row_count"] is None
    assert observation.facts["row_count_exact"] is False
    columns = {item["name"]: item for item in observation.facts["columns"]}
    assert columns["id"]["inferred_type"] == "integer"
    assert columns["value"]["inferred_type"] == "float"
    assert columns["value"]["null_count"] == 1
    assert "rows" in observation.budget.exhausted


def test_jsonl_is_streamed_without_retaining_all_rows_or_distinct_values(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text(
        "\n".join(f'{{"id":{index},"value":"sample-{index}"}}' for index in range(20)) + "\n",
        encoding="utf-8",
    )
    limits = InspectionLimits(
        max_bytes_read=16_384,
        sniff_bytes=64,
        max_rows=3,
        max_sample_values=2,
    )

    observation = inspect_file(tmp_path, "records.jsonl", limits=limits)

    assert observation.status == "PARTIAL"
    assert observation.facts["rows_observed"] == 3
    value = next(item for item in observation.facts["fields"] if item["name"] == "value")
    assert len(value["samples"]) == 2
    assert observation.facts["raw_rows_returned"] is False


def test_unknown_extensions_can_be_sniffed_as_generic_tabular_or_jsonl(tmp_path: Path) -> None:
    (tmp_path / "evidence.dat").write_text("id\tscore\n1\t0.5\n", encoding="utf-8")
    (tmp_path / "events.log").write_text('{"id":1}\n{"id":2}\n', encoding="utf-8")

    table = inspect_file(tmp_path, "evidence.dat")
    records = inspect_file(tmp_path, "events.log")

    assert table.status == "COMPLETE"
    assert table.detected_format == "tsv"
    assert table.facts["row_count"] == 1
    assert records.status == "COMPLETE"
    assert records.detected_format == "jsonl"
    assert records.facts["row_count"] == 2


def test_unknown_binary_returns_unsupported_observation(tmp_path: Path) -> None:
    (tmp_path / "opaque.bin").write_bytes(b"\x00\x01\x02closed-format\x00")

    observation = InspectorRegistry.default().inspect(tmp_path, "opaque.bin")

    assert observation.status == "UNSUPPORTED"
    assert observation.detected_format == "binary"
    assert observation.facts["file_content_returned"] is False
    assert observation.warnings


def test_json_returns_bounded_structure_not_raw_document(tmp_path: Path) -> None:
    (tmp_path / "metadata.json").write_text(
        '{"instrument":{"name":"Orbitrap","path":"C:/private/source.raw"},"runs":[1,2,3]}',
        encoding="utf-8",
    )

    observation = inspect_file(tmp_path, "metadata.json")

    assert observation.status == "COMPLETE"
    assert observation.facts["parsed"] is True
    assert observation.facts["raw_value_returned"] is False
    assert observation.facts["structure"]["type"] == "object"
    assert observation.hashes.source_content_sha256 is not None


def test_json_over_byte_budget_does_not_claim_a_successful_parse(tmp_path: Path) -> None:
    (tmp_path / "large.json").write_text('{"values":[' + ",".join("1" for _ in range(500)) + "]}", encoding="utf-8")
    limits = InspectionLimits(max_bytes_read=128, sniff_bytes=64)

    observation = inspect_file(tmp_path, "large.json", limits=limits)

    assert observation.status == "PARTIAL"
    assert observation.facts["parsed"] is False
    assert observation.facts["raw_value_returned"] is False
    assert observation.facts["root_type_hint"] == "object"


def test_xml_structure_is_bounded_and_rejects_dtd(tmp_path: Path) -> None:
    (tmp_path / "params.xml").write_text(
        "<Params><Mode>DDA</Mode><Nested><Mode>HCD</Mode></Nested></Params>",
        encoding="utf-8",
    )
    (tmp_path / "unsafe.xml").write_text(
        '<!DOCTYPE root [<!ENTITY x "unsafe">]><root>&x;</root>',
        encoding="utf-8",
    )

    valid = inspect_file(tmp_path, "params.xml")
    invalid = inspect_file(tmp_path, "unsafe.xml")

    assert valid.status == "COMPLETE"
    assert valid.facts["root_element"] == "Params"
    assert valid.facts["tag_counts"]["Mode"] == 2
    assert valid.facts["raw_document_returned"] is False
    assert invalid.status == "INVALID"
    assert "DTD" in invalid.warnings[0]


def test_mzml_inspection_uses_declared_metadata_without_peak_arrays(tmp_path: Path) -> None:
    (tmp_path / "run.mzML").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<mzML xmlns="http://psi.hupo.org/ms/mzml">
  <run><spectrumList count="2">
    <spectrum id="controllerType=0 controllerNumber=1 scan=7" defaultArrayLength="3">
      <cvParam accession="MS:1000511" name="ms level" value="1"/>
      <cvParam accession="MS:1000016" name="scan start time" value="2" unitAccession="UO:0000031" unitName="minute"/>
      <binaryDataArrayList><binaryDataArray><binary>AAAA</binary></binaryDataArray></binaryDataArrayList>
    </spectrum>
    <spectrum id="scan=8" defaultArrayLength="2">
      <cvParam accession="MS:1000511" name="ms level" value="2"/>
      <cvParam accession="MS:1000127" name="centroid spectrum" value=""/>
      <cvParam accession="MS:1000016" name="scan start time" value="3" unitAccession="UO:0000032" unitName="hour"/>
    </spectrum>
  </spectrumList></run>
</mzML>""",
        encoding="utf-8",
    )

    observation = inspect_file(tmp_path, "run.mzML")

    assert observation.status == "COMPLETE"
    assert observation.facts["spectrum_count"] == 2
    assert observation.facts["ms_level_counts_observed"] == {"1": 1, "2": 1}
    assert observation.facts["declared_peak_pair_counts_observed"]["total"] == 5
    assert observation.facts["retention_time_seconds_observed"] == [120.0, 120.0]
    assert observation.facts["unresolved_retention_time_units"] == {"UO:0000032": 1}
    assert observation.facts["peak_arrays_returned"] is False
    assert observation.facts["binary_values_decoded"] is False
    assert "AAAA" not in str(observation.facts)


def test_fasta_inspection_never_returns_sequences(tmp_path: Path) -> None:
    (tmp_path / "db.fasta").write_text(
        ">sp|P1|ONE Protein one\nPEPTIDE\n>P2 Protein two\nAAAA\n>P3 Duplicate\nAAAA\n",
        encoding="utf-8",
    )

    observation = inspect_file(tmp_path, "db.fasta")

    assert observation.status == "COMPLETE"
    assert observation.facts["record_count"] == 3
    assert observation.facts["unique_sequence_count"] == 2
    assert observation.facts["duplicate_sequence_count"] == 1
    assert observation.facts["sequences_returned"] is False
    assert "PEPTIDE" not in str(observation.facts)


def test_parquet_reads_only_metadata_and_schema(tmp_path: Path) -> None:
    path = tmp_path / "report.parquet"
    pq.write_table(pa.table({"id": [1, 2], "score": [0.1, None]}), path)

    observation = inspect_file(tmp_path, "report.parquet")

    assert observation.status == "COMPLETE"
    assert observation.facts["row_count"] == 2
    assert observation.facts["column_count"] == 2
    assert [field["name"] for field in observation.facts["fields"]] == ["id", "score"]
    assert observation.facts["data_pages_read"] is False
