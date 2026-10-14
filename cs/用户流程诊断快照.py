"""Read public case diagnostics into this run's evidence directory; no mutations."""
import argparse
import json
from pathlib import Path
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    def read(suffix):
        with urlopen(args.origin + "/api/v1/agent-import-cases/" + args.case + suffix, timeout=20) as response:
            return json.load(response)
    case, artifacts = read(""), read("/artifacts")
    selected = []
    for item in artifacts:
        payload = item.get("structured_payload") or {}
        if item["artifact_type"] == "model_request":
            payload = {key: payload[key] for key in ("role", "elapsed_seconds", "request_id", "phase", "outcome", "model", "response_model") if key in payload}
        elif item["artifact_type"] in {"candidate_plan", "candidate_diagnostic", "failure_progress"}:
            pass
        else:
            continue
        selected.append({"type": item["artifact_type"], "payload": payload})
    target = args.output.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"case": case, "selected_artifacts": selected}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"case_id": args.case, "status": case["status"], "artifact_count": len(selected), "output": str(target)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
