"""Trusted v2 full-scope reconciliation. Not writable/callable as an Agent tool.

SQLite bounds reconciliation memory, not the current materialized semantic ZP
Reader or converter. Expected values are read independently of those components.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
from typing import Literal

import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent_import.execution_control import checkpoint
from app.agent_import.input_assets import content_manifest
from app.source_inspection.paths import CasePathResolver

VERIFIER_VERSION = "full-semantic-v2.0"
EXTENDED_VERIFIER_VERSION = "full-semantic-v2.1"


class TableExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relative_path: str
    reader: Literal["parquet", "jsonl", "delimited"]
    delimiter: str = "\t"
    identity: Literal["mapped", "source_row"] = "mapped"
    id_column: str | None = None
    run_column: str
    sequence_column: str
    modified_column: str | None = None
    rt_column: str | None = None
    rt_unit: Literal["minute", "second"] | None = None
    q_column: str | None = None
    score_column: str | None = None
    charge_column: str | None = None
    mz_column: str | None = None
    decoy_column: str | None = None
    proteins_column: str | None = None
    group_column: str | None = None
    group_members_column: str | None = None
    quantity_column: str | None = None
    quantity_unit: str | None = None
    quantity_sample_column: str | None = None
    pep_column: str | None = None
    neutral_mass_column: str | None = None
    scan_column: str | None = None
    decoy_encoding: Literal["boolean", "plus_marker"] = "boolean"
    external_groups: bool = False
    semantics_evidence: str = Field(min_length=10)

    @model_validator(mode="after")
    def complete_binding(self):
        if self.identity == "mapped" and self.id_column is None:
            raise ValueError("Mapped identity needs an independent source column")
        if self.rt_column is not None and self.rt_unit is None:
            raise ValueError("Source RT requires an established unit")
        if self.group_column is not None and self.group_members_column is None and not self.external_groups:
            raise ValueError("Group identity requires an explicit membership contract")
        return self


class GroupExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relative_path: str
    reader: Literal["delimited", "jsonl", "parquet"] = "delimited"
    delimiter: str = "\t"
    id_column: str
    members_column: str
    q_column: str | None = None
    pep_column: str | None = None
    semantics_evidence: str = Field(min_length=10)


class FastaExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relative_path: str
    accession_rule: Literal["first_token", "uniprot_pipe_accession"]
    semantics_evidence: str = Field(min_length=10)


class FullAcceptanceContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[2, 3] = 2
    verifier_version: Literal["full-semantic-v2.0", "full-semantic-v2.1"] = VERIFIER_VERSION
    source_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evidence: str = Field(min_length=10)
    requirements_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    scope: str = Field(min_length=5)
    table: TableExpectation
    source_roles: dict[str, Literal["identifications", "spectra", "provenance", "protein_groups", "reference_sequences"]]
    groups: GroupExpectation | None = None
    fasta: FastaExpectation | None = None
    acquisition_mode: Literal["dia", "dda"] = "dia"
    batch_size: int = Field(default=1024, ge=1, le=8192)
    max_seconds: int = Field(default=1800, ge=1, le=14400)
    max_ledger_bytes: int = Field(default=2_147_483_648, ge=1)
    numeric_absolute_tolerance: float = Field(default=0, ge=0, le=1e-5)
    numeric_relative_tolerance: float = Field(default=0, ge=0, le=1e-6)
    required_views: dict[str, Literal["AVAILABLE", "PARTIAL"]] = Field(default_factory=lambda: {"bu.matches": "AVAILABLE", "bu.peptides": "AVAILABLE"})

    @model_validator(mode="after")
    def role_scope(self):
        if self.source_roles.get(self.table.relative_path) != "identifications" or list(self.source_roles.values()).count("identifications") != 1:
            raise ValueError("v2 validates one complete identification table, not a first-N slice")
        extended = (self.groups or self.fasta or self.acquisition_mode != "dia" or self.table.external_groups
                    or self.table.pep_column or self.table.neutral_mass_column or self.table.scan_column
                    or self.table.quantity_sample_column or self.table.decoy_encoding != "boolean")
        if extended and (self.schema_version != 3 or self.verifier_version != EXTENDED_VERIFIER_VERSION):
            raise ValueError("Extended multi-table/DDA facts require the version 3 / v2.1 acceptance contract")
        if self.table.external_groups and (not self.groups or not self.table.group_column):
            raise ValueError("External group references require a declared group table and identity field")
        for specification, role in ((self.groups, "protein_groups"), (self.fasta, "reference_sequences")):
            declared = [p for p, value in self.source_roles.items() if value == role]
            if declared != ([] if specification is None else [specification.relative_path]):
                raise ValueError("Extended source roles must exactly match their independent contracts")
        return self


class FullVerificationError(ValueError):
    def __init__(self, code, report=None):
        self.code, self.report = code, report or {}
        super().__init__(code)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _text(value, *, required=False):
    if value is None or isinstance(value, str) and not value.strip():
        if required:
            raise FullVerificationError("SOURCE_REQUIRED_VALUE_MISSING")
        return None
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise FullVerificationError("SOURCE_TEXT_TYPE_INVALID")
    return str(value).strip()


def _number(value, *, integer=False):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise FullVerificationError("SOURCE_NUMERIC_TYPE_INVALID")
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise FullVerificationError("SOURCE_NUMERIC_TYPE_INVALID") from None
    if not math.isfinite(number) or integer and number != int(number):
        raise FullVerificationError("SOURCE_NUMERIC_TYPE_INVALID")
    return int(number) if integer else number


def _bool(value):
    if value is None or value == "":
        return None
    if value in (True, 1, "1", "true"):
        return True
    if value in (False, 0, "0", "false"):
        return False
    raise FullVerificationError("SOURCE_BOOLEAN_TYPE_INVALID")


def _members(value):
    return sorted(set(filter(None, (v.strip() for v in (_text(value) or "").split(";")))))


def source_records(path, table, batch_size):
    if table.reader == "parquet":
        for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_size):
            checkpoint()
            yield from batch.to_pylist()
    elif table.reader == "jsonl":
        with path.open(encoding="utf-8-sig") as stream:
            for line in stream:
                if line.strip():
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise FullVerificationError("SOURCE_RECORD_NOT_OBJECT")
                    yield value
    else:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, delimiter=table.delimiter)
            if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise FullVerificationError("SOURCE_HEADER_INVALID")
            for row in reader:
                if None in row or any(v is None for v in row.values()):
                    raise FullVerificationError("SOURCE_RECORD_WIDTH_INVALID")
                yield row


def expected_record(row, number, table):
    bindings = [v for k, v in table.model_dump().items() if k.endswith("_column") and v is not None]
    if set(bindings) - set(row):
        raise FullVerificationError("SOURCE_CONTRACT_FIELD_MISSING")
    def get(name):
        column = getattr(table, name + "_column")
        return row[column] if column else None
    rt = _number(get("rt"))
    if rt is not None and table.rt_unit == "minute":
        rt *= 60
    quant = [] if not table.quantity_column else [{"value": _number(get("quantity")), "unit": table.quantity_unit,
        "metric": table.quantity_column, "channel": None, "sample": _text(get("quantity_sample")), "normalization_kind": None}]
    group = _text(get("group"))
    record = {"run": _text(get("run"), required=True), "source_id": str(number) if table.identity == "source_row" else _text(get("id"), required=True),
            "sequence": _text(get("sequence"), required=True), "modified_sequence": _text(get("modified")),
            "rt_seconds": rt, "q_value": _number(get("q")), "score": _number(get("score")),
            "charge": _number(get("charge"), integer=True), "precursor_mz": _number(get("mz")),
            "decoy": (None if not get("decoy") else get("decoy") == "+") if table.decoy_encoding == "plus_marker" else _bool(get("decoy")),
            "proteins": _members(get("proteins")), "groups": {group: _members(get("group_members"))} if group else {},
            "quantification": quant, "source_fields": row, "source_relative_path": table.relative_path, "source_row_number": number}
    for name in ("pep", "neutral_mass", "scan"):
        if getattr(table, name + "_column"):
            record[name] = _number(get(name), integer=name == "scan")
    return record


def record_key(record):
    return encoded([record["run"], record["source_id"]])


def unequal(expected, actual, *, absolute, relative, path=""):
    if type(expected) is bool or expected is None:
        return [] if type(actual) is type(expected) and actual == expected else [path]
    if isinstance(expected, (float, int)):
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual):
            return [path]
        strict = path != "rt_seconds" or isinstance(expected, int)
        return [] if (expected == actual if strict else math.isclose(expected, actual, abs_tol=absolute, rel_tol=relative)) else [path]
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [path]
        differences = [path + ".keys"] if set(expected) != set(actual) else []
        for key in expected.keys() & actual.keys():
            differences.extend(unequal(expected[key], actual[key], absolute=absolute, relative=relative, path=(path + "." + key).strip(".")))
        return differences
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return [path]
        return [p for i, (e, a) in enumerate(zip(expected, actual)) for p in unequal(e, a, absolute=absolute, relative=relative, path=path + f"[{i}]")]
    return [] if expected == actual else [path]


class ReconciliationLedger:
    def __init__(self, path: Path, contract: FullAcceptanceContract):
        if path.exists():
            raise FullVerificationError("LEDGER_ALREADY_EXISTS")
        self.path, self.contract = path, contract
        self.started = time.monotonic()
        self.db = sqlite3.connect(path)
        self.db.executescript("PRAGMA cache_size=-8192; PRAGMA temp_store=FILE; CREATE TABLE expected(k TEXT PRIMARY KEY, ordinal INTEGER UNIQUE, body TEXT NOT NULL); CREATE TABLE seen(stage TEXT,k TEXT, PRIMARY KEY(stage,k)); CREATE TABLE errors(stage TEXT,k TEXT,fields TEXT); CREATE TABLE refs(kind TEXT,left_key TEXT,right_key TEXT,PRIMARY KEY(kind,left_key,right_key)); CREATE TABLE projection_ids(id INTEGER PRIMARY KEY,k TEXT UNIQUE,body TEXT); CREATE TABLE state(name TEXT PRIMARY KEY,value TEXT);")
        self.complete = False
        self.progress = None
        self.processed = {}

    def check(self):
        checkpoint()
        if time.monotonic() - self.started > self.contract.max_seconds:
            raise FullVerificationError("FULL_SCAN_DEADLINE")
        if self.path.stat().st_size > self.contract.max_ledger_bytes:
            raise FullVerificationError("FULL_SCAN_DISK_BUDGET")

    def add_expected(self, record, ordinal):
        try:
            self.db.execute("INSERT INTO expected VALUES(?,?,?)", (record_key(record), ordinal, encoded(record)))
        except sqlite3.IntegrityError:
            raise FullVerificationError("DUPLICATE_SOURCE_IDENTITY") from None

    def seal_source(self):
        self.check()
        self.db.execute("INSERT INTO state VALUES('source_complete','true')")
        self.db.commit()
        self.complete = True

    def compare(self, stage, actual, *, fields=None):
        self.processed[stage] = self.processed.get(stage, 0) + 1
        if self.progress and self.processed[stage] % self.contract.batch_size == 0:
            self.progress(stage, self.processed[stage], self.db.execute("SELECT count(*) FROM expected").fetchone()[0])
        key = record_key(actual)
        try:
            self.db.execute("INSERT INTO seen VALUES(?,?)", (stage, key))
        except sqlite3.IntegrityError:
            self.db.execute("INSERT INTO errors VALUES(?,?,?)", (stage, key, '["duplicate_identity"]'))
            return
        row = self.db.execute("SELECT body FROM expected WHERE k=?", (key,)).fetchone()
        if row is None:
            differences = ["unexpected_identity"]
        else:
            expected = json.loads(row[0])
            if fields is not None:
                expected = {k: expected[k] for k in fields}
                actual = {k: actual.get(k) for k in fields}
            differences = unequal(expected, actual, absolute=self.contract.numeric_absolute_tolerance,
                                  relative=self.contract.numeric_relative_tolerance)
        if differences:
            self.db.execute("INSERT INTO errors VALUES(?,?,?)", (stage, key, encoded(differences)))

    def finish(self, stage):
        self.check()
        if not self.complete:
            raise FullVerificationError("SOURCE_SCAN_INCOMPLETE")
        self.db.commit()
        expected = self.db.execute("SELECT count(*) FROM expected").fetchone()[0]
        seen = self.db.execute("SELECT count(*) FROM seen WHERE stage=?", (stage,)).fetchone()[0]
        missing = self.db.execute("SELECT count(*) FROM expected e WHERE NOT EXISTS (SELECT 1 FROM seen s WHERE s.stage=? AND s.k=e.k)", (stage,)).fetchone()[0]
        errors = self.db.execute("SELECT count(*) FROM errors WHERE stage=?", (stage,)).fetchone()[0]
        report = {"verifier_version": self.contract.verifier_version, "stage": stage, "coverage": "all_declared_records", "expected": expected,
                  "observed_unique": seen, "missing": missing, "errors": errors,
                  "diagnostic_samples": [{"key_sha256": hashlib.sha256(k.encode()).hexdigest(), "fields": json.loads(fields)}
                     for k, fields in self.db.execute("SELECT k,fields FROM errors WHERE stage=? LIMIT 10", (stage,))]}
        if missing or errors or seen != expected or expected == 0:
            raise FullVerificationError("FULL_RECONCILIATION_FAILED", report)
        if self.progress:
            self.progress(stage, seen, expected)
        return report

    def close(self):
        self.db.close()


def populate_source(ledger, root):
    contract = ledger.contract
    before = content_manifest(root)
    stats = {p: ((root / p).stat().st_size, (root / p).stat().st_mtime_ns) for p in before["files"]}
    if before["sha256"] != contract.source_identity or set(before["files"]) != set(contract.source_roles):
        raise FullVerificationError("SOURCE_SCOPE_OR_IDENTITY_CHANGED")
    path = CasePathResolver(root).resolve_file(contract.table.relative_path)
    from .verification_tables import populate_supplements, bind_external_groups
    populate_supplements(ledger, root)
    for ordinal, row in enumerate(source_records(path, contract.table, contract.batch_size), 1):
        if (ordinal - 1) % contract.batch_size == 0:
            ledger.check()
            ledger.db.commit()
            if ledger.progress:
                ledger.progress("source", ordinal - 1, None)
        record = expected_record(row, ordinal, contract.table)
        bind_external_groups(ledger, row, record)
        ledger.add_expected(record, ordinal)
    if content_manifest(root) != before or stats != {p: ((root / p).stat().st_size, (root / p).stat().st_mtime_ns) for p in before["files"]}:
        raise FullVerificationError("SOURCE_CHANGED_DURING_SCAN")
    ledger.seal_source()
    return {"coverage": "all_files_and_all_table_records", "source_identity": before["sha256"],
            "files": len(before["files"]), "records": ledger.db.execute("SELECT count(*) FROM expected").fetchone()[0]}


def semantic_records(dataset, table=None):
    runs = {r.run_id: r.name for r in dataset.runs}
    peptides = {p.peptide_id: p.sequence for p in dataset.peptides}
    proteins = {p.protein_id: p for p in dataset.proteins}
    groups = {g.protein_group_id: g for g in dataset.protein_groups}
    quantities = {q.quantification_id: q for q in dataset.quantification}
    for item in dataset.identifications:
        try:
            quant = [quantities[q] for q in item.quantification_ids]
            if any(q.entity_kind != "identification" or q.entity_id != item.identification_id or q.run_id != item.run_id for q in quant):
                raise KeyError("wrong quantitative owner")
            memberships = {groups[g].source_group: sorted(proteins[p].accession for p in groups[g].member_protein_ids) for g in item.protein_group_ids}
            decoy = item.is_decoy
            if decoy is None:
                evidence = [proteins[p].is_decoy for p in item.protein_ids]
                decoy = all(evidence) if evidence and all(v is not None for v in evidence) else None
            record = {"run": runs[item.run_id], "source_id": item.source_record_id, "sequence": peptides[item.peptide_id],
                "modified_sequence": item.modified_sequence, "rt_seconds": item.rt_seconds, "q_value": item.q_value,
                "score": item.score, "charge": item.charge, "precursor_mz": item.precursor_mz, "decoy": decoy,
                "proteins": sorted(proteins[p].accession for p in item.protein_ids), "groups": memberships,
                "quantification": [{k: getattr(q, k) for k in ("value", "unit", "metric", "channel", "sample", "normalization_kind")} for q in quant],
                "source_fields": item.source_fields, "source_relative_path": item.source_relative_path, "source_row_number": item.source_row_number}
            for name, attribute in (("pep", "pep"), ("neutral_mass", "neutral_mass"), ("scan", "source_scan")):
                if table is not None and getattr(table, name + "_column"):
                    record[name] = getattr(item, attribute)
            yield record
        except KeyError:
            raise FullVerificationError("SEMANTIC_FOREIGN_KEY_OR_OWNER_INVALID") from None


def reconcile_semantic(ledger, dataset):
    if not ledger.contract.groups and any(g.q_value is not None or g.pep is not None or g.leading_protein_id is not None for g in dataset.protein_groups):
        raise FullVerificationError("UNDECLARED_GROUP_CONFIDENCE")
    if any(p.name is not None or p.gene is not None or p.description is not None or (p.sequence is not None and not ledger.contract.fasta) for p in dataset.proteins):
        raise FullVerificationError("UNDECLARED_PROTEIN_ANNOTATION")
    from .verification_tables import reconcile_supplements
    supplements = reconcile_supplements(ledger, dataset)
    for ordinal, record in enumerate(semantic_records(dataset, ledger.contract.table)):
        if ordinal % ledger.contract.batch_size == 0:
            ledger.check()
            ledger.db.commit()
        ledger.compare("semantic", record)
    report = ledger.finish("semantic")
    report["supplements"] = supplements
    # Validate both direction and membership of the entire relationship graph.
    for ident in dataset.identifications:
        pairs = [("identification_to_peptide", ident.peptide_id)]
        pairs += [("identification_to_protein", p) for p in ident.protein_ids]
        pairs += [("identification_to_protein_group", g) for g in ident.protein_group_ids]
        for kind, right in pairs:
            ledger.db.execute("INSERT INTO refs VALUES(?,?,?)", (kind, ident.identification_id, right))
    for relation in dataset.relationships:
        if relation.kind.startswith("identification_to_") and relation.kind != "identification_to_spectrum":
            if relation.state not in {"DIRECT", "DERIVED"}:
                raise FullVerificationError("SEMANTIC_RELATION_UNAVAILABLE")
            result = ledger.db.execute("DELETE FROM refs WHERE kind=? AND left_key=? AND right_key=?",
                                       (relation.kind, relation.left_id, relation.right_id))
            if result.rowcount != 1:
                raise FullVerificationError("SEMANTIC_RELATION_WRONG_OR_DUPLICATED")
    if ledger.db.execute("SELECT count(*) FROM refs").fetchone()[0]:
        raise FullVerificationError("SEMANTIC_RELATION_MISSING")
    ledger.db.execute("CREATE TABLE entities(kind TEXT,k TEXT,PRIMARY KEY(kind,k))")
    ledger.db.execute("CREATE TABLE source_edges(peptide TEXT,protein TEXT,PRIMARY KEY(peptide,protein))")
    for raw, in ledger.db.execute("SELECT body FROM expected"):
        expected = json.loads(raw)
        entries = [("run", expected["run"]), ("peptide", expected["sequence"])]
        entries += [("protein", p) for p in expected["proteins"]]
        ledger.db.executemany("INSERT OR IGNORE INTO source_edges VALUES(?,?)", [(expected["sequence"], p) for p in expected["proteins"]])
        for group, members in expected["groups"].items():
            entries.append(("group", group))
            entries += [("protein", p) for p in members]
        ledger.db.executemany("INSERT OR IGNORE INTO entities VALUES(?,?)", entries)
    for raw, in ledger.db.execute("SELECT body FROM expected_groups"):
        group = json.loads(raw)
        ledger.db.execute("INSERT OR IGNORE INTO entities VALUES('group',?)", (group["source_group"],))
        ledger.db.executemany("INSERT OR IGNORE INTO entities VALUES('protein',?)", [(p,) for p in group["members"]])
    ledger.db.execute("CREATE TABLE source_entities AS SELECT * FROM entities")
    ledger.db.execute("CREATE UNIQUE INDEX source_entities_keys ON source_entities(kind,k)")
    for kind, values in (("run", (r.name for r in dataset.runs)), ("peptide", (p.sequence for p in dataset.peptides)),
                         ("protein", (p.accession for p in dataset.proteins)), ("group", (g.source_group for g in dataset.protein_groups))):
        for value in values:
            if ledger.db.execute("DELETE FROM entities WHERE kind=? AND k=?", (kind, value)).rowcount != 1:
                raise FullVerificationError("SEMANTIC_EXTRA_OR_DUPLICATED_ENTITY")
    if ledger.db.execute("SELECT count(*) FROM entities").fetchone()[0]:
        raise FullVerificationError("SEMANTIC_ENTITY_MISSING")
    return report
