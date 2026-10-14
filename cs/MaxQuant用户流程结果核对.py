"""Summarize retained browser evidence and compare plans structurally."""
import argparse
from datetime import datetime
import json
from pathlib import Path
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--initial", type=Path, required=True)
    parser.add_argument("--repair", type=Path, required=True)
    parser.add_argument("--origin", required=True)
    args = parser.parse_args()
    initial = json.loads(args.initial.read_text(encoding="utf-8"))
    repair = json.loads(args.repair.read_text(encoding="utf-8"))
    case = initial["cases"][1]
    with urlopen(args.origin + "/api/v1/agent-import-cases/" + case["case_id"] + "/maintenance") as response:
        tasks = json.load(response)
    published = next(task for task in tasks if task["task_id"] == repair["maintenance"]["task_id"])
    original, changed = case["plan"], json.loads(published["candidate_json"])
    original["zp_conversion_plan"]["declarative_plan"]["requested_views"] = changed["zp_conversion_plan"]["declarative_plan"]["requested_views"]
    def stamp(value): return datetime.fromisoformat(value.replace("Z", "+00:00"))
    first_end = next(step["time"] for step in initial["steps"] if step["label"] == "智能导入-匹配列表")
    repair_start = published["created_at"]
    repair_end = next(step["time"] for step in repair["steps"] if step["label"] == "真实修复已应用")
    result = {"initial_submit_to_browsable_seconds": (stamp(first_end) - stamp(initial["initial_submitted_at"])).total_seconds(),
        "fixed_case_elapsed_seconds": case["elapsed_seconds"], "fixed_model_requests": len(case["model_requests"]),
        "repair_feedback_to_applied_seconds": (stamp(repair_end) - stamp(repair_start)).total_seconds(),
        "only_requested_views_changed": original == changed, "recipe_version": repair["updated_recipe"]["version"],
        "repair_revision_read_back": repair["active_revision"] == repair["maintenance"]["published_revision_id"],
        "rollback_revision": repair["restored"]["active_revision_id"], "browser_flow_passed": repair["passed"]}
    (args.repair.parent / "核对摘要.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__": main()
