"""Local operator gate for newly enabled source/verification privileges."""

import hmac
import ipaddress
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from app.core.config import settings


def guard_workspace_request(request: Request) -> None:
    """Shared workspace access, not user authentication.

    Deployment controls who can reach Viewer. Keep browser cross-site and Host
    protection without requiring a session, operator token or model grant.
    This guard never assigns the internal-operator identity.
    """
    try:
        host = urlsplit("http://" + request.headers.get("host", ""))
        configured = {urlsplit(value).netloc.lower() for value in settings.cors_origin_list}
        local = host.hostname == "localhost"
        if not local:
            try:
                local = ipaddress.ip_address(host.hostname or "").is_loopback
            except ValueError:
                pass
        valid_host = bool(host.hostname) and not host.username and not host.password and (local or host.netloc.lower() in configured)
        origin = request.headers.get("origin")
        if origin is not None:
            parsed = urlsplit(origin)
            valid_origin = (parsed.scheme in {"http", "https"} and not parsed.username and not parsed.password
                and not parsed.path and not parsed.query and not parsed.fragment
                and (parsed.netloc.lower() == host.netloc.lower() or origin in settings.cors_origin_list))
        else:
            valid_origin = True  # non-browser clients within the deployment boundary
    except ValueError:
        valid_host = valid_origin = False
    if not valid_host or not valid_origin or request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, detail={"code": "WORKSPACE_ORIGIN_REJECTED", "message": "Request origin is outside this Viewer workspace."})


def require_internal_operator(request: Request) -> None:
    token = settings.agent_internal_token or ""
    try:
        loopback = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        loopback = False
    supplied = request.headers.get("authorization", "")
    if not loopback or len(token) < 32 or not hmac.compare_digest(supplied, f"Bearer {token}"):
        raise HTTPException(403, detail={"code": "AGENT_OPERATOR_REQUIRED", "message": "This operation requires an authenticated local operator."})
    request.state.viewer_subject = "local-operator"


def require_operator(request: Request) -> None:
    if settings.agent_browser_sessions_enabled and not request.headers.get("authorization"):
        from .local_sessions import authenticate, check_resource
        authenticate(request)
        if request.path_params.get("case_id"):
            check_resource(request, "case", request.path_params["case_id"])
    else:
        require_internal_operator(request)


def guard_privileged_agent_mode(request: Request) -> None:
    if settings.agent_model_authorization_required or settings.agent_browser_sessions_enabled or settings.agent_source_read_enabled or settings.agent_candidate_verification_enabled or settings.agent_auto_delivery_enabled or settings.agent_engineering_enabled:
        require_operator(request)
