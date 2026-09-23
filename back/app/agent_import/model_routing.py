"""Role routing references existing credentials; no provider-name guessing/fallback."""
from dataclasses import dataclass
import hashlib
import json
from urllib.parse import urlsplit

from app.agent_import.errors import AgentImportError
from app.core.config import settings


@dataclass(frozen=True)
class ModelRoute:
    base_url: str
    api_key: str
    model: str
    timeout: int
    max_tokens: int


def route_for(role: str) -> ModelRoute:
    if role not in {"research", "implementation", "review", "maintenance"}:
        raise ValueError("Unimplemented model role")
    base, key, model = settings.openai_base_url.strip().rstrip("/"), (settings.openai_api_key or "").strip(), settings.openai_model.strip()
    if key:
        target = urlsplit(base)
        if not model or target.scheme not in {"http", "https"} or not target.hostname or target.username or target.password or target.query or target.fragment:
            raise AgentImportError("MODEL_PROFILE_INVALID", "Configure OPENAI_BASE_URL, OPENAI_API_KEY and OPENAI_MODEL; no other provider or endpoint fallback is available.", status_code=503)
    if role == "maintenance" and not key:
        raise AgentImportError("MODEL_PROFILE_INVALID", "Maintenance requires the single configured API connection", status_code=503)
    implementation = role == "implementation"
    timeout = (settings.agent_maintenance_request_timeout_seconds if role == "maintenance" else
               (settings.agent_implementation_request_timeout_seconds or settings.openai_request_timeout_seconds) if implementation else
               settings.agent_review_request_timeout_seconds if role == "review" else settings.openai_request_timeout_seconds)
    tokens = (settings.agent_maintenance_max_output_tokens if role == "maintenance" else
              settings.agent_implementation_max_output_tokens if implementation else
              settings.agent_review_max_output_tokens if role == "review" else settings.agent_read_max_output_tokens)
    return ModelRoute(base, key or "", model, timeout, tokens)


def model_route_identity() -> str:
    routes = [route_for(role) for role in ("research", "implementation", "review")]
    value = {"connection_schema": "single-openai-v1", "reasoning": settings.agent_research_reasoning_effort,
             "routes": [{"base": r.base_url, "model": r.model, "timeout": r.timeout, "output": r.max_tokens} for r in routes]}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
