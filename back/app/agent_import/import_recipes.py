"""Versioned default-import recipes, derived only from published data plans."""
from copy import deepcopy
import json
from pathlib import Path
import uuid

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from .contracts import AgentCandidatePlan, AgentPlanReview
from .errors import AgentImportError
from .source_code import canonical_bytes, digest_bytes


DDL = (
    """CREATE TABLE IF NOT EXISTS agent_import_recipes (
        recipe_id TEXT PRIMARY KEY, name TEXT NOT NULL, analysis_category TEXT NOT NULL,
        display_category TEXT NOT NULL, active_version INTEGER NOT NULL, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS agent_import_recipe_versions (
        recipe_id TEXT NOT NULL REFERENCES agent_import_recipes(recipe_id), version INTEGER NOT NULL,
        parent_case_id TEXT NOT NULL REFERENCES agent_import_cases(case_id), maintenance_task_id TEXT NULL,
        candidate_json TEXT NOT NULL, candidate_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(recipe_id,version))""",
    """CREATE TABLE IF NOT EXISTS agent_case_recipes (
        case_id TEXT PRIMARY KEY REFERENCES agent_import_cases(case_id),
        recipe_id TEXT NOT NULL, version INTEGER NOT NULL,
        FOREIGN KEY(recipe_id,version) REFERENCES agent_import_recipe_versions(recipe_id,version))""",
)


class SaveRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    recipe_id: str | None = None
    expected_version: int | None = Field(default=None, ge=1)
    maintenance_task_id: str | None = None


def _ready_plan(payload):
    plan = AgentCandidatePlan.model_validate(payload)
    if plan.status != "READY" or plan.zp_conversion_plan.declarative_plan is None:
        raise AgentImportError("IMPORT_RECIPE_UNSUPPORTED", "This delivery has no reusable declarative import plan.", status_code=409)
    return plan


def save_recipe(service, case_id, body):
    from .case_service import _now
    name = body.name.strip()
    if not name:
        raise AgentImportError("IMPORT_RECIPE_NAME_REQUIRED", "Enter an import format name.", status_code=422)
    case = service.get_case(case_id)
    if not case.ever_published or case.dataset_id is None:
        raise AgentImportError("IMPORT_RECIPE_REQUIRES_DELIVERY", "Save a default import after its dataset has been published.", status_code=409)
    payload = case.candidate_payload
    with service.engine.begin() as db:
        selected_task_id = body.maintenance_task_id
        if selected_task_id is None:
            selected_task_id = db.execute(text("""SELECT t.task_id FROM agent_maintenance_tasks t
                JOIN dataset_revision_heads h ON h.active_revision_id=t.published_revision_id AND h.dataset_id=t.dataset_id
                WHERE t.parent_case_id=:case AND t.state='PUBLISHED'"""), {"case": case_id}).scalar()
        if selected_task_id:
            task = db.execute(text("SELECT * FROM agent_maintenance_tasks WHERE task_id=:id AND parent_case_id=:case AND state='PUBLISHED'"),
                              {"id": selected_task_id, "case": case_id}).mappings().first()
            if task is None:
                raise AgentImportError("IMPORT_RECIPE_REQUIRES_DELIVERY", "The repair must be published before updating a default import.", status_code=409)
            payload = json.loads(task["candidate_json"])
        plan = _ready_plan(payload)
        encoded = plan.model_dump_json()
        digest = digest_bytes(canonical_bytes(plan.model_dump(mode="json")))
        category = plan.physical_analysis_mode
        declarative = plan.zp_conversion_plan.declarative_plan
        display = "DDA" if declarative.acquisition_mode == "dda" else category
        recipe_id = body.recipe_id or str(uuid.uuid4())
        if body.recipe_id:
            prior = db.execute(text("SELECT * FROM agent_import_recipes WHERE recipe_id=:id"), {"id": recipe_id}).mappings().first()
            if prior is None or prior["analysis_category"] != plan.analysis_category or prior["display_category"] != display:
                raise AgentImportError("IMPORT_RECIPE_CONFLICT", "The saved format has a different category.", status_code=409)
            version = prior["active_version"] + 1
            changed = db.execute(text("UPDATE agent_import_recipes SET active_version=:version,name=:name WHERE recipe_id=:id AND active_version=:base"),
                                 {"version": version, "name": name, "id": recipe_id, "base": body.expected_version})
            if changed.rowcount != 1:
                raise AgentImportError("IMPORT_RECIPE_CONFLICT", "The default import changed; reload its current version.", status_code=409)
        else:
            # Repeated clicks for the same delivery and name reuse its existing version.
            prior = db.execute(text("""SELECT r.recipe_id FROM agent_import_recipes r
                JOIN agent_import_recipe_versions v ON v.recipe_id=r.recipe_id AND v.version=r.active_version
                WHERE r.name=:name AND v.parent_case_id=:case AND v.candidate_sha256=:sha"""),
                {"name": name, "case": case_id, "sha": digest}).scalar()
            if prior:
                return get_recipe_tx(db, prior)
            version = 1
            db.execute(text("INSERT INTO agent_import_recipes VALUES (:id,:name,:category,:display,1,:now)"),
                       {"id": recipe_id, "name": name, "category": plan.analysis_category, "display": display, "now": _now()})
        db.execute(text("INSERT INTO agent_import_recipe_versions VALUES (:id,:version,:case,:task,:candidate,:sha,:now)"),
                   {"id": recipe_id, "version": version, "case": case_id, "task": selected_task_id,
                    "candidate": encoded, "sha": digest, "now": _now()})
        return get_recipe_tx(db, recipe_id)


def get_recipe_tx(db, recipe_id, version=None):
    row = db.execute(text("""SELECT r.*,v.version,v.parent_case_id,v.maintenance_task_id,v.candidate_json,v.candidate_sha256
        FROM agent_import_recipes r JOIN agent_import_recipe_versions v ON v.recipe_id=r.recipe_id
        WHERE r.recipe_id=:id AND v.version=COALESCE(:version,r.active_version)"""), {"id": recipe_id, "version": version}).mappings().first()
    if row is None:
        raise AgentImportError("IMPORT_RECIPE_NOT_FOUND", "Saved import format not found.", status_code=404)
    return dict(row)


def recipe_out(row):
    return {key: row[key] for key in ("recipe_id", "name", "analysis_category", "display_category", "version", "parent_case_id")}


def list_recipes(service):
    with service.engine.connect() as db:
        ids = db.execute(text("SELECT recipe_id FROM agent_import_recipes ORDER BY display_category,name,recipe_id")).scalars().all()
        return [recipe_out(get_recipe_tx(db, item)) for item in ids]


def bound_recipe(service, case_id):
    with service.engine.connect() as db:
        bound = db.execute(text("SELECT recipe_id,version FROM agent_case_recipes WHERE case_id=:id"), {"id": case_id}).mappings().first()
        return get_recipe_tx(db, bound["recipe_id"], bound["version"]) if bound else None


def build_recipe_strategy(recipe, source_root):
    """Inspect this source afresh; never reuse another dataset's observations."""
    from .research_tools import AgentResearchToolbox
    from .mapping_preflight import preflight_mapping_plan
    from .workflow import _trusted_observations
    from app.source_inspection import InventoryService

    candidate = deepcopy(json.loads(recipe["candidate_json"]))
    if digest_bytes(canonical_bytes(candidate)) != recipe["candidate_sha256"]:
        raise AgentImportError("IMPORT_RECIPE_CHANGED", "Saved import plan changed.", status_code=409)
    plan = candidate["zp_conversion_plan"]["declarative_plan"]
    root = Path(source_root).resolve(strict=True)
    # Tables keep exact names; uniquely identifiable companion filenames may vary.
    inventory = InventoryService(root)
    files, cursor = [], None
    while True:
        page = inventory.list_files(limit=1000, cursor=cursor)
        files.extend(item.relative_path for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    renamed = {}
    for source in plan["sources"]:
        old = source["relative_path"]
        if not (root / old).is_file() and source["reader"] in {"mzml", "fasta"}:
            suffixes = {".mzml"} if source["reader"] == "mzml" else {".fasta", ".fa"}
            matches = [path for path in files if Path(path).suffix.casefold() in suffixes]
            if len(matches) == 1:
                source["relative_path"] = renamed[old] = matches[0]
    toolbox = AgentResearchToolbox(root)
    observations = []
    refs = {}
    for index, source in enumerate(plan["sources"]):
        path = source["relative_path"]
        if not (root / path).exists() and not source["required"]:
            continue
        call_id = f"recipe-source-{index}"
        payload = toolbox.execute("inspect_source_file", {"relative_path": path, "max_fields": 256})
        refs[source["source_id"]] = call_id
        observations.append({"call_id": call_id, "payload": payload, "result_sha256": digest_bytes(canonical_bytes(payload))})
        if source["accession_rule_evidence_refs"]:
            source["accession_rule_evidence_refs"] = [call_id]
    for item in plan["field_mappings"]:
        item["evidence_refs"] = [refs[item["source_id"]]]
    for item in plan["join_rules"]:
        item["evidence_refs"] = [refs[item["left_source_id"]], refs[item["right_source_id"]]]
    for item in plan["requested_views"]:
        item["evidence_refs"] = []
    if plan["acquisition_mode"]:
        plan["acquisition_mode_evidence_refs"] = list(refs.values())
    # Dispositions describe original assets; rebuild only for files actually present.
    dispositions = []
    for index, item in enumerate(plan["asset_dispositions"]):
        if item["relative_path"] not in files:
            continue
        call_id = f"recipe-asset-{index}"
        payload = toolbox.execute("inspect_source_file", {"relative_path": item["relative_path"]})
        observations.append({"call_id": call_id, "payload": payload, "result_sha256": digest_bytes(canonical_bytes(payload))})
        item["evidence_refs"] = [call_id]
        dispositions.append(item)
    plan["asset_dispositions"] = dispositions
    candidate["zp_conversion_plan"]["relative_source"] = renamed.get(candidate["zp_conversion_plan"]["relative_source"], candidate["zp_conversion_plan"]["relative_source"])
    rebound = _ready_plan(candidate)
    strategy = {"provider": "saved-import-recipe", "import_recipe": recipe_out(recipe), "observations": observations,
                "saved_candidate": rebound.model_dump(mode="json")}
    from app.core.config import settings
    from .source_code import SourceSnapshot
    strategy["source_snapshot"] = {"sha256": SourceSnapshot.capture(settings.agent_source_root).identity}
    preflight_mapping_plan(source_root=root, plan=rebound, allow_legacy_mapping=False, trusted_observations=_trusted_observations(strategy))
    return strategy


def recipe_review():
    return AgentPlanReview(status="APPROVED", evidence=["Versioned default-import plan; fresh source evidence and deterministic preflight passed."])
