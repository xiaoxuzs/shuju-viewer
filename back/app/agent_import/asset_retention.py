"""Reference-aware retention. Unknown/historical files are never GC candidates.

Production assets default to legal hold. This version only exposes dry-run;
recoverable filesystem mutation is restricted to explicitly marked test fixtures.
"""
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import text

from .input_assets import hash_file
from .source_code import _linked

DDL = (
    """CREATE TABLE IF NOT EXISTS agent_retained_assets (
        asset_id TEXT PRIMARY KEY,path TEXT NOT NULL UNIQUE,content_sha256 TEXT NOT NULL,
        kind TEXT NOT NULL,legal_hold INTEGER NOT NULL DEFAULT 1,state TEXT NOT NULL DEFAULT 'LIVE',serial INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS agent_asset_references (
        asset_id TEXT NOT NULL REFERENCES agent_retained_assets(asset_id),owner TEXT NOT NULL,
        PRIMARY KEY(asset_id,owner))""",
)


def register_asset(db, path, content_sha256, *, kind, owner, legal_hold=True):
    path = str(Path(path).absolute())
    identity = hashlib.sha256((path + "\0" + content_sha256).encode()).hexdigest()
    db.execute(text("INSERT INTO agent_retained_assets (asset_id,path,content_sha256,kind,legal_hold) VALUES (:id,:path,:sha,:kind,:hold) ON CONFLICT DO NOTHING"),
               {"id": identity, "path": path, "sha": content_sha256, "kind": kind, "hold": int(legal_hold)})
    add_reference(db, identity, owner)
    return identity


def add_reference(db, asset_id, owner):
    updated = db.execute(text("UPDATE agent_retained_assets SET serial=serial+1 WHERE asset_id=:id AND state='LIVE'"), {"id": asset_id})
    if updated.rowcount != 1:
        raise ValueError("Asset is missing or undergoing collection; cannot attach a late reference")
    db.execute(text("INSERT INTO agent_asset_references VALUES (:id,:owner) ON CONFLICT DO NOTHING"), {"id": asset_id, "owner": owner})


def retain_delivery(db, case):
    from app.core.config import settings
    if case.candidate_zp_path and case.candidate_zp_sha256:
        register_asset(db, case.candidate_zp_path, case.candidate_zp_sha256, kind="candidate_zp", owner="case:" + case.case_id)
    snapshot = (case.strategy_payload or {}).get("input_snapshot") or {}
    for relative, entry in snapshot.get("files", {}).items():
        from app.source_inspection.paths import CasePathResolver
        root = settings.resolved_zp_output_root / "agent-cases" / case.case_id / "source/files"
        path = CasePathResolver(root).resolve_file(relative)
        if hash_file(path) != entry["sha256"]:
            raise ValueError("Retained source content changed before publication")
        register_asset(db, path, entry["sha256"], kind="source", owner="case:" + case.case_id)


def dry_run(engine):
    with engine.connect() as db:
        return [dict(row) for row in db.execute(text("""SELECT a.asset_id,a.kind,a.legal_hold,a.state,count(r.owner) AS reference_count
            FROM agent_retained_assets a LEFT JOIN agent_asset_references r ON r.asset_id=a.asset_id
            GROUP BY a.asset_id,a.kind,a.legal_hold,a.state ORDER BY a.asset_id""")).mappings()]


def quarantine_fixture(engine, asset_id, fixture_root):
    """Only synthetic GC test fixtures; no production/historical cleanup API."""
    root = Path(fixture_root).absolute()
    if any(_linked(p) for p in (root, *root.parents)):
        raise ValueError("Linked fixture root")
    marker = json.loads((root / "gc-fixture.json").read_text(encoding="utf-8"))
    if marker != {"kind": "viewer-gc-synthetic-fixture", "allow_quarantine": True}:
        raise ValueError("Only a declared synthetic GC fixture is mutable")
    with engine.begin() as db:
        db.execute(text("UPDATE agent_retained_assets SET serial=serial+1 WHERE asset_id=:id"), {"id": asset_id})
        row = db.execute(text("SELECT * FROM agent_retained_assets WHERE asset_id=:id"), {"id": asset_id}).mappings().one()
        refs = db.execute(text("SELECT count(*) FROM agent_asset_references WHERE asset_id=:id"), {"id": asset_id}).scalar_one()
        path = Path(row["path"])
        if row["legal_hold"] or refs or row["state"] != "LIVE" or row["kind"] != "synthetic_gc_fixture":
            raise ValueError("Referenced, held or historical assets cannot be collected")
        if not path.is_relative_to(root) or any(_linked(p) for p in (path, *path.parents)):
            raise ValueError("Asset escaped the synthetic fixture root")
        target = root / "quarantine" / asset_id
        target.parent.mkdir(exist_ok=True)
        if target.exists():
            raise ValueError("Prior quarantine needs reconciliation; never overwrite")
        if hash_file(path) != row["content_sha256"]:
            raise ValueError("Asset content changed")
        os.replace(path, target)  # recoverable; no unlink of user data
        db.execute(text("UPDATE agent_retained_assets SET state='QUARANTINED' WHERE asset_id=:id"), {"id": asset_id})
    return target
