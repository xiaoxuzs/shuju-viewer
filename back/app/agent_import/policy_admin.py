"""Trusted local test administration. Not mounted as an HTTP grant-issuing API."""
import argparse
import hashlib
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "status"))
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--authorization-id", required=True)
    parser.add_argument("--fixture-grant", type=Path, help="Only a local test-model grant; never for real model access")
    parser.add_argument("--approved-contract", type=Path, help="Finite non-secret contract explicitly approved by the local owner")
    parser.add_argument("--approval-sha256", help="Owner confirmation of that exact canonical contract; not an API credential")
    args = parser.parse_args()
    if os.environ.get("VIEWER_ENV") != "test" or not all(os.environ.get(k) for k in ("DATABASE_URL", "DATA_ROOT")):
        raise SystemExit("Explicit isolated test environment required; production/default DB refused")
    from app.core.config import settings
    from sqlalchemy.engine import make_url
    url = make_url(settings.database_url)
    if url.get_backend_name() == "postgresql" and (url.host not in {"127.0.0.1", "localhost", "::1"} or not (url.database or "").startswith("viewer_test_")):
        raise SystemExit("Only a named isolated local test database is allowed")
    from app.core.db import engine
    from .migrations import ensure_agent_import_schema
    from .authorization_ledger import AuthorizationLedger, canonical, route_identity
    from .admission_policy import ImportPolicy, install_policy
    ensure_agent_import_schema(engine)
    ledger = AuthorizationLedger(engine)
    if args.approved_contract:
        if args.fixture_grant or args.action != "install":
            raise SystemExit("Grant registration must be an explicit single install operation")
        contract = json.loads(args.approved_contract.read_text(encoding="utf-8"))
        digest = hashlib.sha256(canonical(contract).encode()).hexdigest()
        if args.approval_sha256 != digest:
            raise SystemExit("Explicit owner approval of the exact finite contract is required")
        if not settings.openai_api_key or contract.get("route_sha256") != route_identity(settings.openai_base_url.rstrip("/")+"/chat/completions", settings.openai_model):
            raise SystemExit("Approved contract differs from the configured single model connection")
        # This CLI is the trusted owner action, never invoked by Case creation.
        # Idempotent registration cannot replace or reset an existing grant.
        ledger.register(args.authorization_id, contract)
    if args.fixture_grant:
        from urllib.parse import urlsplit
        endpoint = urlsplit(settings.openai_base_url)
        if not settings.agent_test_model_enabled or settings.openai_model != "gpt-test-fixture" or endpoint.hostname not in {"127.0.0.1", "localhost"} or not endpoint.path.endswith("/_test"):
            raise SystemExit("Fixture authority cannot authorize the real GPT gateway")
        ledger.register(args.authorization_id, json.loads(args.fixture_grant.read_text(encoding="utf-8")))
    if args.action == "install":
        if not args.policy:
            raise SystemExit("A finite policy file is required")
        policy = ImportPolicy.model_validate_json(args.policy.read_text(encoding="utf-8"))
        if policy.authorization_id != args.authorization_id:
            raise SystemExit("Policy/grant mismatch")
        install_policy(engine, policy)
    print(json.dumps(ledger.status(args.authorization_id)))
    engine.dispose()


if __name__ == "__main__":
    main()
