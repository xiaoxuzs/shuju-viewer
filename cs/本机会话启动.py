"""Open a short-lived local browser handoff; never print or persist its plaintext.

Requires explicit isolated test configuration. API and frontend must already
be running with AGENT_BROWSER_SESSIONS_ENABLED=true and this exact origin.
"""
import argparse
import os
from pathlib import Path
import sys
import webbrowser


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    args = parser.parse_args()
    if os.environ.get("VIEWER_ENV") != "test" or not all(os.environ.get(k) for k in ("DATABASE_URL", "DATA_ROOT")):
        raise SystemExit("Explicit isolated test environment is required; dotenv is not loaded")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "back"))
    from app.core.db import engine
    from app.agent_import.local_sessions import create_handoff, validate_origin
    from app.core.config import settings
    validate_origin(args.origin)
    if not settings.agent_browser_sessions_enabled or settings.agent_browser_origin != args.origin:
        raise SystemExit("Launcher/API browser session configuration must agree")
    token = create_handoff(engine, origin=args.origin)
    if not webbrowser.open(args.origin + "/datasets#viewer-handoff=" + token):
        raise SystemExit("Browser could not open. Handoff will expire; its value is not printed.")
    print("Opened a one-use local session handoff (60 second expiry); no operator key sent to browser.")


if __name__ == "__main__":
    main()
