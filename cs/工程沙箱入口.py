"""Trusted image entry, ONLY to be baked into an operator-pinned Linux sandbox image.

Do not run on the host. Dependencies must already be installed in that image.
No output from this entry is an acceptance/publication receipt.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    if os.name != "posix" or os.geteuid() == 0 or Path.cwd() != Path("/work"):
        raise SystemExit("Requires the configured non-root Linux sandbox")
    tasks = {"backend_tests": ["python3", "-B", "-m", "pytest", "-p", "no:cacheprovider", "-q", "tests"],
             "frontend_build": ["npm", "run", "build"]}
    if len(sys.argv) != 2 or sys.argv[1] not in tasks:
        raise SystemExit("Only trusted fixed checks are accepted")
    source = Path("/source")
    for entry in source.rglob("*"):
        if entry.is_symlink():
            raise SystemExit("Linked candidate paths rejected")
    shutil.copytree(source, Path("/work/candidate"))
    component = "back" if sys.argv[1] == "backend_tests" else "front"
    if component == "front":
        # Read-only, preinstalled dependencies from the pinned image, never npm install.
        Path("/work/candidate/front/node_modules").symlink_to("/opt/viewer/node_modules", target_is_directory=True)
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "TMPDIR": "/tmp"}
    raise SystemExit(subprocess.run(tasks[sys.argv[1]], cwd=Path("/work/candidate") / component, env=env,
                                   stdin=subprocess.DEVNULL, shell=False).returncode)


if __name__ == "__main__":
    main()
