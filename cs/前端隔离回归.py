"""Own the mock-only Vite server and its Windows process tree; never proxy API."""

import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--browser-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--test", action="append", help="Repository-relative Playwright spec; repeat to select a subset")
    parser.add_argument("--grep", help="Playwright title filter for a deterministic targeted reproduction")
    parser.add_argument("--all", action="store_true", help="All repository frontend specs, no backend proxy")
    parser.add_argument("--seconds", type=int, help="Explicit bounded suite deadline, 30..900 seconds")
    args = parser.parse_args()
    seconds = args.seconds or (900 if args.all else 180)
    if not 30 <= seconds <= 900 or args.all and args.test:
        raise ValueError("Invalid bounded suite selection/deadline")
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "back"))
    from app.agent_import.validation_processes import ProcessLifetime
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "PATHEXT", "COMSPEC", "TEMP", "TMP") if name in os.environ}
    run_id = secrets.token_hex(16)
    env.update({"VIEWER_MOCK_RUN_ID": run_id, "VIEWER_MOCK_OUTPUT": str(output), "PLAYWRIGHT_BROWSERS_PATH": str(args.browser_cache),
                "VIEWER_MOCK_SECONDS": str(seconds),
                "PATH": str(args.node.parent) + os.pathsep + str(Path(os.environ.get("SystemRoot", "/")) / "System32")})
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    server_job, test_job = ProcessLifetime(), ProcessLifetime()
    server = tests = None
    try:
        with (output / "前端回归-server.log").open("w", encoding="utf-8") as server_log, (output / "前端回归-cli.log").open("w", encoding="utf-8") as test_log:
            server = subprocess.Popen([str(args.node), "node_modules/vite/bin/vite.js", "--config", "vite.regression.config.ts"],
                                      cwd=root / "front", env=env, stdout=server_log, stderr=subprocess.STDOUT, **flags)
            server_job.attach(server)
            deadline = time.monotonic() + 30
            while True:
                try:
                    with urlopen("http://127.0.0.1:15516", timeout=1) as response:
                        if response.headers.get("X-Viewer-Mock-Run") != run_id:
                            raise RuntimeError("Refusing an existing unidentified server")
                        break
                except OSError:
                    if server.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Regression server failed to start") from None
                    time.sleep(0.1)
            specs = args.test or ["tests/import-upload-page.spec.ts", "tests/agent-candidate-diagnostics.spec.ts", "tests/capability-report.spec.ts",
                                 "tests/bu-q-value-filter.spec.ts", "tests/bu-match-detail.spec.ts", "tests/local-session.spec.ts"]
            if args.all:
                specs = [path.relative_to(root / "front").as_posix() for path in sorted((root / "front/tests").glob("*.spec.ts"))]
            for spec in specs:
                target = (root / "front" / spec).resolve(strict=True)
                if not target.is_relative_to(root / "front/tests") or not target.name.endswith(".spec.ts"):
                    raise ValueError("Only existing frontend test specs are allowed")
            command = [str(args.node), "node_modules/@playwright/test/cli.js", "test", "--config=playwright.local-regression.config.ts", *specs]
            if args.grep:
                command.extend(["--grep", args.grep])
            tests = subprocess.Popen(command, cwd=root / "front", env=env, stdout=test_log, stderr=subprocess.STDOUT, **flags)
            test_job.attach(tests)
            code = tests.wait(timeout=seconds + 20)
            print(f"Mock_UI_regression_exit_code={code}", flush=True)
            if code:
                raise SystemExit(code)
    finally:
        test_job.close()
        server_job.close()
        for process in (tests, server):
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
