"""Loopback-only synthetic transport. Not a real model or a product fallback.

The application still runs its real tools, contracts, Worker, budget and Writer.
No private files/credentials are read; only the harness's two-row fixture is valid.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


def candidate():
    mapping = [("record", "identification", "source_id", "string", "identity"),
               ("run", "run", "name", "string", "identity"),
               ("sequence", "peptide", "sequence", "string", "identity"),
               ("proteins", "identification", "protein_accessions", "string", "semicolon_split"),
               ("intensity", "quantification", "value", "float", "identity")]
    return {"schema_version": 3, "status": "READY", "analysis_category": "BOTTOM_UP",
        "source_profile": "synthetic-gpt-normal-entry", "binary_operation": "convert_declared_mapping_to_zp",
        "zp_conversion_plan": {"relative_source": "unknown-results.tsv", "target_format_version": 3,
            "declarative_plan": {"schema_version": 1, "plan_id": "synthetic-transport-v1", "analysis_mode": "BOTTOM_UP",
                "sources": [{"source_id": "table", "relative_path": "unknown-results.tsv", "role": "identification_table",
                    "reader": "delimited", "delimiter": "\t", "required_fields": [m[0] for m in mapping]}],
                "field_mappings": [{"mapping_id": f"field-{f}", "source_id": "table", "source_field": f,
                    "target_entity": e, "target_field": t, "value_kind": k, "transform": tr, "required": f != "intensity",
                    "evidence_refs": ["fixture-1"]} for f,e,t,k,tr in mapping],
                "unmapped_fields": {"table": []}, "requested_views": [{"view_id": "bu.matches"}, {"view_id": "bu.peptides"}]}}}


def main():
    if os.environ.get("VIEWER_ENV") != "test" or os.environ.get("AGENT_TEST_MODEL_ENABLED") != "true":
        raise SystemExit("Explicit isolated fixture environment required")
    root = Path.cwd()
    sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location("fixture_blueprint", root / "tests/test_kimi_research_runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    blueprint = json.loads(json.dumps(module._offline_blueprint()).replace("sample.txt", "unknown-results.tsv"))
    blueprint["executive_summary"] = "Synthetic two-row transport fixture, not scientific or model acceptance."
    blueprint["source_profile"] = "synthetic-gpt-normal-entry"
    counter = 0

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            nonlocal counter
            if self.path != "/_test/chat/completions" or self.headers.get("Authorization") != "Bearer fixture-only-no-real-credential":
                self.send_error(403)
                return
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 192 * 1024 or counter >= 12:
                self.send_error(429)
                return
            body = json.loads(self.rfile.read(size))
            if body.get("model") != "gpt-test-fixture":
                self.send_error(403)
                return
            counter += 1
            payload = json.loads(body["messages"][1]["content"])
            message = {"role": "assistant"}
            finish = "stop"
            if "published_context" in payload and "contract" in payload:
                phase = "maintenance"
                value = {"status": "MAPPING_PLAN", "explanation": "Synthetic maintenance consumption; recompile existing mapping, no scientific correction or publication claimed.", "candidate": candidate()}
                value["candidate"]["zp_conversion_plan"]["declarative_plan"]["plan_id"] = "synthetic-maintenance-v1"
            elif "review_json_schema" in payload:
                phase = "review"
                value = {"schema_version": 1, "status": "APPROVED", "evidence": ["Synthetic transport response; protected verifier remains authoritative"]}
            elif "candidate_json_schema" in payload:
                phase, value = "implementation", candidate()
            else:
                phase, value = "research", blueprint
                if body.get("tools") and not any(m["role"] == "tool" for m in body["messages"]):
                    finish = "tool_calls"
                    message["tool_calls"] = [{"id": f"fixture-{i}", "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)}} for i,(name,arguments) in enumerate([
                            ("list_source_inventory", {"limit": 100}),
                            ("inspect_source_file", {"relative_path": "unknown-results.tsv"}),
                            ("inspect_viewer_capabilities", {})])]
            if finish == "stop":
                message["content"] = json.dumps(value)
            response = json.dumps({"model": "gpt-test-fixture", "choices": [{"finish_reason": finish, "message": message}]}).encode()
            print(json.dumps({"request": counter, "phase": phase, "finish_reason": finish, "request_bytes": size}), flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()


if __name__ == "__main__":
    main()
