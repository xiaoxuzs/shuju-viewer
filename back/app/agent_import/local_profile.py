"""Opt-in local profile, loaded before Settings. Never copies database/other dotenv values."""
import json
import os
from pathlib import Path


def apply_local_gpt_profile() -> None:
    if os.environ.get("VIEWER_ENV") not in {"test", "development"}:
        raise RuntimeError("GPT local profile requires explicit test/development environment")
    if not all(os.environ.get(name) for name in ("DATABASE_URL", "DATA_ROOT")):
        raise RuntimeError("Explicit isolated DATABASE_URL and DATA_ROOT are required")
    from sqlalchemy.engine import make_url
    database = make_url(os.environ["DATABASE_URL"])
    if database.get_backend_name() != "sqlite" and (
        database.get_backend_name() != "postgresql" or database.host not in {"127.0.0.1", "localhost", "::1"}
        or not (database.database or "").startswith("viewer_test_")
    ):
        raise RuntimeError("Local profile refuses non-local/non-test PostgreSQL targets")
    from dotenv import dotenv_values
    backend = Path(__file__).resolve().parents[2]
    # Existing process credential overrides win; only the configured GPT route is read.
    configured = dotenv_values(backend / ".env")
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"):
        if configured.get(name):
            os.environ.setdefault(name, configured[name])
    configured.clear()
    profile = json.loads((backend / "config/agent-gpt-local.json").read_text(encoding="utf-8"))
    allowed = {"AGENT_API_WORKER_ENABLED", "AGENT_CASE_TOKEN_BUDGET", "AGENT_READ_MAX_OUTPUT_TOKENS",
               "AGENT_IMPLEMENTATION_MAX_OUTPUT_TOKENS", "AGENT_REVIEW_MAX_OUTPUT_TOKENS", "AGENT_RESEARCH_REASONING_EFFORT",
               "OPENAI_REQUEST_TIMEOUT_SECONDS", "AGENT_IMPLEMENTATION_REQUEST_TIMEOUT_SECONDS"}
    if set(profile) != allowed:
        raise RuntimeError("Local model profile is not an allowed role configuration")
    # An explicitly selected profile wins over legacy role/output environment values.
    os.environ.update(profile)
