"""Bounded, redacted model diagnostics; never log raw HTTP response bodies."""

from __future__ import annotations

import json
import math
import re
from typing import Any
from urllib.error import URLError
from urllib.parse import urlsplit

from pydantic import ValidationError


def describe_model_failure(exc: Exception, *, phase: str, endpoint: str) -> dict[str, Any]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and len(chain) < 6 and all(current is not item for item in chain):
        chain.append(current)
        reason = getattr(current, "reason", None)
        current = current.__cause__ or (reason if isinstance(reason, BaseException) else None)
    status = next((
        value for item in chain
        if isinstance(value := getattr(item, "status_code", getattr(item, "code", None)), int)
        and not isinstance(value, bool) and 400 <= value <= 599
    ), None)
    detail = " ".join(str(getattr(item, "detail", ""))[:1000] for item in chain).casefold()
    if status and "tls handshake" in detail and "eof" in detail:
        reason_code = "PROVIDER_REPORTED_TLS_HANDSHAKE_EOF"
    elif any(isinstance(item, ConnectionRefusedError) for item in chain):
        reason_code = "CONNECTION_REFUSED"
    elif any(isinstance(item, TimeoutError) for item in chain):
        reason_code = "TRANSPORT_TIMEOUT"
    elif any(isinstance(item, json.JSONDecodeError) for item in chain):
        reason_code = "RESPONSE_INVALID_JSON"
    elif status:
        reason_code = {401: "HTTP_AUTHENTICATION_FAILED", 403: "HTTP_FORBIDDEN",
                       429: "HTTP_RATE_LIMITED"}.get(
            status, "HTTP_UPSTREAM_ERROR" if status >= 500 else "HTTP_REQUEST_REJECTED",
        )
    elif any(isinstance(item, URLError) for item in chain):
        reason_code = "TRANSPORT_ERROR"
    else:
        reason_code = "MODEL_PROTOCOL_ERROR"
    try:
        parsed = urlsplit(endpoint)
        host = parsed.hostname or "unknown"
        host = f"[{host}]" if ":" in host else host
        origin = f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else "")
    except ValueError:
        origin = "invalid-endpoint"
    return {"phase": phase, "endpoint_origin": origin, "error_type": type(exc).__name__,
            "http_status": status, "cause_types": [type(item).__name__ for item in chain],
            "reason": reason_code}


_SECRET_KEY = re.compile(r"(?:api[_-]?key|authorization|password|access[_-]?token|refresh[_-]?token|secret)", re.I)
_TOKEN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|agt_[A-Za-z0-9_-]{8,}|Bearer\s+[^\s\"',;]+)", re.I)
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"'<>]*")
_POSIX_PATH = re.compile(r"(?<![\w:/])/[^\s\"'<>]+")


def redact_diagnostic(value: Any, *, secrets: tuple[str, ...] = (), depth: int = 0) -> Any:
    if depth > 20:
        return "[TRUNCATED]"
    if isinstance(value, str):
        for secret in sorted((item for item in secrets if item), key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        value = _TOKEN.sub("[REDACTED]", value)
        value = re.sub(r"https?://[^\s\"'<>]+", "[REDACTED_URL]", value)
        value = _WINDOWS_PATH.sub("[REDACTED_PATH]", value)
        value = _POSIX_PATH.sub("[REDACTED_PATH]", value)
        return value[:4000] + ("[TRUNCATED]" if len(value) > 4000 else "")
    if isinstance(value, dict):
        return {
            redact_diagnostic(str(key), secrets=secrets): (
                "[REDACTED]" if _SECRET_KEY.search(str(key))
                else redact_diagnostic(item, secrets=secrets, depth=depth + 1)
            )
            for key, item in list(value.items())[:1000]
        }
    if isinstance(value, (list, tuple)):
        return [redact_diagnostic(item, secrets=secrets, depth=depth + 1) for item in value[:1000]]
    if isinstance(value, float) and not math.isfinite(value):
        return "[NON_FINITE]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[UNSUPPORTED_VALUE]"


def candidate_diagnostic(
    *, candidate: Any, error: Exception, attempt: int, revision: int,
    model: str, secrets: tuple[str, ...],
) -> dict[str, Any]:
    errors = (
        error.errors(include_input=False, include_context=False, include_url=False)
        if isinstance(error, ValidationError)
        else [{"loc": [], "type": getattr(error, "code", type(error).__name__), "msg": str(error)}]
    )
    record = redact_diagnostic({
        "schema_version": 1, "context_revision": revision, "candidate_attempt": attempt,
        "model": model, "kind": "schema_rejected" if isinstance(error, ValidationError) else "preflight_rejected",
        "errors": errors, "candidate": candidate,
    }, secrets=secrets)
    if len(json.dumps(record, ensure_ascii=False).encode("utf-8")) > 256_000:
        record["candidate"] = {"truncated": True, "reason": "diagnostic_size_limit"}
    return record
