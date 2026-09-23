from copy import deepcopy
import json
from types import SimpleNamespace as Row

import pytest

from app.agent_import.input_assets import content_manifest
from app.agent_import.verification_full import FullAcceptanceContract, ReconciliationLedger, populate_source, FullVerificationError
from app.agent_import.verification_tables import reconcile_supplements


def setup_source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "ids.tsv").write_text("id\trun\tsequence\tgroups\tpep\n1\tr\tPEPTIDE\t7;8\t0.01\n")
    (root / "groups.tsv").write_text("id\tmembers\tq\tintensity\n7\tA;B\t0.02\t12\n8\tC\t0\t0\n9\tD\t0.2\t\n")
    (root / "seq.fasta").write_text(">sp|A|alpha\nPEPTIDE\n>sp|B|beta\nOTHER\n>sp|D|delta\nAAA\n>sp|D|delta\nBBB\n")
    contract = FullAcceptanceContract.model_validate({"schema_version": 3, "verifier_version": "full-semantic-v2.1",
        "source_identity": content_manifest(root)["sha256"], "source_evidence": "Independent synthetic multi-table specification",
        "scope": "all records, memberships and source-owned group values", "acquisition_mode": "dda",
        "table": {"relative_path": "ids.tsv", "reader": "delimited", "id_column": "id", "run_column": "run", "sequence_column": "sequence",
            "group_column": "groups", "external_groups": True, "pep_column": "pep", "semantics_evidence": "Explicit identity and confidence columns"},
        "groups": {"relative_path": "groups.tsv", "id_column": "id", "members_column": "members", "q_column": "q", "semantics_evidence": "Group confidence is distinct from PEP"},
        "fasta": {"relative_path": "seq.fasta", "accession_rule": "uniprot_pipe_accession", "semantics_evidence": "Explicit sp pipe FASTA identifiers"},
        "source_roles": {"ids.tsv": "identifications", "groups.tsv": "protein_groups", "seq.fasta": "reference_sequences"}})
    ledger = ReconciliationLedger(tmp_path / "ledger.sqlite", contract)
    populate_source(ledger, root)
    groups = []
    for raw, in ledger.db.execute("SELECT body FROM expected_groups ORDER BY k"):
        g = json.loads(raw)
        groups.append(Row(source_group=g["source_group"], member_protein_ids=g["members"], q_value=g["q_value"], pep=None, leading_protein_id=None, source_fields=g["source_fields"]))
    proteins = [Row(protein_id=p, accession=p, sequence=s, sequence_state=state) for p, s, state in
        [("A", "PEPTIDE", "DIRECT"), ("B", "OTHER", "DIRECT"), ("C", None, "MISSING"), ("D", None, "AMBIGUOUS")]]
    return ledger, Row(proteins=proteins, protein_groups=groups)


@pytest.mark.parametrize("mutation", [None, "group_q", "group_value", "member", "missing_group", "sequence", "ambiguous_sequence"])
def test_complete_independent_group_and_fasta_contract(tmp_path, mutation):
    ledger, dataset = setup_source(tmp_path)
    try:
        expected = json.loads(ledger.db.execute("SELECT body FROM expected").fetchone()[0])
        assert expected["groups"] == {"7": ["A", "B"], "8": ["C"]}
        assert expected["pep"] == 0.01
        if mutation == "group_q": dataset.protein_groups[-1].q_value = 0
        if mutation == "group_value": dataset.protein_groups[0].source_fields["intensity"] = "13"
        if mutation == "member": dataset.protein_groups[0].member_protein_ids = ["A", "C"]
        if mutation == "missing_group": dataset.protein_groups.pop()
        if mutation == "sequence": dataset.proteins[0].sequence = "WRONG"
        if mutation == "ambiguous_sequence": dataset.proteins[-1].sequence_state = "MISSING"
        if mutation:
            with pytest.raises(FullVerificationError): reconcile_supplements(ledger, dataset)
        else:
            report = reconcile_supplements(ledger, dataset)
            assert report["protein_groups"] == 3
            assert report["fasta"]["matched"] == 2
            assert report["fasta"]["ambiguous"] == 1
        old = ledger.contract.model_dump()
        old.update(schema_version=2, verifier_version="full-semantic-v2.0")
        with pytest.raises(ValueError, match="version 3"):
            FullAcceptanceContract.model_validate(old)
    finally:
        ledger.close()
