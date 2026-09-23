"""Read-only checks of an already committed local Case. No Worker/model/recovery."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "back"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--api", required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if urlsplit(args.api).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Readback is restricted to the local application")
    from app.agent_import.case_service import get_case_service
    from app.agent_import.input_assets import hash_file
    from app.agent_import.verification import load_acceptance_contract
    from app.agent_import.verification_full import ReconciliationLedger, populate_source
    from app.core.config import settings
    service = get_case_service()
    case = service.get_case(args.case)
    if case.status.value != "SUCCESS" or not case.ever_published or case.dataset_id is None:
        raise RuntimeError("Case is not committed")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"passed": False, "case_id": case.case_id, "dataset_id": case.dataset_id, "slug": case.dataset_slug,
        "model_requests": 0, "scope": "read-only local delivery; all source assets and all match detail records"}
    contract = load_acceptance_contract(args.oracle.read_text(encoding="utf-8"))
    ledger = ReconciliationLedger(args.output / "readback.sqlite", contract)
    def get(path):
        return urlopen(args.api.rstrip("/") + path, timeout=60)
    def get_json(path):
        with get(path) as response:
            return json.load(response)
    try:
        root = settings.resolved_zp_output_root / "agent-cases" / case.case_id / "source/files"
        report["source"] = populate_source(ledger, root)
        candidate = Path(case.candidate_zp_path)
        if hash_file(candidate) != case.candidate_zp_sha256:
            raise RuntimeError("Published ZP content changed")
        from app.declarative_ingest import read_semantic_zp
        dataset = read_semantic_zp(candidate)
        report["zp"] = {"sha256": case.candidate_zp_sha256, "bytes": candidate.stat().st_size, "identifications": len(dataset.identifications)}
        assets = get_json(f"/api/v1/agent-import-cases/{case.case_id}/source-assets")
        if {a["relative_path"] for a in assets} != set(contract.source_roles):
            raise RuntimeError("Source download catalog is incomplete")
        report["source_downloads"] = []
        for asset in assets:
            digest, count = hashlib.sha256(), 0
            with get(f"/api/v1/agent-import-cases/{case.case_id}/source-assets/{asset['asset_id']}") as response:
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    digest.update(chunk)
            if digest.hexdigest() != asset["sha256"] or count != asset["size_bytes"]:
                raise RuntimeError("Downloaded source identity mismatch")
            report["source_downloads"].append({"relative_path": asset["relative_path"], "bytes": count, "sha256": digest.hexdigest()})
        handover = [a.structured_payload for a in service.list_artifacts(case.case_id) if a.artifact_type == "handover"][-1]
        with get(f"/api/v1/agent-import-cases/{case.case_id}/handover") as response:
            markdown = response.read()
        if hashlib.sha256(markdown).hexdigest() != handover["sha256"]:
            raise RuntimeError("HANDOVER identity mismatch")
        (args.output / "HANDOVER.md").write_bytes(markdown)
        report["handover_sha256"] = handover["sha256"]
        page = 1
        while True:
            listing = get_json(f"/api/v1/datasets/{case.dataset_slug}/matches?page={page}&page_size=20&sort=match_id&order=asc&q_filter=false&decoy=true")
            if listing["total"] != len(dataset.identifications):
                raise RuntimeError("Delivered list scope changed")
            if not listing["items"]:
                break
            for item in listing["items"]:
                detail = get_json(f"/api/v1/datasets/{case.dataset_slug}/matches/{item['id']}")
                m = detail["extra_metadata"]
                record = {"run": m["source_run_name"], "source_id": m["source_record_id"], "sequence": detail["sequence"],
                    "modified_sequence": detail["modified_sequence"], "rt_seconds": detail["retention_time"] * 60 if detail["retention_time"] is not None else None,
                    "q_value": detail["q_value"], "score": detail["score"], "charge": detail["precursor_charge"], "precursor_mz": detail["precursor_mz"],
                    "decoy": detail["is_decoy_match"], "proteins": sorted(m["protein_accessions"]),
                    "groups": {g["source_group"]: sorted(g["members"]) for g in m["protein_groups"]},
                    "quantification": [{k:q.get(k) for k in ("value", "unit", "metric", "channel", "sample", "normalization_kind")} for q in m["quantification"]],
                    "source_fields": m["source_fields"], "source_relative_path": m["source_relative_path"], "source_row_number": m["source_row_number"],
                    "neutral_mass": detail["experimental_mass"], "scan": m["source_scan"]}
                # PEP is verified in ZP/SQL and original source fields, but the
                # current public detail DTO has no separate canonical PEP field.
                ledger.compare("delivered_http", record, fields=list(record))
            page += 1
        report["http"] = ledger.finish("delivered_http")
        report["http"]["pages_including_empty"] = page
        report["http"]["canonical_pep_field"] = "not exposed; source_fields preserved; independent SQL verification covers PEP"
        report["passed"] = True
    finally:
        ledger.close()
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "dataset_id": case.dataset_id, "matches": len(dataset.identifications), "sources": len(assets)}))


if __name__ == "__main__":
    main()
