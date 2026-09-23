"""Immutable per-dataset projection namespaces and compare-and-swap heads.

The control rows use the existing business DB. SQLite files/PostgreSQL schemas
contain only projection tables, never a second copy of Case/authorization state.
This module does not grant deployment or bypass trusted candidate verification.
"""
from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import re
import uuid

from sqlalchemy import MetaData, create_engine, inspect, select, text
from sqlalchemy.orm import Session

from .errors import AgentImportError
from .input_assets import hash_file
from .source_code import canonical_bytes

TABLES = ("datasets", "runs", "proteins", "peptides", "proteoforms", "identification_matches", "protein_relation_mapping", "dataset_zp_assets")
DDL = (
    """CREATE TABLE IF NOT EXISTS dataset_revision_heads (
        dataset_id BIGINT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, active_revision_id TEXT NOT NULL,
        generation INTEGER NOT NULL DEFAULT 0, ever_published INTEGER NOT NULL DEFAULT 1)""",
    """CREATE TABLE IF NOT EXISTS dataset_revisions (
        revision_id TEXT PRIMARY KEY, dataset_id BIGINT NOT NULL, slug TEXT NOT NULL,
        base_revision_id TEXT NOT NULL, namespace TEXT NOT NULL UNIQUE, backend TEXT NOT NULL,
        build_sha256 TEXT NOT NULL, source_sha256 TEXT NOT NULL, zp_path TEXT NOT NULL,
        zp_sha256 TEXT NOT NULL, environment_sha256 TEXT NOT NULL, state TEXT NOT NULL,
        projection_sha256 TEXT NULL, receipt_json TEXT NULL)""",
    """CREATE TABLE IF NOT EXISTS dataset_revision_events (
        event_id TEXT PRIMARY KEY, dataset_id BIGINT NOT NULL, kind TEXT NOT NULL,
        from_revision TEXT NOT NULL, to_revision TEXT NOT NULL, generation INTEGER NOT NULL)""",
)


def fail(code, message):
    raise AgentImportError(code, message, status_code=409)


class RevisionStore:
    def __init__(self, engine, root: Path, *, build_sha256: str, signing_key: bytes):
        self.engine, self.root = engine, root.absolute()
        self.build, self.key = build_sha256, signing_key

    def ensure_schema(self):
        with self.engine.begin() as db:
            for statement in DDL:
                db.execute(text(statement))

    def _row(self, revision):
        with self.engine.connect() as db:
            row = db.execute(text("SELECT * FROM dataset_revisions WHERE revision_id=:id"), {"id": revision}).mappings().first()
        if row is None:
            fail("REVISION_NOT_FOUND", "Requested revision does not exist")
        return dict(row)

    def _namespace_path(self, namespace):
        if not re.fullmatch(r"viewer_revision_[0-9a-f]{32}", namespace):
            fail("REVISION_IDENTITY_INVALID", "Invalid projection namespace")
        path = self.root / (namespace + ".sqlite")
        if self.root.resolve() != self.root or path.is_symlink():
            fail("REVISION_IDENTITY_INVALID", "Linked revision storage is forbidden")
        return path

    @contextmanager
    def projection(self, revision, *, writable=False):
        row = self._row(revision)
        if writable and row["state"] != "PREPARING":
            fail("REVISION_IMMUTABLE", "A sealed projection cannot be modified")
        own_engine = None
        if row["backend"] == "sqlite":
            path = self._namespace_path(row["namespace"])
            if not path.is_file():
                fail("REVISION_UNAVAILABLE", "Retained projection is missing")
            url = f"sqlite+pysqlite:///{path.as_posix()}" if writable else f"sqlite+pysqlite:///file:{path.as_posix()}?mode=ro&uri=true"
            own_engine = create_engine(url)
        session = Session(own_engine or self.engine)
        try:
            if row["backend"] == "postgresql":
                self._namespace_path(row["namespace"])  # validate generated identifier
                if not writable:
                    session.execute(text("SET TRANSACTION READ ONLY"))
                session.execute(text('SET LOCAL search_path TO "' + row["namespace"] + '"'))
            else:
                session.execute(text("PRAGMA foreign_keys=ON"))
            session.info["dataset_revision"] = revision
            session.info["logical_dataset_id"] = row["dataset_id"]
            yield session
            if writable:
                session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            if own_engine:
                own_engine.dispose()

    def prepare(self, dataset_id, slug, *, source_sha256, zp_path, environment_sha256, empty_projection=False):
        if len(self.key) < 32 or not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in (self.build, source_sha256, environment_sha256)):
            fail("REVISION_AUTHORITY_REQUIRED", "Explicit build, environment and signing authority are required")
        candidate = Path(zp_path).resolve(strict=True)
        revision = uuid.uuid4().hex
        namespace = "viewer_revision_" + revision
        self.root.mkdir(parents=True, exist_ok=True)
        self._namespace_path(namespace)
        with self.engine.begin() as db:
            original = db.execute(text("SELECT dataset_id FROM datasets WHERE slug=:slug AND dataset_id=:id"), {"slug": slug, "id": dataset_id}).first()
            if original is None:
                fail("REVISION_DATASET_MISMATCH", "A revision belongs to an existing logical dataset")
            db.execute(text("INSERT INTO dataset_revision_heads (dataset_id,slug,active_revision_id) VALUES (:id,:slug,'legacy') ON CONFLICT DO NOTHING"), {"id": dataset_id, "slug": slug})
            head = db.execute(text("SELECT active_revision_id FROM dataset_revision_heads WHERE dataset_id=:id"), {"id": dataset_id}).scalar_one()
            db.execute(text("INSERT INTO dataset_revisions VALUES (:revision,:id,:slug,:base,:namespace,:backend,:build,:source,:path,:zp,:environment,'PREPARING',NULL,NULL)"),
                {"revision": revision, "id": dataset_id, "slug": slug, "base": head, "namespace": namespace, "backend": self.engine.dialect.name,
                 "build": self.build, "source": source_sha256, "path": str(candidate), "zp": hash_file(candidate), "environment": environment_sha256})
        # Projection preparation is an explicit recoverable step, not a cross-FS
        # atomic transaction. A failed clone remains PREPARING and is never active.
        if head == "legacy":
            with Session(self.engine) as source_session:
                self._clone(source_session, revision, namespace, dataset_id, empty=empty_projection)
        else:
            with self.projection(head) as source_session:
                self._clone(source_session, revision, namespace, dataset_id, empty=empty_projection)
        return revision

    def _clone(self, source_session, revision, namespace, dataset_id, *, empty=False):
        origin = MetaData()
        names = set(inspect(source_session.connection()).get_table_names())
        origin.reflect(bind=source_session.connection(), only=[name for name in TABLES if name in names])
        if "datasets" not in origin.tables:
            fail("REVISION_PROJECTION_MISSING", "Source namespace has no dataset projection")
        own_engine = None
        if self.engine.dialect.name == "sqlite":
            path = self._namespace_path(namespace)
            with path.open("xb"):
                pass
            own_engine = create_engine(f"sqlite+pysqlite:///{path.as_posix()}")
        with (own_engine or self.engine).begin() as target:
            schema = None
            if self.engine.dialect.name == "postgresql":
                target.execute(text('CREATE SCHEMA "' + namespace + '"'))
                schema = namespace
            destination = MetaData(schema=schema)
            for table in origin.sorted_tables:
                copied = table.to_metadata(destination, schema=schema, referred_schema_fn=lambda *args: schema)
                for column in copied.columns:
                    if column.primary_key and column.autoincrement in {True, "auto"}:
                        column.server_default = None
            destination.create_all(target)
            for table in origin.sorted_tables:
                if "dataset_id" not in table.c:
                    fail("REVISION_PROJECTION_SCOPE_INVALID", "Projection table lacks dataset scope")
                if empty:
                    continue
                copied = destination.tables[(schema + "." if schema else "") + table.name]
                rows = source_session.execute(select(table).where(table.c.dataset_id == dataset_id)).mappings()
                for batch in rows.partitions(512):
                    if batch:
                        target.execute(copied.insert(), [dict(row) for row in batch])
        if own_engine:
            own_engine.dispose()

    def prepare_from_zp(self, dataset_id, slug, *, source_sha256, zp_path, environment_sha256):
        """Rebuild every projection table from the NEW ZP, preserving dataset ID.

        Never calls the public importer against the live namespace, overwrites
        old data, alters deduplication, or makes a PREPARING revision visible.
        """
        from app.agent_zp.service import (_validate_existing_zp, _semantic_dataset_or_none, _read_zp_runs,
            _insert_dataset_and_runs, _verify_dataset)
        from app.schemas.agent_zp import AgentZpImportCreateIn
        with self.engine.connect() as db:
            original = db.execute(text("SELECT * FROM datasets WHERE dataset_id=:id AND slug=:slug"), {"id": dataset_id, "slug": slug}).mappings().one()
            metadata_fingerprint = original["source_dataset_fingerprint"]
        prepared = _validate_existing_zp(Path(zp_path).resolve(strict=True), case_id="revision-preflight")
        semantic = _semantic_dataset_or_none(prepared.path)
        if semantic is None:
            fail("REVISION_PROJECTION_UNSUPPORTED", "This builder currently requires semantic ZP; nonsemantic data is not silently discarded")
        revision = self.prepare(dataset_id, slug, source_sha256=source_sha256, zp_path=prepared.path,
                                environment_sha256=environment_sha256, empty_projection=True)
        body = AgentZpImportCreateIn(source_path=str(prepared.path), slug=slug, name=original["dataset_name"],
            description=original["description"], analysis_category=original["analysis_mode"], source_profile="verified-revision",
            binary_operation="register_existing_zp", replace_existing=False)
        with self.projection(revision, writable=True) as session:
            imported, runs, _ = _insert_dataset_and_runs(session, body, prepared, _read_zp_runs(prepared.path, semantic=semantic),
                case_id="revision:" + revision, source_fingerprint=metadata_fingerprint, semantic=semantic, logical_dataset_id=dataset_id)
            assert imported == dataset_id
            _verify_dataset(session, dataset_id=dataset_id, run_ids=runs, validation_mode=prepared.validation_mode, semantic=semantic)
            session.execute(text("UPDATE datasets SET status='READY' WHERE dataset_id=:id"), {"id": dataset_id})
            session.execute(text("UPDATE runs SET status='READY' WHERE dataset_id=:id"), {"id": dataset_id})
        if hash_file(prepared.path) != self._row(revision)["zp_sha256"]:
            fail("REVISION_EVIDENCE_STALE", "Candidate changed during projection")
        return revision

    def projection_digest(self, revision):
        digest = hashlib.sha256()
        with self.projection(revision) as session:
            metadata = MetaData()
            names = set(inspect(session.connection()).get_table_names())
            metadata.reflect(bind=session.connection(), only=[name for name in TABLES if name in names])
            for name in sorted(metadata.tables):
                table = metadata.tables[name]
                digest.update(name.encode())
                columns = list(table.primary_key.columns)
                if not columns:
                    fail("REVISION_PROJECTION_SCOPE_INVALID", "Every projection table needs a stable primary key")
                for row in session.execute(select(table).order_by(*columns)).mappings():
                    digest.update(json.dumps(dict(row), sort_keys=True, separators=(",", ":"), default=str).encode())
        return digest.hexdigest()

    def seal(self, revision, application_receipt, *, projection_receipt):
        from .verification import verify_receipt
        row = self._row(revision)
        if row["state"] != "PREPARING":
            fail("REVISION_IMMUTABLE", "Revision has already been sealed")
        # A candidate's unrelated validation DB is insufficient: a trusted
        # verifier must attest this exact namespace after source reconciliation.
        expected = {"revision_id": revision, "dataset_id": row["dataset_id"],
            "projection_sha256": self.projection_digest(revision), "zp_sha256": row["zp_sha256"],
            "source_sha256": row["source_sha256"], "build_sha256": row["build_sha256"],
            "environment_sha256": row["environment_sha256"], "status": "PASSED"}
        if projection_receipt.get("record") != expected or not hmac.compare_digest(projection_receipt.get("signature", ""), hmac.new(self.key, canonical_bytes(expected), hashlib.sha256).hexdigest()):
            fail("REVISION_PROJECTION_VALIDATION_REQUIRED", "The actual revision namespace needs independent signed source reconciliation")
        verify_receipt(application_receipt, self.key, code_sha256=row["build_sha256"], candidate_sha256=row["zp_sha256"], source_sha256=row["source_sha256"])
        with self.projection(revision) as session:
            identity = session.execute(text("SELECT dataset_id,slug FROM datasets")).all()
            if identity != [(row["dataset_id"], row["slug"])]:
                fail("REVISION_DATASET_MISMATCH", "Projection changed logical dataset identity")
        record = {"revision_id": revision, "dataset_id": row["dataset_id"], "projection_sha256": self.projection_digest(revision),
            "build_sha256": row["build_sha256"], "environment_sha256": row["environment_sha256"],
            "zp_sha256": hash_file(Path(row["zp_path"])), "application_receipt_sha256": hashlib.sha256(canonical_bytes(application_receipt)).hexdigest()}
        if record["zp_sha256"] != row["zp_sha256"]:
            fail("REVISION_EVIDENCE_STALE", "Candidate ZP changed")
        evidence = {"record": record, "signature": hmac.new(self.key, canonical_bytes(record), hashlib.sha256).hexdigest()}
        with self.engine.begin() as db:
            db.execute(text("UPDATE dataset_revisions SET state='VALIDATED',projection_sha256=:sha,receipt_json=:receipt WHERE revision_id=:id AND state='PREPARING'"),
                       {"id": revision, "sha": record["projection_sha256"], "receipt": json.dumps(evidence)})
        return evidence

    def activate(self, revision, *, expected_base, rollback=False):
        row = self._row(revision)
        if row["state"] not in {"VALIDATED", "ACTIVE", "RETIRED"} or row["build_sha256"] != self.build:
            fail("REVISION_BUILD_UNAVAILABLE", "Verified compatible running build required; no fake activation")
        receipt = json.loads(row["receipt_json"] or "{}")
        record = receipt.get("record", {})
        if not hmac.compare_digest(receipt.get("signature", ""), hmac.new(self.key, canonical_bytes(record), hashlib.sha256).hexdigest()) or self.projection_digest(revision) != row["projection_sha256"] or hash_file(Path(row["zp_path"])) != row["zp_sha256"]:
            fail("REVISION_EVIDENCE_STALE", "Immutable projection, ZP or receipt changed")
        with self.engine.begin() as db:
            result = db.execute(text("UPDATE dataset_revision_heads SET active_revision_id=:new,generation=generation+1 WHERE dataset_id=:id AND active_revision_id=:base"),
                                {"new": revision, "id": row["dataset_id"], "base": expected_base})
            if result.rowcount != 1:
                fail("REVISION_BASE_CONFLICT", "Another revision was published; rebase explicitly")
            db.execute(text("UPDATE dataset_revisions SET state='RETIRED' WHERE dataset_id=:id AND state='ACTIVE'"), {"id": row["dataset_id"]})
            db.execute(text("UPDATE dataset_revisions SET state='ACTIVE' WHERE revision_id=:id"), {"id": revision})
            generation = db.execute(text("SELECT generation FROM dataset_revision_heads WHERE dataset_id=:id"), {"id": row["dataset_id"]}).scalar_one()
            db.execute(text("INSERT INTO dataset_revision_events VALUES (:event,:dataset,:kind,:base,:new,:generation)"),
                {"event": uuid.uuid4().hex, "dataset": row["dataset_id"], "kind": "ROLLBACK" if rollback else "PUBLISH", "base": expected_base, "new": revision, "generation": generation})

    def resolve(self, slug, requested=None):
        with self.engine.connect() as db:
            head = db.execute(text("SELECT * FROM dataset_revision_heads WHERE slug=:slug"), {"slug": slug}).mappings().first()
        selected = requested or (head["active_revision_id"] if head else "legacy")
        if selected == "legacy":
            return None
        row = self._row(selected)
        if row["slug"] != slug or row["state"] not in {"ACTIVE", "RETIRED"}:
            fail("REVISION_NOT_READABLE", "Revision does not belong to this dataset or is not ready")
        if row["build_sha256"] != self.build:
            fail("REVISION_BUILD_UNAVAILABLE", "This process cannot serve that revision build")
        return selected
