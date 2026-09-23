"""Short-lived local browser sessions bootstrapped only by a trusted launcher.

Only hashes are persisted. The one-time handoff travels in a URL fragment, is
removed before React renders, then POSTed to the exact configured local origin.
Long-lived operator credentials never enter the browser.
"""
import hashlib
import hmac
import ipaddress
import secrets
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.core.config import settings


DDL = (
    """CREATE TABLE IF NOT EXISTS agent_browser_handoffs (
        token_hash TEXT PRIMARY KEY, subject TEXT NOT NULL, origin TEXT NOT NULL,
        expires_at DOUBLE PRECISION NOT NULL, consumed INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS agent_browser_sessions (
        token_hash TEXT PRIMARY KEY, subject TEXT NOT NULL, origin TEXT NOT NULL,
        csrf_hash TEXT NOT NULL, expires_at DOUBLE PRECISION NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS agent_resource_owners (
        resource_kind TEXT NOT NULL, resource_id TEXT NOT NULL, subject TEXT NOT NULL,
        PRIMARY KEY(resource_kind,resource_id))""",
)
COOKIE = "viewer_local_session"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def session_engine():
    from app.core.db import engine
    return engine


def validate_origin(origin):
    url = urlsplit(origin)
    if url.scheme not in {"http", "https"} or url.username or url.password or url.path or url.query or url.fragment:
        raise ValueError("An exact local browser origin is required")
    try:
        local = url.hostname == "localhost" or ipaddress.ip_address(url.hostname).is_loopback
    except ValueError:
        local = False
    if not local:
        raise ValueError("Browser initialization is local-only")
    return url


def create_handoff(engine, *, origin, subject="local-operator", seconds=60):
    """Trusted CLI/control plane only. Never register as an unauthenticated API."""
    validate_origin(origin)
    if not subject or not 1 <= seconds <= 120:
        raise ValueError("Invalid finite handoff")
    token = secrets.token_urlsafe(32)
    with engine.begin() as db:
        for sql in DDL:
            db.execute(text(sql))
        db.execute(text("INSERT INTO agent_browser_handoffs VALUES (:token,:subject,:origin,:expires,0)"),
                   {"token": digest(token), "subject": subject, "origin": origin, "expires": time.time() + seconds})
    return token


def boundary(request, *, require_origin):
    origin = settings.agent_browser_origin
    if not settings.agent_browser_sessions_enabled or not origin:
        raise HTTPException(403, detail={"code": "LOCAL_SESSION_DISABLED"})
    allowed = validate_origin(origin)
    try:
        local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    # The proxy must preserve Host. Never trust forwarded host/origin headers.
    if not local or request.headers.get("host") != allowed.netloc or request.headers.get("sec-fetch-site") not in {None, "same-origin", "none"}:
        raise HTTPException(403, detail={"code": "LOCAL_SESSION_ORIGIN_REJECTED"})
    supplied = request.headers.get("origin")
    if supplied != origin and (require_origin or supplied is not None):
        raise HTTPException(403, detail={"code": "LOCAL_SESSION_ORIGIN_REJECTED"})
    return origin


def authenticate(request, *, mutation=None):
    mutation = request.method not in {"GET", "HEAD", "OPTIONS"} if mutation is None else mutation
    origin = boundary(request, require_origin=mutation)
    token = request.cookies.get(COOKIE, "")
    with session_engine().connect() as db:
        row = db.execute(text("SELECT * FROM agent_browser_sessions WHERE token_hash=:token"), {"token": digest(token)}).mappings().first()
    if not row or row["revoked"] or row["expires_at"] <= time.time() or row["origin"] != origin:
        raise HTTPException(401, detail={"code": "LOCAL_SESSION_REQUIRED"})
    if mutation and not hmac.compare_digest(digest(request.headers.get("x-viewer-csrf", "")), row["csrf_hash"]):
        raise HTTPException(403, detail={"code": "LOCAL_SESSION_CSRF_REJECTED"})
    request.state.viewer_subject = row["subject"]
    return row["subject"]


def claim_resource(request, kind, resource_id):
    subject = getattr(getattr(request, "state", None), "viewer_subject", None)
    if subject is None:
        return
    with session_engine().begin() as db:
        row = db.execute(text("SELECT subject FROM agent_resource_owners WHERE resource_kind=:kind AND resource_id=:id"), {"kind": kind, "id": resource_id}).scalar()
        if row is not None and row != subject:
            raise HTTPException(403, detail={"code": "RESOURCE_FORBIDDEN"})
        if row is None:
            db.execute(text("INSERT INTO agent_resource_owners VALUES (:kind,:id,:subject) ON CONFLICT DO NOTHING"), {"kind": kind, "id": resource_id, "subject": subject})
            owner = db.execute(text("SELECT subject FROM agent_resource_owners WHERE resource_kind=:kind AND resource_id=:id"), {"kind": kind, "id": resource_id}).scalar_one()
            if owner != subject:
                raise HTTPException(403, detail={"code": "RESOURCE_FORBIDDEN"})


def check_resource(request, kind, resource_id):
    subject = getattr(getattr(request, "state", None), "viewer_subject", None)
    if subject is None:
        return
    with session_engine().connect() as db:
        owner = db.execute(text("SELECT subject FROM agent_resource_owners WHERE resource_kind=:kind AND resource_id=:id"), {"kind": kind, "id": resource_id}).scalar()
    if owner != subject:
        raise HTTPException(403, detail={"code": "RESOURCE_FORBIDDEN"})


def guard_upload_session(request: Request):
    if settings.agent_browser_sessions_enabled:
        authenticate(request)
        if request.path_params.get("upload_id"):
            check_resource(request, "upload", request.path_params["upload_id"])


def owned_ids(request, kind):
    subject = getattr(request.state, "viewer_subject", None)
    if subject is None:
        return None
    with session_engine().connect() as db:
        return set(db.execute(text("SELECT resource_id FROM agent_resource_owners WHERE subject=:subject AND resource_kind=:kind"), {"subject": subject, "kind": kind}).scalars())


router = APIRouter(tags=["local-session"])


class Exchange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    handoff: str = Field(min_length=32, max_length=120)


@router.post("/local-session/exchange")
def exchange_handoff(body: Exchange, request: Request, response: Response):
    origin = boundary(request, require_origin=True)
    now = time.time()
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with session_engine().begin() as db:
        consumed = db.execute(text("UPDATE agent_browser_handoffs SET consumed=1 WHERE token_hash=:token AND origin=:origin AND consumed=0 AND expires_at>:now"),
                              {"token": digest(body.handoff), "origin": origin, "now": now})
        if consumed.rowcount != 1:
            raise HTTPException(401, detail={"code": "LOCAL_HANDOFF_EXPIRED_OR_USED"})
        subject = db.execute(text("SELECT subject FROM agent_browser_handoffs WHERE token_hash=:token"), {"token": digest(body.handoff)}).scalar_one()
        expires = now + min(3600, settings.agent_browser_session_seconds)
        db.execute(text("INSERT INTO agent_browser_sessions VALUES (:token,:subject,:origin,:csrf,:expires,0)"),
                   {"token": digest(token), "subject": subject, "origin": origin, "csrf": digest(csrf), "expires": expires})
    response.set_cookie(COOKIE, token, httponly=True, secure=origin.startswith("https:"), samesite="strict", max_age=int(expires-now), path="/api/v1")
    response.headers["Cache-Control"] = "no-store"
    return {"csrf": csrf, "expires_at": expires}


@router.post("/local-session/revoke")
def revoke_session(request: Request, response: Response):
    authenticate(request)
    with session_engine().begin() as db:
        db.execute(text("UPDATE agent_browser_sessions SET revoked=1 WHERE token_hash=:token"), {"token": digest(request.cookies[COOKIE])})
    response.delete_cookie(COOKIE, path="/api/v1")
    return {"revoked": True}
