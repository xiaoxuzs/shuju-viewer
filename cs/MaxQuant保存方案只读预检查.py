"""Check fresh source bindings on an existing plan; no database/model/UI actions."""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "back"))
    from app.agent_import.import_recipes import build_recipe_strategy
    from app.agent_import.source_code import canonical_bytes, digest_bytes
    artifacts = json.loads(args.artifacts.read_text(encoding="utf-8"))
    plans = [item["structured_payload"] for item in artifacts if item["artifact_type"] == "candidate_plan" and (item.get("structured_payload") or {}).get("status") == "READY"]
    if not plans:
        raise RuntimeError("No historical executable plan exists in these artifacts")
    candidate = plans[-1]
    recipe = {"recipe_id": "readonly-historical-plan", "name": candidate["source_profile"], "version": 1,
        "parent_case_id": "historical-evidence-only", "analysis_category": candidate["analysis_category"], "display_category": "DDA",
        "candidate_json": json.dumps(candidate), "candidate_sha256": digest_bytes(canonical_bytes(candidate))}
    strategy = build_recipe_strategy(recipe, args.source)
    print(json.dumps({"status": "PASSED_STATIC_SOURCE_PREFLIGHT", "model_requests": 0, "database_writes": 0,
        "fresh_observations": len(strategy["observations"]), "scope": "historical real MaxQuant plan and fresh full-source bindings; not a fresh browser/model acceptance"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
