"""Bake as /opt/viewer/engineering-admission.py in the operator-pinned image.
Run only under the trusted controller's constrained container policy.
"""
import json
import os
from pathlib import Path
import socket
import sys


def cannot_write(path):
    try:
        with path.open("x") as stream:
            stream.write("isolation probe")
    except OSError:
        return True
    path.unlink()
    return False


def main():
    if len(sys.argv) != 2 or os.name != "posix":
        raise SystemExit("Trusted Linux probe invocation required")
    nonce = sys.argv[1]
    if Path("/source/probe.txt").read_text().strip() != nonce:
        raise SystemExit("Wrong isolated source mount")
    with socket.socket() as sock:
        sock.settimeout(0.5)
        try:
            sock.connect(("198.51.100.1", 443))
            denied = False
        except OSError:
            denied = True
    # TEST-NET address + absent non-loopback interface checks both intent and
    # observed namespace. It is not a proof against arbitrary kernel exploits.
    interfaces = {p.name for p in Path("/sys/class/net").iterdir()}
    memory = Path("/sys/fs/cgroup/memory.max")
    pids = Path("/sys/fs/cgroup/pids.max")
    checks = {"non_root": os.geteuid() != 0,
        "source_read_only": cannot_write(Path("/source/denied-write")),
        "root_read_only": cannot_write(Path("/denied-root-write")),
        "network_denied": denied and interfaces == {"lo"},
        "no_control_socket": not any(Path(p).exists() for p in ("/var/run/docker.sock", "/run/podman/podman.sock")),
        "no_secrets": not any(any(s in k.upper() for s in ("PASSWORD", "TOKEN", "API_KEY", "SIGNING", "DATABASE_URL")) for k in os.environ),
        "private_work": Path.cwd() == Path("/work") and not Path("/work/other-task").exists(),
        "memory_limit": memory.is_file() and memory.read_text().strip().isdigit() and int(memory.read_text()) <= 4096*1024*1024,
        "pid_limit": pids.is_file() and pids.read_text().strip().isdigit() and int(pids.read_text()) <= 128}
    print(json.dumps({"nonce": nonce, "checks": checks}))


if __name__ == "__main__":
    main()
