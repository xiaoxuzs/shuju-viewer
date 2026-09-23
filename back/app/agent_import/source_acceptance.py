"""Trusted source-derived acceptance; never consume the model's proposed plan."""
from pathlib import Path
from lxml import etree as ElementTree
from app.agent_import.errors import AgentImportError
from app.agent_import.input_assets import content_manifest
from app.agent_import.verification_full import FullAcceptanceContract
from app.agent_import.source_code import canonical_bytes, digest_bytes


def build_registered_acceptance(source: Path, *, requirements_sha256: str, source_identity: str):
    from app.source_inspection.registered import _maxquant_table_contract, _thermo_dependent_filter_contract
    manifest = content_manifest(source)
    if manifest["sha256"] != source_identity:
        raise ValueError("Frozen source content identity changed")
    # Explicit source parameter, not a candidate-derived answer or filename guess.
    parameters = source / "mqpar.xml"
    if not parameters.is_file() or parameters.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("No registered independent source contract")
    from app.source_inspection.paths import CasePathResolver
    CasePathResolver(source).resolve_file("mqpar.xml")
    parser = ElementTree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, remove_comments=True)
    document = ElementTree.parse(str(parameters), parser)
    if document.docinfo.doctype:
        raise ValueError("DTD is outside the registered source contract")
    rules = {e.text for e in document.iter()
             if isinstance(e.tag, str) and e.tag.rsplit("}", 1)[-1] == "identifierParseRule"}
    if rules not in ({r">(\S+)"}, {r"^>(\S+)"}):
        raise ValueError("FASTA identifier rule is outside the registered first-token contract")
    tables = {}
    for name in manifest["files"]:
        if Path(name).suffix.lower() not in {".txt", ".tsv"}:
            continue
        facts = _maxquant_table_contract(source, source / name)
        if facts:
            owner = facts["quantification_owner"]
            if owner in tables:
                raise RuntimeError("This acceptance recipe requires one complete table per owner")
            tables[owner] = name
    if set(tables) != {"identification", "protein_group"}:
        raise RuntimeError("Missing structural MaxQuant evidence/group contract")
    spectra = [name for name in manifest["files"] if name.lower().endswith(".mzml")]
    fastas = [name for name in manifest["files"] if Path(name).suffix.lower() in {".fasta", ".fa"}]
    if len(spectra) != 1 or len(fastas) != 1 or not _thermo_dependent_filter_contract(source / spectra[0]):
        raise RuntimeError("This independent recipe needs one explicitly DDA mzML and one FASTA")
    roles = {name: "provenance" for name in manifest["files"]}
    roles.update({tables["identification"]: "identifications", tables["protein_group"]: "protein_groups", spectra[0]: "spectra", fastas[0]: "reference_sequences"})
    contract = FullAcceptanceContract.model_validate({
        "schema_version": 3, "verifier_version": "full-semantic-v2.1", "source_identity": manifest["sha256"],
        "requirements_sha256": requirements_sha256, "acquisition_mode": "dda",
        "source_evidence": "Protected MaxQuantParams/table structural contract; independent full table and FASTA reads; all MS2 carry Thermo data-dependent filter flags. Not derived from the candidate plan.",
        "scope": "All input files preserved; all evidence/group rows and fields, memberships, confidence, identification quantities, imported FASTA sequences, DDA spectra/peaks and chromatograms checked. Group quantities retained at group source-field scope, not identification quantities. Representative browser interaction only.",
        "source_roles": roles,
        "table": {"relative_path": tables["identification"], "reader": "delimited", "id_column": "id", "run_column": "Raw file",
            "sequence_column": "Sequence", "modified_column": "Modified sequence", "rt_column": "Retention time", "rt_unit": "minute",
            "score_column": "Score", "pep_column": "PEP", "neutral_mass_column": "Mass", "scan_column": "MS/MS scan number",
            "charge_column": "Charge", "mz_column": "m/z", "proteins_column": "Proteins", "group_column": "Protein group IDs", "external_groups": True,
            "quantity_column": "Intensity", "quantity_unit": "source_intensity", "quantity_sample_column": "Experiment",
            "semantics_evidence": "Registered MaxQuant source contract: RT minutes, PEP not q-value, evidence-owned Intensity, reported Experiment; no normalized/channel claim."},
        "groups": {"relative_path": tables["protein_group"], "id_column": "id", "members_column": "Protein IDs", "q_column": "Q-value",
            "semantics_evidence": "MaxQuant group ID/member list and group Q-value. Majority IDs are not an invented unique leader; every raw field including group quantities must survive."},
        "fasta": {"relative_path": fastas[0], "accession_rule": "first_token", "semantics_evidence": "Direct full first-token FASTA accessions; missing and ambiguous proteins remain explicit."},
        "numeric_absolute_tolerance": 1e-7, "numeric_relative_tolerance": 1e-9,
        "required_views": {"bu.matches": "AVAILABLE", "bu.peptides": "AVAILABLE", "bu.proteins": "AVAILABLE", "spectra": "AVAILABLE"}})

    import csv
    for specification in (contract.table, contract.groups):
        with (source / specification.relative_path).open(encoding="utf-8-sig", newline="") as stream:
            headers = set(next(csv.reader(stream, delimiter="\t"), []))
        columns = {v for k, v in specification.model_dump().items() if k.endswith("_column") and v is not None}
        if not columns.issubset(headers):
            raise ValueError("Source columns do not satisfy the registered independent semantic contract")
    return contract


def ensure_registered_acceptance(source: Path, *, source_identity: str, requirements_sha256: str, oracle_root: Path):
    """Reuse a protected compatible contract, or construct one before any model plan."""
    from app.agent_import.verification import load_acceptance_contract
    path = oracle_root / f"{source_identity}-{requirements_sha256}.json"
    if path.is_file():
        contract = load_acceptance_contract(path.read_text(encoding="utf-8"))
    else:
        try:
            contract = build_registered_acceptance(source, requirements_sha256=requirements_sha256, source_identity=source_identity)
        except (ValueError, RuntimeError, OSError, ElementTree.XMLSyntaxError) as exc:
            raise AgentImportError("VERIFICATION_SOURCE_RULE_UNAVAILABLE",
                "当前来源不符合已注册的独立验证规则；需要扩展验证能力，而不是补充模型授权。",
                status_code=409, diagnostics={"cause_type": type(exc).__name__}) from exc
        oracle_root.mkdir(parents=True, exist_ok=True)
        payload = canonical_bytes(contract.model_dump(mode="json"))
        # Publish a complete immutable file; a concurrent producer must agree.
        import os
        import tempfile
        fd, temporary = tempfile.mkstemp(prefix="acceptance-", dir=oracle_root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != payload:
                    raise AgentImportError("VERIFICATION_BASELINE_CONFLICT", "Independent source contract changed; preserve and reconcile it", status_code=409)
        finally:
            Path(temporary).unlink(missing_ok=True)
    if contract.source_identity != source_identity or contract.requirements_sha256 != requirements_sha256:
        raise AgentImportError("VERIFICATION_BASELINE_REQUIRED", "Independent source contract identity mismatch", status_code=409)
    return {"sha256": digest_bytes(canonical_bytes(contract.model_dump(mode="json"))),
            "source_identity": source_identity, "requirements_sha256": requirements_sha256,
            "verifier_version": getattr(contract, "verifier_version", "legacy"),
            "producer": "trusted_control_plane", "candidate_plan_used": False}
