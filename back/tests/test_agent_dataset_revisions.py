"""Real isolated SQL snapshots with synthetic signed control fixtures, not delivery evidence."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac

import pytest
from sqlalchemy import create_engine, text

from app.agent_import.revisions import RevisionStore
from app.agent_import.source_code import canonical_bytes
from app.agent_import.verification import seal_record
from app.agent_import.errors import AgentImportError


@pytest.fixture
def store(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'business.sqlite'}", connect_args={"timeout": 10})
    with engine.begin() as db:
        db.execute(text("CREATE TABLE datasets(dataset_id INTEGER PRIMARY KEY,slug TEXT UNIQUE)"))
        db.execute(text("CREATE TABLE identification_matches(match_id INTEGER PRIMARY KEY,dataset_id INTEGER REFERENCES datasets(dataset_id),intensity REAL)"))
        db.execute(text("INSERT INTO datasets VALUES(7,'same-dataset'),(8,'other-dataset')"))
        db.execute(text("INSERT INTO identification_matches VALUES(1,7,10),(2,8,999)"))
    value = RevisionStore(engine, tmp_path / "revisions", build_sha256="b"*64, signing_key=b"fixture-signing-key-not-a-real-admission")
    value.ensure_schema()
    candidate = tmp_path / "fixture.zp"
    candidate.write_bytes(b"synthetic control asset; not a physical-ZP verification claim")
    yield value, candidate
    engine.dispose()


def prepare(store):
    value, candidate = store
    return value.prepare(7, "same-dataset", source_sha256="a"*64, zp_path=candidate, environment_sha256="c"*64)


def sign_control_fixture(value, revision):
    row = value._row(revision)
    # These fixtures test control verification only. They are never written to
    # user evidence directories or presented as real browser/source acceptance.
    app_receipt = seal_record({"status": "PASSED", "code_sha256": value.build, "source_sha256": "a"*64,
        "candidate_sha256": row["zp_sha256"], "browser_assertions": ["synthetic-test"], "import_result": {"synthetic": True},
        "cleanup": {"processes_stopped": True}}, value.key)
    projection = {"revision_id": revision, "dataset_id": 7, "projection_sha256": value.projection_digest(revision),
        "zp_sha256": row["zp_sha256"], "source_sha256": "a"*64, "build_sha256": value.build,
        "environment_sha256": "c"*64, "status": "PASSED"}
    signed = {"record": projection, "signature": hmac.new(value.key, canonical_bytes(projection), hashlib.sha256).hexdigest()}
    return value.seal(revision, app_receipt, projection_receipt=signed)


def intensity(value, revision):
    with value.projection(revision) as db:
        assert db.execute(text("SELECT dataset_id FROM datasets")).scalars().all() == [7]
        return db.execute(text("SELECT intensity FROM identification_matches")).scalar_one()


def test_two_distinct_projection_versions_old_reader_pinning_and_rollback(store):
    value, _ = store
    first = prepare(store)
    with pytest.raises(AgentImportError):
        value.resolve("same-dataset", first)
    sign_control_fixture(value, first)
    with pytest.raises(AgentImportError):
        value.resolve("same-dataset", first)  # VALIDATED is not publicly visible
    value.activate(first, expected_base="legacy")
    second = prepare(store)
    with value.projection(second, writable=True) as db:
        db.execute(text("UPDATE identification_matches SET intensity=20"))
    sign_control_fixture(value, second)
    value.activate(second, expected_base=first)
    assert intensity(value, value.resolve("same-dataset")) == 20
    assert intensity(value, value.resolve("same-dataset", first)) == 10
    value.activate(first, expected_base=second, rollback=True)
    restarted = RevisionStore(value.engine, value.root, build_sha256=value.build, signing_key=value.key)
    assert intensity(restarted, restarted.resolve("same-dataset")) == 10
    assert intensity(restarted, second) == 20
    with value.engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM datasets")).scalar_one() == 2  # no duplicate logical dataset
        assert db.execute(text("SELECT ever_published FROM dataset_revision_heads")).scalar_one() == 1


def test_concurrent_publish_rejects_stale_base_and_keeps_one_head(store):
    value, _ = store
    candidates = [prepare(store), prepare(store)]
    for candidate in candidates:
        sign_control_fixture(value, candidate)
    def activate(candidate):
        try:
            value.activate(candidate, expected_base="legacy")
            return True
        except AgentImportError as exc:
            assert exc.code == "REVISION_BASE_CONFLICT"
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(activate, candidates)) == 1


def test_wrong_dataset_or_build_and_changed_asset_are_never_silently_served(store):
    value, candidate = store
    first = prepare(store)
    sign_control_fixture(value, first)
    value.activate(first, expected_base="legacy")
    with pytest.raises(AgentImportError):
        value.resolve("other-dataset", first)
    other_build = RevisionStore(value.engine, value.root, build_sha256="d"*64, signing_key=value.key)
    with pytest.raises(AgentImportError):
        other_build.resolve("same-dataset", first)
    with pytest.raises(AgentImportError):
        with value.projection(first, writable=True):
            pytest.fail("sealed namespace cannot be writable")
    candidate.write_bytes(b"changed test fixture")
    with pytest.raises(AgentImportError):
        value.activate(first, expected_base=first)


def test_product_database_dependency_pins_http_requests_to_sql_revision(store, monkeypatch):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session
    from app.api.deps import get_db
    from app.core import db as database
    from app.core.config import settings
    value, _ = store
    first = prepare(store)
    sign_control_fixture(value, first)
    value.activate(first, expected_base="legacy")
    second = prepare(store)
    with value.projection(second, writable=True) as session:
        session.execute(text("UPDATE identification_matches SET intensity=20"))
    sign_control_fixture(value, second)
    value.activate(second, expected_base=first)
    monkeypatch.setattr(database, "engine", value.engine)
    monkeypatch.setattr(settings, "agent_revision_reads_enabled", True)
    monkeypatch.setattr(settings, "zp_output_root", value.root.parent)
    monkeypatch.setattr(settings, "viewer_build_id", value.build)
    monkeypatch.setattr(settings, "agent_verification_signing_key", value.key.decode())
    app = FastAPI()
    @app.get("/datasets/{slug}/matches/{match_id}")
    def match(slug: str, match_id: int, session: Session = Depends(get_db)):
        return {"intensity": session.execute(text("SELECT intensity FROM identification_matches WHERE match_id=:id"), {"id": match_id}).scalar_one()}
    with TestClient(app) as client:
        response = client.get("/datasets/same-dataset/matches/1")
        assert response.json()["intensity"] == 20
        assert response.headers["x-viewer-revision"] == second
        old = client.get("/datasets/same-dataset/matches/1", headers={"x-viewer-revision": first})
        assert old.json()["intensity"] == 10
        assert old.headers["x-viewer-revision"] == first
        assert client.get("/datasets/other-dataset/matches/1", headers={"x-viewer-revision": first}).status_code == 409
