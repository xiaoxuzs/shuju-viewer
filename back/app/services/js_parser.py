"""Parse the legacy ``<variable> = {...};`` JavaScript files used by TopPIC /
TopFD HTML viewer into Python dictionaries.

All JSON bodies in these files are standards compliant so we only need to
strip the ``name =`` prefix and optional trailing semicolon.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    import orjson  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - orjson is a hard dep but fall back to json
    orjson = None  # type: ignore[assignment]


_ASSIGNMENT_RE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*", re.DOTALL)


def strip_js_shell(text: str) -> str:
    """Remove the ``var = `` prefix and trailing ``;`` from a JS data file."""
    body = _ASSIGNMENT_RE.sub("", text, count=1)
    body = body.strip()
    if body.endswith(";"):
        body = body[:-1].rstrip()
    return body


def load_js_object(path: Path) -> dict[str, Any]:
    """Read a TopPIC/TopFD JS data file and return the embedded object."""
    text = path.read_text(encoding="utf-8")
    body = strip_js_shell(text)
    if orjson is not None:
        return orjson.loads(body)
    return json.loads(body)


def load_js_object_text(text: str) -> dict[str, Any]:
    body = strip_js_shell(text)
    if orjson is not None:
        return orjson.loads(body)
    return json.loads(body)
