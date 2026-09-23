"""Detect repeated deterministic failure without changed candidate/evidence."""
import hashlib

from .source_code import canonical_bytes


def failure_fingerprint(case, code, diagnostics=None):
    strategy = case.strategy_payload or {}
    value = {"code": code, "context_revision": case.context_revision,
        "source": case.dataset_fingerprint, "candidate": case.candidate_payload,
        "source_snapshot": strategy.get("source_snapshot"), "observations": strategy.get("observations"),
        "model_route": strategy.get("model_route_identity"), "diagnostics": diagnostics}
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
