import json

import pytest
from sqlalchemy import create_engine, text

from app.agent_import.asset_retention import DDL, add_reference, dry_run, quarantine_fixture, register_asset
from app.agent_import.input_assets import hash_file


@pytest.mark.parametrize("relative", [".viewer-derived/converted/run.mzML", "input.tsv"])
def test_delivery_retains_real_hidden_source_assets_with_content_check(tmp_path, monkeypatch, relative):
    from types import SimpleNamespace
    from app.agent_import.asset_retention import retain_delivery
    from app.core.config import settings
    monkeypatch.setattr(settings, "zp_output_root", tmp_path)
    source = tmp_path / "agent-cases/case/source/files"
    target = source / relative
    target.parent.mkdir(parents=True)
    target.write_text("source fixture")
    case = SimpleNamespace(case_id="case", candidate_zp_path=None, candidate_zp_sha256=None,
        strategy_payload={"input_snapshot": {"files": {relative: {"sha256": hash_file(target)}}}})
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'retained.sqlite'}")
    with engine.begin() as db:
        for statement in DDL: db.execute(text(statement))
        retain_delivery(db, case)
    assert dry_run(engine)[0]["reference_count"] == 1
    target.write_text("changed")
    with engine.begin() as db, pytest.raises(ValueError, match="content changed"):
        retain_delivery(db, case)
    case.strategy_payload["input_snapshot"]["files"] = {"../escape": {"sha256": "a" * 64}}
    with engine.begin() as db, pytest.raises(ValueError, match="inside"):
        retain_delivery(db, case)


def test_refs_and_hold_prevent_gc_and_only_fixture_can_be_quarantined(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'control.sqlite'}")
    root = tmp_path / "fixture"
    root.mkdir()
    (root / "gc-fixture.json").write_text(json.dumps({"kind": "viewer-gc-synthetic-fixture", "allow_quarantine": True}))
    path = root / "synthetic.txt"
    path.write_text("synthetic fixture only")
    with engine.begin() as db:
        for statement in DDL:
            db.execute(text(statement))
        identity = register_asset(db, path, hash_file(path), kind="synthetic_gc_fixture", owner="fixture:1", legal_hold=False)
    assert dry_run(engine)[0]["reference_count"] == 1
    with pytest.raises(ValueError, match="Referenced"):
        quarantine_fixture(engine, identity, root)
    with engine.begin() as db:
        db.execute(text("DELETE FROM agent_asset_references WHERE owner='fixture:1'"))
        db.execute(text("UPDATE agent_retained_assets SET legal_hold=1"))
    with pytest.raises(ValueError, match="Referenced"):
        quarantine_fixture(engine, identity, root)
    with engine.begin() as db:
        db.execute(text("UPDATE agent_retained_assets SET legal_hold=0"))
    target = quarantine_fixture(engine, identity, root)
    assert target.read_text() == "synthetic fixture only" and not path.exists()
    with engine.begin() as db, pytest.raises(ValueError, match="late reference"):
        add_reference(db, identity, "fixture:late")
    assert dry_run(engine)[0]["state"] == "QUARANTINED"
    engine.dispose()
