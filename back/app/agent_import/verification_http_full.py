"""Real HTTP all-page verification, keyed to a locked PostgreSQL projection."""
from __future__ import annotations
import json
from urllib.parse import urlencode

from app.agent_import.verification_full import FullVerificationError, encoded, record_key, unequal


API_FIELDS = ("source_record_id", "source_run_name", "source_relative_path", "sequence", "modified_sequence", "precursor_mz",
              "precursor_charge", "retention_time", "q_value", "score", "intensity", "is_decoy_match", "protein_accessions", "run_id", "peptide_id")


def reconcile_http(ledger, get_json, prefix, *, page_size=500):
    count = ledger.db.execute("SELECT count(*) FROM projection_ids").fetchone()[0]
    previous_id, observed, page = -1, 0, 1
    while True:
        ledger.check()
        response = get_json(prefix + "/matches?" + urlencode(dict(page=page, page_size=page_size, sort="match_id", order="asc", q_filter="false", decoy="true")))
        if response.get("total") != count or response.get("page") != page or response.get("page_size") != page_size:
            raise FullVerificationError("HTTP_PAGE_SCOPE_CHANGED")
        items = response.get("items")
        if not isinstance(items, list) or len(items) > page_size:
            raise FullVerificationError("HTTP_PAGE_INVALID")
        if not items:
            if observed != count:
                raise FullVerificationError("HTTP_PREMATURE_END")
            break
        for item in items:
            identity = item.get("id")
            if not isinstance(identity, int) or identity <= previous_id:
                raise FullVerificationError("HTTP_ORDER_OR_DUPLICATE_ID")
            previous_id = identity
            projected = ledger.db.execute("SELECT k,body FROM projection_ids WHERE id=?", (identity,)).fetchone()
            if projected is None:
                raise FullVerificationError("HTTP_UNKNOWN_ID")
            key, raw = projected
            expected = json.loads(raw)
            actual = {name: item.get(name) for name in API_FIELDS}
            if isinstance(actual.get("protein_accessions"), list):
                # Associations are order-independent; retain multiplicity so duplicates still fail.
                actual["protein_accessions"] = sorted(actual["protein_accessions"])
            differences = unequal(expected, actual, absolute=0, relative=0)
            ledger.db.execute("INSERT INTO seen VALUES('http',?)", (key,))
            if differences:
                ledger.db.execute("INSERT INTO errors VALUES('http',?,?)", (key, encoded(differences)))
            observed += 1
        ledger.db.commit()
        if ledger.progress:
            ledger.progress("http_matches", observed, count)
        page += 1
        if observed > count:
            raise FullVerificationError("HTTP_EXTRA_ROWS")
    report = ledger.finish("http")
    return {**report, "pages_including_empty_boundary": page, "page_size": page_size,
            "ordering": "match_id ASC unique", "fields": list(API_FIELDS), "association_comparison": "exact unordered multiset; no value or multiplicity tolerance"}


def reconcile_entity_http(ledger, get_json, prefix, entity):
    expected = ledger.db.execute("SELECT count(*) FROM api_entities WHERE kind=?", (entity,)).fetchone()[0]
    observed = 0
    page = 1
    while True:
        ledger.check()
        payload = get_json(prefix + f"/{entity}?page={page}&page_size=500&q_filter=false&decoy=true")
        if payload.get("total") != expected or payload.get("page") != page:
            raise FullVerificationError("HTTP_ENTITY_SCOPE_CHANGED")
        if not payload["items"]:
            break
        for item in payload["items"]:
            row = ledger.db.execute("SELECT body FROM api_entities WHERE kind=? AND id=?", (entity, item["id"])).fetchone()
            if row is None:
                raise FullVerificationError("HTTP_ENTITY_DUPLICATE_OR_UNEXPECTED")
            values = json.loads(row[0])
            if unequal(values, {k: item.get(k) for k in values}, absolute=0, relative=0):
                raise FullVerificationError("HTTP_ENTITY_FIELDS_MISMATCH")
            ledger.db.execute("DELETE FROM api_entities WHERE kind=? AND id=?", (entity, item["id"]))
            observed += 1
        ledger.db.commit()
        if ledger.progress:
            ledger.progress("http_" + entity, observed, expected)
        page += 1
    if observed != expected:
        raise FullVerificationError("HTTP_ENTITY_TRUNCATED")
    return {"coverage": "all_entity_list_pages", "expected": expected, "observed": observed, "pages": page,
            "fields": "identity, sequence/accession, match and association counts"}
