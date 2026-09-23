"""Explicit API/Worker launcher; requires test environment paths, never starts from default DB."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("component", choices=("api", "worker"))
    parser.add_argument("--port", type=int, default=18761)
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args()
    if os.environ.get("VIEWER_ENV") != "test":
        raise SystemExit("This launcher only accepts an explicitly isolated VIEWER_ENV=test")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "back"))
    from app.agent_import.local_profile import apply_local_gpt_profile
    apply_local_gpt_profile()
    from app.agent_import.model_routing import route_for
    for role in ("research", "implementation", "review"):
        route = route_for(role)
        print(f"{role}: protocol=chat_completions model={route.model} credential_present={bool(route.api_key)} timeout={route.timeout} output={route.max_tokens}", flush=True)
    if args.check_config:
        return
    if args.component == "worker":
        from app.agent_import.worker_main import main as run
        run()
    else:
        import uvicorn
        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
