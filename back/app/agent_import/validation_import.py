"""Fixed trusted importer for committed validation data; HTTP validation is a separate full scan."""
import argparse
import json
import os
from pathlib import Path
import time


def main():
    if os.environ.get("VIEWER_ENV") != "test" or not os.environ.get("VIEWER_BUILD_ID"):
        raise SystemExit("Validation import requires an identified isolated application")
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from app.core.db import SessionLocal
    from app.agent_zp.service import import_agent_zp_candidate
    from app.schemas.agent_zp import AgentZpImportCreateIn
    from app.agent_import.verification_metrics import peak_rss_bytes
    started = time.monotonic()
    with SessionLocal() as session:
        result = import_agent_zp_candidate(session, AgentZpImportCreateIn(source_path=str(args.candidate),
            slug="candidate-validation", name="Candidate validation", analysis_category="BOTTOM_UP", source_profile="verified-candidate",
            binary_operation="register_existing_zp", format_version=3, replace_existing=False))
    args.output.write_text(json.dumps({"import_result": result.model_dump(mode="json"), "elapsed_seconds": time.monotonic() - started,
                                      "peak_rss_bytes": peak_rss_bytes(), "entry": "trusted committed import service; not an HTTP import endpoint claim"}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
