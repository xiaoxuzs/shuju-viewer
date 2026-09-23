import json

import pytest

from app.agent_import.source_acceptance import ensure_registered_acceptance
from app.agent_import.input_assets import content_manifest
from app.agent_import.errors import AgentImportError


def source(root):
    root.mkdir()
    (root / "mqpar.xml").write_text(r"<MaxQuantParams><maxQuantVersion>2.8.1</maxQuantVersion><identifierParseRule>&gt;(\S+)</identifierParseRule></MaxQuantParams>")
    (root / "renamed.tsv").write_text("Raw file\tSequence\tModified sequence\tRetention time\tMS/MS scan number\tProtein group IDs\tPEP\tid\tIntensity\tScore\tMass\tCharge\tm/z\tProteins\tExperiment\n")
    (root / "groups-renamed.tsv").write_text("Protein IDs\tMajority protein IDs\tQ-value\tEvidence IDs\tid\n")
    (root / "reference.fa").write_text(">A\nPEPTIDE\n")
    (root / "acquisition.mzML").write_text('<mzML><spectrum><cvParam accession="MS:1000511" value="2"/><cvParam accession="MS:1000512" value="FTMS + p NSI d Full ms2 600@hcd30 [100-1200]"/></spectrum></mzML>')
    return root


def test_new_source_builds_immutable_independent_contract_without_case_or_model(tmp_path):
    root = source(tmp_path / "source")
    output = tmp_path / "protected"
    identity = content_manifest(root)["sha256"]
    args = dict(source_identity=identity, requirements_sha256="a" * 64, oracle_root=output)
    first = ensure_registered_acceptance(root, **args)
    second = ensure_registered_acceptance(root, **args)
    assert first == second and first["candidate_plan_used"] is False
    contract = json.loads(next(output.glob("*.json")).read_text())
    assert contract["table"]["relative_path"] == "renamed.tsv"
    assert contract["groups"]["relative_path"] == "groups-renamed.tsv"
    assert "total_matches" not in contract
    assert set(contract["source_roles"]) == set(content_manifest(root)["files"])


@pytest.mark.parametrize("change", ["rule", "columns", "mode", "source_identity", "dtd"])
def test_unknown_or_changed_source_never_gets_fabricated_acceptance(tmp_path, change):
    root = source(tmp_path / "source")
    if change == "rule": (root / "mqpar.xml").write_text("<MaxQuantParams><maxQuantVersion>2</maxQuantVersion><identifierParseRule>unknown</identifierParseRule></MaxQuantParams>")
    if change == "dtd": (root / "mqpar.xml").write_text('<!DOCTYPE MaxQuantParams [<!ENTITY rule "&gt;(\\S+)">]><MaxQuantParams><identifierParseRule>&rule;</identifierParseRule></MaxQuantParams>')
    if change == "columns": (root / "renamed.tsv").write_text("id\tvalue\n")
    if change == "mode": (root / "acquisition.mzML").write_text("<mzML/>")
    identity = "0" * 64 if change == "source_identity" else content_manifest(root)["sha256"]
    with pytest.raises(AgentImportError) as exc:
        ensure_registered_acceptance(root, source_identity=identity, requirements_sha256="a" * 64, oracle_root=tmp_path / "protected")
    assert exc.value.code == "VERIFICATION_SOURCE_RULE_UNAVAILABLE"
    assert not (tmp_path / "protected").exists()
