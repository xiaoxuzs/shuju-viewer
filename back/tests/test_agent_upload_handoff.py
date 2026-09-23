import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.agent_import.api import router
from app.agent_import.case_service import CaseService
from app.agent_import.migrations import ensure_agent_import_schema
from app.agent_import.schemas import AgentCaseFromUploadIn
from app.agent_import.upload_admission import case_from_upload
from app.core.config import settings
from app.import_types import ImportType
from app.import_uploads import service
from app.import_uploads.errors import UploadError
from app.import_uploads.locking import upload_lock


@pytest.fixture
def managed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", tmp_path)
    monkeypatch.setattr(settings, "import_upload_disk_reserve_bytes", 0)
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'cases.sqlite').as_posix()}")
    ensure_agent_import_schema(engine)
    cases = CaseService(engine)
    upload = service.create_upload(ImportType.AGENT_UNKNOWN)
    async def chunks():
        yield b"name\tvalue\na\t0\n"
    asyncio.run(service.upload_file(upload_id=upload.upload_id, relative_path="table.tsv",
                                   content_length_header="15", chunks=chunks()))
    return cases, upload.upload_id


def test_upload_is_pinned_and_retries_return_same_case(managed):
    cases, upload_id = managed
    parameters = dict(data_type="BOTTOM_UP", format_name="unknown", format_details=None)
    first = case_from_upload(cases, upload_id, **parameters)
    assert case_from_upload(cases, upload_id, **parameters).case_id == first.case_id
    assert first.source_mode == "MANAGED_UPLOAD"
    with pytest.raises(UploadError):
        service.delete_upload(upload_id)
    assert len(cases.list_cases()) == 1


def test_handoff_lock_blocks_delete_and_other_handoffs(managed):
    cases, upload_id = managed
    with upload_lock(upload_id), pytest.raises(UploadError, match="another request"):
        service.delete_upload(upload_id)


def test_upload_contract_cannot_smuggle_a_source_path():
    with pytest.raises(ValueError):
        AgentCaseFromUploadIn(upload_id="id", source_path="private/path")


def test_internal_management_still_rejects_unauthenticated_requests_before_db(monkeypatch):
    monkeypatch.setattr(settings, "agent_source_read_enabled", True)
    monkeypatch.setattr(settings, "agent_internal_token", "x" * 32)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 51000))
    response = client.get("/agent-retention/dry-run")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "AGENT_OPERATOR_REQUIRED"
