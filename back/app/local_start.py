"""Normal local API/Worker startup. No per-Case script, grant or model fallback."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time


def _file(path, label):
    result = Path(path).resolve()
    if not result.is_file():
        raise RuntimeError(f"Local import prerequisite missing: {label}; configure the installed tool path (no automatic installation)")
    return result


def prepare_environment(config, inherited=None):
    """One-time application configuration, independent of any input/Case/plan."""
    env = dict(os.environ if inherited is None else inherited)
    if env.get("VIEWER_ENV", "development") not in {"development", "test"}:
        raise RuntimeError("Local startup does not deploy to production")
    from sqlalchemy.engine import make_url
    if make_url(config.database_url).host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Local startup requires an explicitly configured local PostgreSQL database")
    source_root = config.agent_source_root.resolve()
    runtime = config.resolved_zp_output_root / "runtime"
    # Ordinary users never write this control directory through an HTTP path.
    from app.agent_import.source_code import _linked
    for parent in (runtime, *runtime.parents):
        if parent.exists() and _linked(parent):
            raise RuntimeError("Linked runtime control path is forbidden")
    runtime.mkdir(parents=True, exist_ok=True)
    postgres = config.agent_verification_postgres_bin
    if postgres is None:
        on_path = shutil.which("pg_config", path=env.get("PATH"))
        postgres = Path(on_path).parent if on_path else source_root / "cjb/runtime/postgresql/bin"
    suffix = ".exe" if os.name == "nt" else ""
    for binary in ("initdb", "postgres", "pg_ctl"):
        _file(postgres / (binary + suffix), "PostgreSQL " + binary)
    node = config.agent_verification_node or shutil.which("node", path=env.get("PATH"))
    if node is None:
        raise RuntimeError("Local import prerequisite missing: installed Node.js on PATH")
    node = _file(node, "Node.js")
    browser_cache = config.agent_verification_browser_cache or env.get("PLAYWRIGHT_BROWSERS_PATH")
    if browser_cache is None:
        if os.name != "nt" or not env.get("LOCALAPPDATA"):
            raise RuntimeError("Configure the installed browser cache path")
        browser_cache = Path(env["LOCALAPPDATA"]) / "ms-playwright"
    browser_cache = Path(browser_cache).resolve()
    if not browser_cache.is_dir() or not any(browser_cache.glob("chromium*")):
        raise RuntimeError("Local import prerequisite missing: installed Playwright Chromium (no automatic download)")
    key = config.agent_verification_signing_key
    if not key:
        if os.name != "nt":
            raise RuntimeError("Configure a private verification signing key on this platform")
        from app.agent_import.test_storage import protect_secrets, unprotect_secrets
        key_path = runtime / "verification-key.dpapi"
        if not key_path.exists():
            material = protect_secrets({"signing_key": secrets.token_urlsafe(48)})
            import tempfile
            descriptor, temporary = tempfile.mkstemp(prefix="key-", dir=runtime)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(material)
                try:
                    os.link(temporary, key_path)
                except FileExistsError:
                    pass
            finally:
                Path(temporary).unlink(missing_ok=True)
        key = unprotect_secrets(key_path.read_bytes())["signing_key"]
    profile_path = Path(__file__).resolve().parents[1] / "config/agent-gpt-local.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    allowed = {"AGENT_API_WORKER_ENABLED", "AGENT_CASE_TOKEN_BUDGET", "AGENT_READ_MAX_OUTPUT_TOKENS", "AGENT_IMPLEMENTATION_MAX_OUTPUT_TOKENS",
        "AGENT_REVIEW_MAX_OUTPUT_TOKENS", "OPENAI_REQUEST_TIMEOUT_SECONDS", "AGENT_IMPLEMENTATION_REQUEST_TIMEOUT_SECONDS",
        "AGENT_RESEARCH_REASONING_EFFORT"}
    if set(profile) != allowed:
        raise RuntimeError("Unexpected local role configuration")
    for name, value in profile.items():
        env.setdefault(name, value)  # Explicit process overrides remain authoritative.
    env.update(VIEWER_ENV=env.get("VIEWER_ENV", "development"), DATABASE_URL=config.database_url,
        DATA_ROOT=str(config.resolved_data_root), AGENT_API_WORKER_ENABLED="false", AGENT_INPUT_SNAPSHOT_ENABLED="true",
        AGENT_CANDIDATE_VERIFICATION_ENABLED="true", AGENT_VERIFICATION_POSTGRES_BIN=str(Path(postgres).resolve()),
        AGENT_VERIFICATION_NODE=str(node), AGENT_VERIFICATION_BROWSER_CACHE=str(browser_cache),
        AGENT_VERIFICATION_ORACLE_ROOT=str(config.agent_verification_oracle_root or runtime / "source-contracts"),
        AGENT_VERIFICATION_SIGNING_KEY=key, AGENT_IMPORT_ENABLED="true", PYTHONUTF8="1")
    env.setdefault("VIEWER_VALIDATION_ID", secrets.token_hex(32))
    # Use only the already selected connection. Never expose any credential in argv/logs.
    for name, value in (("OPENAI_BASE_URL", config.openai_base_url), ("OPENAI_API_KEY", config.openai_api_key), ("OPENAI_MODEL", config.openai_model)):
        env[name] = value or ""
    if not env["OPENAI_API_KEY"] or not env["OPENAI_BASE_URL"] or not env["OPENAI_MODEL"]:
        raise RuntimeError("Configure the single OPENAI_BASE_URL, OPENAI_API_KEY and OPENAI_MODEL connection")
    return env, runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args()
    from app.core.config import settings
    env, runtime = prepare_environment(settings)
    print(json.dumps({"mode": "local API plus independent Worker", "model": env["OPENAI_MODEL"],
        "connection": "single OPENAI configuration", "verification": "automatic registered source contract",
        "implementation_timeout_seconds": int(env["AGENT_IMPLEMENTATION_REQUEST_TIMEOUT_SECONDS"])}), flush=True)
    if args.check_config:
        return
    done = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: done.set())
    children = []
    from app.agent_import.validation_processes import ProcessLifetime
    lifetime = ProcessLifetime()
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        for command in (["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)], ["app.agent_import.worker_main"]):
            child = subprocess.Popen([sys.executable, "-B", "-m", *command], cwd=Path(__file__).resolve().parents[1], env=env,
                stdin=subprocess.DEVNULL, stdout=sys.stdout, stderr=sys.stderr, **flags)
            children.append(child)
            lifetime.attach(child)
            if command[0] == "uvicorn":
                from urllib.request import urlopen
                until = time.monotonic() + 60
                while True:
                    if child.poll() is not None or time.monotonic() >= until:
                        raise RuntimeError("Local API did not become ready; Worker was not started")
                    try:
                        with urlopen(f"http://127.0.0.1:{args.port}/health", timeout=2) as response:
                            if json.load(response).get("validation_id") == env["VIEWER_VALIDATION_ID"]:
                                break
                    except OSError:
                        pass
                    time.sleep(.2)
        (runtime / "processes.json").write_text(json.dumps({"controller": os.getpid(), "api": children[0].pid,
            "worker": children[1].pid, "port": args.port}), encoding="utf-8")
        while not done.wait(1) and all(child.poll() is None for child in children):
            pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=15)
        lifetime.close()


if __name__ == "__main__":
    main()
