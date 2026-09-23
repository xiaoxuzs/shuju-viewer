"""Hard wall-clock boundary for the trusted XLSX parser, not a code sandbox."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from app.agent_import.execution_control import checkpoint
from app.agent_import.validation_processes import ProcessLifetime


def preview_xlsx(path, result, sheet, sheet_offset, row_offset, field_offset, field_limit, *, seconds=5):
    env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "TEMP", "TMP") if k in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    payload = json.dumps([str(path.resolve()), result, sheet, sheet_offset, row_offset, field_offset, field_limit]).encode()
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    life = ProcessLifetime()
    process = None
    started = time.monotonic()
    try:
        process = subprocess.Popen([sys.executable, "-B", "-m", "app.source_inspection.preview_process"],
            cwd=Path(__file__).resolve().parents[2], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **flags)
        life.attach(process)
        first = True
        while True:
            remaining = min(seconds - (time.monotonic() - started), checkpoint(timeout=seconds))
            if remaining <= 0:
                return {**result, "records": [], "status": "PARTIAL", "truncation": ["xlsx_wall_clock_limit"],
                        "budget": {"max_seconds": seconds, "elapsed_seconds": time.monotonic() - started, "parser_terminated": True}}
            try:
                stdout, _ = process.communicate(payload if first else None, timeout=min(remaining, 0.1))
                break
            except subprocess.TimeoutExpired:
                first = False
        checkpoint()
        if process.returncode or len(stdout) > 196608:
            raise ValueError("XLSX parser failed or exceeded its output budget")
        value = json.loads(stdout)
        if "parser_error" in value:
            raise ValueError("XLSX parser rejected its bounded input: " + value["parser_error"])
        value["budget"] = {"max_seconds": seconds, "elapsed_seconds": time.monotonic() - started,
                           "container_limit_bytes": 67108864, "member_limit_bytes": 8388608}
        return value
    finally:
        life.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


def main():
    from .preview import _xlsx
    args = json.loads(sys.stdin.buffer.read(16385))
    args[0] = Path(args[0])
    try:
        value = _xlsx(*args)
    except (ValueError, OSError, KeyError, IndexError) as exc:
        value = {"parser_error": type(exc).__name__}
    sys.stdout.write(json.dumps(value, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
