from copy import deepcopy
import json

import pytest

from app.agent_import.verification_full import (
    FullAcceptanceContract, TableExpectation, ReconciliationLedger, FullVerificationError,
    expected_record, populate_source, reconcile_semantic, semantic_records, unequal,
)
from app.agent_import.input_assets import content_manifest


def fixture(tmp_path, count=237, batch_size=37, *, rows=None):
    root = tmp_path / "input"
    root.mkdir()
    rows = rows if rows is not None else [dict(id=str(i), run="one", sequence="PEPTIDE", value=None if i == 101 else float(i), rt=float(i), protein="A;B") for i in range(count)]
    (root / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    table = TableExpectation(relative_path="rows.jsonl", reader="jsonl", id_column="id", run_column="run", sequence_column="sequence",
        quantity_column="value", quantity_unit="intensity", proteins_column="protein", rt_column="rt", rt_unit="minute", semantics_evidence="Independent fixture: RT is minutes, quantity is identification intensity.")
    contract = FullAcceptanceContract(source_identity=content_manifest(root)["sha256"], source_evidence="Independent test source specification",
        scope="every fixture record", table=table, source_roles={"rows.jsonl": "identifications"}, batch_size=batch_size)
    ledger = ReconciliationLedger(tmp_path / "ledger.sqlite", contract)
    populate_source(ledger, root)
    return ledger, [expected_record(r, i, table) for i, r in enumerate(rows, 1)], root


def test_full_scan_multiple_batches_and_non_multiple_tail(tmp_path):
    ledger, records, _ = fixture(tmp_path)
    try:
        for record in reversed(records):
            ledger.compare("zp", record)
        report = ledger.finish("zp")
        assert report["expected"] == report["observed_unique"] == 237
        assert report["coverage"] == "all_declared_records"
    finally:
        ledger.close()


@pytest.mark.parametrize("index", [100, 36, 37, 236])
@pytest.mark.parametrize("mutation", ["field", "null_zero", "unit", "relation", "same_count_replacement"])
def test_late_and_boundary_corruption_fails_despite_unchanged_aggregates(tmp_path, index, mutation):
    ledger, records, _ = fixture(tmp_path)
    try:
        if mutation == "field":
            records[index]["sequence"] = "CHANGED"
        elif mutation == "null_zero":
            records[index]["quantification"][0]["value"] = None
        elif mutation == "unit":
            records[index]["rt_seconds"] /= 60
        elif mutation == "relation":
            records[index]["proteins"] = ["B", "C"]
        else:
            records[index] = deepcopy(records[0])
        for record in records:
            ledger.compare("zp", record)
        with pytest.raises(FullVerificationError) as failure:
            ledger.finish("zp")
        assert failure.value.report["errors"] or failure.value.report["missing"]
        assert len(failure.value.report["diagnostic_samples"]) <= 10
    finally:
        ledger.close()


def test_value_swap_with_equal_sum_is_not_a_valid_reconciliation(tmp_path):
    ledger, records, _ = fixture(tmp_path)
    records[100]["quantification"], records[-1]["quantification"] = records[-1]["quantification"], records[100]["quantification"]
    try:
        for record in records:
            ledger.compare("projection", record)
        with pytest.raises(FullVerificationError):
            ledger.finish("projection")
    finally:
        ledger.close()


@pytest.mark.parametrize("limit", [0, 10, 100, 236])
def test_partial_parser_zp_projection_or_api_never_passes(tmp_path, limit):
    ledger, records, _ = fixture(tmp_path)
    try:
        for stage in ("parse", "zp", "projection", "http"):
            for record in records[:limit]:
                ledger.compare(stage, record)
            with pytest.raises(FullVerificationError):
                ledger.finish(stage)
    finally:
        ledger.close()


def test_cross_run_same_local_id_is_distinct_and_cross_batch_duplicate_is_rejected(tmp_path):
    rows = [dict(id="same", run=r, sequence="PEPTIDE", rt=1, value=0, protein="A") for r in ("r1", "r2")]
    ledger, records, _ = fixture(tmp_path, rows=rows, batch_size=1)
    try:
        for record in records:
            ledger.compare("zp", record)
        assert ledger.finish("zp")["expected"] == 2
    finally:
        ledger.close()
    duplicate_root = tmp_path / "duplicate"
    duplicate_root.mkdir()
    with pytest.raises(FullVerificationError, match="DUPLICATE_SOURCE_IDENTITY"):
        fixture(duplicate_root, rows=[*rows, rows[0]], batch_size=1)


def test_bad_type_after_first_ten_and_empty_input_never_pass(tmp_path):
    rows = [dict(id=str(i), run="one", sequence="PEPTIDE", rt=1, value=0, protein="A") for i in range(102)]
    rows[101]["value"] = "not a numeric value"
    with pytest.raises(FullVerificationError, match="SOURCE_NUMERIC_TYPE_INVALID"):
        fixture(tmp_path, rows=rows)


def test_snapshot_change_and_cancellation_invalidate_scan(tmp_path, monkeypatch):
    from app.agent_import import verification_full as module
    root = tmp_path / "input"
    root.mkdir()
    (root / "rows.jsonl").write_text('{"id":"1","run":"r","sequence":"P"}')
    contract = FullAcceptanceContract(source_identity=content_manifest(root)["sha256"], source_evidence="Independent input contract", scope="all source rows",
        table=TableExpectation(relative_path="rows.jsonl", reader="jsonl", id_column="id", run_column="run", sequence_column="sequence", semantics_evidence="Explicit fixture contract"),
        source_roles={"rows.jsonl": "identifications"})
    ledger = ReconciliationLedger(tmp_path / "changed.sqlite", contract)
    original = module.source_records
    def changed(*args):
        yield from original(*args)
        (root / "rows.jsonl").write_text("changed")
    monkeypatch.setattr(module, "source_records", changed)
    try:
        with pytest.raises(FullVerificationError, match="SOURCE_CHANGED_DURING_SCAN"):
            populate_source(ledger, root)
        with pytest.raises(FullVerificationError, match="SOURCE_SCAN_INCOMPLETE"):
            ledger.finish("zp")
        monkeypatch.setattr(module, "checkpoint", lambda: (_ for _ in ()).throw(RuntimeError("cancelled")))
        with pytest.raises(RuntimeError, match="cancelled"):
            ledger.finish("zp")
    finally:
        ledger.close()


def test_small_oracle_and_full_checker_overlap_on_same_semantic_fields(tmp_path):
    from app.agent_import.verification import AcceptanceContract, MatchExpectation
    ledger, records, _ = fixture(tmp_path, count=7)
    small = AcceptanceContract(source_identity=ledger.contract.source_identity, source_evidence="Independent overlapping fixture", total_matches=7, scope="all seven rows",
        matches=[MatchExpectation(source_record_id=str(i), sequence="PEPTIDE", rt_minutes=float(i), quantification_values=[float(i)], quantification_units=["intensity"]) for i in range(7)])
    try:
        for expected, actual in zip(small.matches, records):
            assert expected.sequence == actual["sequence"]
            assert expected.rt_minutes * 60 == actual["rt_seconds"]
            assert expected.quantification_values == [q["value"] for q in actual["quantification"]]
            assert expected.quantification_units == [q["unit"] for q in actual["quantification"]]
            assert expected.q_value is actual["q_value"] is None
            assert expected.decoy is actual["decoy"] is None
            ledger.compare("semantic", actual)
        assert ledger.finish("semantic")["expected"] == small.total_matches
    finally:
        ledger.close()


def test_real_zp_full_records_and_foreign_key_mutation(tmp_path):
    from app.declarative_ingest import DeclarativeImportPlan, build_declarative_zp_artifact, read_semantic_zp
    rows = [dict(id=str(i // 2), run="run-a" if i % 2 == 0 else "run-b", sequence="PEPTIDE", rt=1.5, value=None if i == 101 else float(i), protein="A;B") for i in range(237)]
    ledger, _, root = fixture(tmp_path, rows=rows)
    pairs = [("id", "identification", "source_id", "string", "identity", None), ("run", "run", "name", "string", "identity", None),
             ("sequence", "peptide", "sequence", "string", "identity", None), ("rt", "identification", "rt_seconds", "float", "minute_to_second", "minute"),
             ("value", "quantification", "value", "float", "identity", "intensity"), ("protein", "identification", "protein_accessions", "string", "semicolon_split", None)]
    plan = DeclarativeImportPlan.model_validate({"schema_version": 1, "plan_id": "full-zp-overlap", "analysis_mode": "BOTTOM_UP",
        "sources": [{"source_id": "rows", "relative_path": "rows.jsonl", "reader": "jsonl", "role": "identification_table"}],
        "field_mappings": [{"mapping_id": f"m{i}", "source_id": "rows", "source_field": field, "target_entity": entity, "target_field": target,
            "value_kind": kind, "transform": transform, "unit": unit, "evidence_refs": ["independent-fixture"]} for i, (field, entity, target, kind, transform, unit) in enumerate(pairs)],
        "unmapped_fields": {"rows": []}})
    try:
        artifact = build_declarative_zp_artifact(source_root=root, source_fingerprint="a" * 32, plan=plan, output_path=tmp_path / "whole.zp")
        dataset = read_semantic_zp(artifact.path)
        assert dataset.schema_version == 2 and len(dataset.runs) == 2
        assert reconcile_semantic(ledger, dataset)["expected"] == 237
        broken = dataset.model_copy(deep=True)
        broken.identifications[-1].peptide_id = "missing-peptide"
        with pytest.raises(FullVerificationError, match="FOREIGN_KEY"):
            list(semantic_records(broken))
    finally:
        ledger.close()


def test_semantic_v1_is_still_readable_and_v2_cannot_masquerade_as_v1():
    from app.declarative_ingest.semantic_schema import SemanticDataset, parse_semantic_extension_payload, semantic_extension_payload
    legacy = {"owner": "viewer", "schema_name": "viewer_semantic_dataset", "schema_version": 1, "record_count": 1,
              "dataset": {"schema_version": 1, "plan_id": "legacy", "plan_sha256": "a" * 64, "source_fingerprint": "b" * 32, "source_files": []}}
    parsed = parse_semantic_extension_payload(legacy)
    assert parsed.schema_version == 1
    assert semantic_extension_payload(parsed)["schema_version"] == 1
    bad = deepcopy(legacy)
    bad["dataset"]["schema_version"] = 2
    with pytest.raises(ValueError, match="versions differ"):
        parse_semantic_extension_payload(bad)


@pytest.mark.parametrize("mutation", [None, "truncated", "duplicate", "late_field", "association_order", "association_duplicate"])
def test_http_full_pagination_boundary_and_late_errors(tmp_path, mutation):
    from app.agent_import.verification_http_full import reconcile_http, API_FIELDS
    from app.agent_import.verification_full import record_key, encoded
    from urllib.parse import urlsplit, parse_qs
    ledger, records, _ = fixture(tmp_path)
    items = []
    for i, record in enumerate(records, 1):
        api = {k: None for k in API_FIELDS}
        api.update(source_record_id=record["source_id"], source_run_name=record["run"], sequence=record["sequence"])
        api["protein_accessions"] = ["A", "B"]
        ledger.db.execute("INSERT INTO projection_ids VALUES(?,?,?)", (i, record_key(record), encoded(api)))
        items.append({"id": i, **api})
    if mutation == "late_field":
        items[100]["sequence"] = "WRONG"
    elif mutation == "duplicate":
        items[101] = deepcopy(items[100])
    elif mutation == "association_order":
        items[101]["protein_accessions"] = ["B", "A"]
    elif mutation == "association_duplicate":
        items[101]["protein_accessions"] = ["A", "A"]
    def get(url):
        page = int(parse_qs(urlsplit(url).query)["page"][0])
        part = items[(page - 1) * 37:page * 37]
        if mutation == "truncated" and page >= 4:
            part = []
        return {"page": page, "page_size": 37, "total": 237, "items": part}
    try:
        if mutation and mutation != "association_order":
            with pytest.raises(FullVerificationError):
                reconcile_http(ledger, get, "http://unused", page_size=37)
        else:
            assert reconcile_http(ledger, get, "http://unused", page_size=37)["observed_unique"] == 237
    finally:
        ledger.close()
