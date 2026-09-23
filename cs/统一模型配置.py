"""Mechanical .env key migration, explicitly authorized by the project owner.

Never print values or copy dotenv to evidence/backup directories. Non-model lines
remain byte-identical. No project import, DB connection, service or model call.
"""
import argparse
import json
from pathlib import Path
import re

RENAMES = {
    "MOONSHOT_BASE_URL": "OPENAI_BASE_URL", "MOONSHOT_API_KEY": "OPENAI_API_KEY",
    "AGENT_READ_MODEL": "OPENAI_MODEL", "MOONSHOT_REQUEST_TIMEOUT_SECONDS": "OPENAI_REQUEST_TIMEOUT_SECONDS",
    "DEEPSEEK_REQUEST_TIMEOUT_SECONDS": "AGENT_IMPLEMENTATION_REQUEST_TIMEOUT_SECONDS",
}
REMOVED = {"DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "AGENT_IMPLEMENTATION_MODEL", "AGENT_MODEL_PROFILE"}
PATTERN = re.compile(r"^(\s*)([A-Z][A-Z0-9_]*)(\s*=.*)$", re.DOTALL)


def migrate(content):
    lines = content.splitlines(keepends=True)
    existing = {}
    for line in lines:
        match = PATTERN.match(line)
        if match:
            name, value = match[2], match[3]
            if name in existing:
                raise ValueError("Duplicate setting name; resolve before migration: " + name)
            existing[name] = value
    result, changed = [], []
    for line in lines:
        match = PATTERN.match(line)
        if not match:
            result.append(line)
            continue
        name = match[2]
        if name in REMOVED:
            changed.append(name + ":removed")
        elif name in RENAMES:
            target = RENAMES[name]
            if target in existing and existing[target].strip() != match[3].strip():
                raise ValueError("Conflicting canonical setting; no values displayed: " + target)
            if target not in existing:
                result.append(match[1] + target + match[3])
            changed.append(name + "->" + target)
        else:
            result.append(line)
    return "".join(result), changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "back/.env"
    original = target.read_bytes()
    result, changes = migrate(original.decode("utf-8"))
    if args.apply and changes:
        if target.read_bytes() != original:
            raise RuntimeError("dotenv changed during migration; no write")
        target.write_bytes(result.encode("utf-8"))
    print(json.dumps({"applied": bool(args.apply and changes), "changed_names_only": changes, "unrelated_lines_preserved": True}))


if __name__ == "__main__":
    main()
