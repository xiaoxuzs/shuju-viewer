"""Check an unchanged retained model plan with trusted tools; no model, business DB, or Case writes."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "back"))


def main():
    parser = argparse.ArgumentParser()
    for name in ("artifacts", "case", "source", "oracle", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    from app.agent_import.contracts import AgentCandidatePlan
    from app.agent_import.model_provider import _trusted_observations
    from app.agent_import.mapping_preflight import preflight_mapping_plan
    from app.agent_import.verification import load_acceptance_contract
    from app.agent_import.verification_full import ReconciliationLedger, populate_source, reconcile_semantic, FullVerificationError
    from app.declarative_ingest import build_declarative_zp_artifact
    artifacts = json.loads(args.artifacts.read_text(encoding="utf-8"))
    strategy = next(a["structured_payload"] for a in artifacts if a["artifact_type"] == "strategy")
    raw = [a["structured_payload"] for a in artifacts if a["artifact_type"] == "candidate_plan"][-1]
    plan = AgentCandidatePlan.model_validate(raw)
    case = json.loads(args.case.read_text(encoding="utf-8"))
    contract = load_acceptance_contract(args.oracle.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {"passed": False, "model_calls": 0, "source_plan": "unchanged retained model candidate", "scope": "offline deterministic ZP/source semantic check only; no business publication"}
    ledger = ReconciliationLedger(args.output / "source.sqlite", contract)
    try:
        preflight_mapping_plan(source_root=args.source, plan=plan, allow_legacy_mapping=False, trusted_observations=_trusted_observations(strategy))
        report["source"] = populate_source(ledger, args.source)
        artifact = build_declarative_zp_artifact(source_root=args.source, source_fingerprint=case["dataset_fingerprint"],
            plan=plan.zp_conversion_plan.declarative_plan, output_path=args.output / "candidate.zp")
        report["semantic"] = reconcile_semantic(ledger, artifact.semantic_dataset)
        report["passed"] = True
    except FullVerificationError as exc:
        report.update(failure_code=exc.code, diagnostic=exc.report)
    except Exception as exc:
        report.update(failure_code=getattr(exc, "code", type(exc).__name__), message=str(exc)[:1000])
    finally:
        ledger.close()
        report["seconds"] = time.monotonic() - started
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
