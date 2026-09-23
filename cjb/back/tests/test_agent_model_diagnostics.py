from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError

import pytest

from app.agent_import import model_provider
from app.agent_import.kimi_research_runtime import KimiHttpError, KimiResearchError
from app.agent_import.model_diagnostics import describe_model_failure


def test_http_diagnostics_preserve_status_without_logging_response_or_url_credentials() -> None:
    error = KimiHttpError(
        502,
        json.dumps({"error": {"message": "TLS handshake: EOF; secret-key; E:\\private\\data.tsv; PRIVATE-PSM"}}),
    )

    diagnostic = describe_model_failure(
        error,
        phase="agent_1_research",
        endpoint="http://alice:secret-key@localhost:55597/v1?key=secret-key#private",
    )

    assert diagnostic["http_status"] == 502
    assert diagnostic["endpoint_origin"] == "http://localhost:55597"
    assert diagnostic["reason"] == "PROVIDER_REPORTED_TLS_HANDSHAKE_EOF"
    encoded = json.dumps(diagnostic)
    for secret in ("alice", "secret-key", "PRIVATE-PSM", "data.tsv", "private"):
        assert secret not in encoded


@pytest.mark.parametrize(
    ("status", "reason"),
    [(401, "HTTP_AUTHENTICATION_FAILED"), (403, "HTTP_FORBIDDEN"),
     (429, "HTTP_RATE_LIMITED"), (400, "HTTP_REQUEST_REJECTED"),
     (503, "HTTP_UPSTREAM_ERROR")],
)
def test_http_status_is_not_flattened_into_connection_failure(status: int, reason: str) -> None:
    result = describe_model_failure(
        KimiHttpError(status, "private response"), phase="agent_1_research", endpoint="http://localhost:55597/v1",
    )
    assert result["http_status"] == status
    assert result["reason"] == reason


def test_wrapped_transport_error_keeps_only_safe_cause_types() -> None:
    error = KimiResearchError("arbitrary sensitive error")
    error.__cause__ = URLError(ConnectionRefusedError(10061, "PRIVATE-PSM"))

    result = describe_model_failure(error, phase="agent_1_research", endpoint="http://localhost:60049/v1")

    assert result["http_status"] is None
    assert result["reason"] == "CONNECTION_REFUSED"
    assert result["cause_types"] == ["KimiResearchError", "URLError", "ConnectionRefusedError"]
    assert "PRIVATE-PSM" not in json.dumps(result)


def test_wrapped_chat_http_error_keeps_original_status() -> None:
    error = RuntimeError("request failed")
    error.__cause__ = HTTPError("https://example.invalid/private", 429, "PRIVATE-PSM", {}, None)
    result = describe_model_failure(error, phase="agent_2_candidate", endpoint="https://example.invalid/v1")
    assert result["http_status"] == 429
    assert result["reason"] == "HTTP_RATE_LIMITED"


def test_provider_failure_logs_safe_details_and_exposes_status_to_case(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        public_error = model_provider._model_unavailable(
            KimiHttpError(502, 'Authorization: Bearer secret-key; PRIVATE-PSM; TLS handshake: EOF'),
            phase="agent_1_research",
            endpoint="http://localhost:55597/v1?api_key=secret-key",
        )

    assert public_error.code == "MODEL_PROVIDER_UNAVAILABLE"
    assert "HTTP 502" in public_error.message
    assert "agent_1_research" in public_error.message
    assert "PROVIDER_REPORTED_TLS_HANDSHAKE_EOF" in public_error.message
    assert '"http_status": 502' in caplog.text
    assert "secret-key" not in caplog.text + public_error.message
    assert "PRIVATE-PSM" not in caplog.text + public_error.message
    assert all(record.exc_info is None for record in caplog.records)
