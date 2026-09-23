"""Independent complete group/FASTA expectations. Never consume a candidate plan."""
import json

from .verification_full import FullVerificationError, _text, _number, _members, encoded, source_records, unequal
from app.source_inspection.paths import CasePathResolver


def populate_supplements(ledger, root):
    ledger.db.executescript("CREATE TABLE expected_groups(k TEXT PRIMARY KEY,body TEXT); CREATE TABLE expected_sequences(k TEXT PRIMARY KEY,sequence TEXT,state TEXT);")
    contract = ledger.contract
    if contract.groups:
        spec = contract.groups
        for ordinal, row in enumerate(source_records(CasePathResolver(root).resolve_file(spec.relative_path), spec, contract.batch_size)):
            if ordinal % contract.batch_size == 0:
                ledger.check()
            required = [spec.id_column, spec.members_column, spec.q_column, spec.pep_column]
            if any(key is not None and key not in row for key in required):
                raise FullVerificationError("SOURCE_GROUP_FIELD_MISSING")
            identity = _text(row[spec.id_column], required=True)
            group = {"source_group": identity, "members": _members(row[spec.members_column]),
                "q_value": _number(row[spec.q_column]) if spec.q_column else None,
                "pep": _number(row[spec.pep_column]) if spec.pep_column else None,
                "leading": None, "source_fields": row}
            if not group["members"] or ledger.db.execute("SELECT 1 FROM expected_groups WHERE k=?", (identity,)).fetchone():
                raise FullVerificationError("SOURCE_GROUP_IDENTITY_INVALID")
            ledger.db.execute("INSERT INTO expected_groups VALUES(?,?)", (identity, encoded(group)))
    if contract.fasta:
        spec = contract.fasta
        from pyteomics import fasta
        with fasta.read(str(CasePathResolver(root).resolve_file(spec.relative_path))) as stream:
            for ordinal, record in enumerate(stream):
                if ordinal % contract.batch_size == 0:
                    ledger.check()
                accession = record.description.split()[0]
                aliases = {accession}
                pieces = accession.split("|")
                if spec.accession_rule == "uniprot_pipe_accession" and len(pieces) == 3 and pieces[0] in {"sp", "tr"}:
                    aliases.add(pieces[1])
                for alias in aliases:
                    previous = ledger.db.execute("SELECT sequence,state FROM expected_sequences WHERE k=?", (alias,)).fetchone()
                    sequence, state = record.sequence, "DIRECT"
                    if previous and (previous[1] == "AMBIGUOUS" or previous[0] != sequence):
                        sequence, state = None, "AMBIGUOUS"
                    ledger.db.execute("INSERT OR REPLACE INTO expected_sequences VALUES(?,?,?)", (alias, sequence, state))


def bind_external_groups(ledger, row, record):
    table = ledger.contract.table
    if not table.external_groups:
        return
    record["groups"] = {}
    for identity in _members(row[table.group_column]):
        raw = ledger.db.execute("SELECT body FROM expected_groups WHERE k=?", (identity,)).fetchone()
        if raw is None:
            raise FullVerificationError("SOURCE_GROUP_REFERENCE_MISSING")
        record["groups"][identity] = json.loads(raw[0])["members"]


def reconcile_supplements(ledger, dataset):
    proteins = {p.protein_id: p for p in dataset.proteins}
    seen = set()
    if ledger.contract.groups:
        for group in dataset.protein_groups:
            ledger.check()
            expected = ledger.db.execute("SELECT body FROM expected_groups WHERE k=?", (group.source_group,)).fetchone()
            if not expected or group.source_group in seen:
                raise FullVerificationError("SEMANTIC_GROUP_SCOPE_MISMATCH")
            seen.add(group.source_group)
            try:
                actual = {"source_group": group.source_group, "members": sorted(proteins[p].accession for p in group.member_protein_ids),
                    "q_value": group.q_value, "pep": group.pep,
                    "leading": proteins[group.leading_protein_id].accession if group.leading_protein_id else None,
                    "source_fields": group.source_fields}
            except KeyError:
                raise FullVerificationError("SEMANTIC_GROUP_MEMBER_MISSING") from None
            if unequal(json.loads(expected[0]), actual, absolute=0, relative=0):
                raise FullVerificationError("SEMANTIC_GROUP_FIELDS_MISMATCH")
        if len(seen) != ledger.db.execute("SELECT count(*) FROM expected_groups").fetchone()[0]:
            raise FullVerificationError("SEMANTIC_GROUP_MISSING")
    matched = ambiguous = missing = 0
    if ledger.contract.fasta:
        for protein in dataset.proteins:
            expected = ledger.db.execute("SELECT sequence,state FROM expected_sequences WHERE k=?", (protein.accession,)).fetchone()
            sequence, state = expected if expected else (None, "MISSING")
            if (protein.sequence, protein.sequence_state) != (sequence, state):
                raise FullVerificationError("SEMANTIC_FASTA_SEQUENCE_MISMATCH")
            matched += state == "DIRECT"
            ambiguous += state == "AMBIGUOUS"
            missing += state == "MISSING"
    return {"protein_groups": len(seen), "group_coverage": "all source rows, fields, members and confidence",
        "fasta": {"matched": matched, "ambiguous": ambiguous, "missing": missing,
                  "coverage": "all FASTA entries read; every imported protein checked against its accession"}}
