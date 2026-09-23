"""Minimal Agent-ZP import API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agent_zp.service import AgentZpError, import_agent_zp_candidate
from app.api.deps import get_db
from app.schemas.agent_zp import AgentZpImportCreateIn, AgentZpImportOut


router = APIRouter(tags=["agent-zp"])


@router.post(
    "/agent-zp/imports",
    response_model=AgentZpImportOut,
    status_code=status.HTTP_201_CREATED,
)
def create_agent_zp_import(
    body: AgentZpImportCreateIn,
    session: Session = Depends(get_db),
) -> AgentZpImportOut:
    try:
        return import_agent_zp_candidate(session, body)
    except AgentZpError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
