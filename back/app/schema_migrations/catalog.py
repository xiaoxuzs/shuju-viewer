from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import SchemaStateError
from .sql import normalize_catalog_sql


CATALOG_COLLECTIONS = (
    "relations",
    "columns",
    "constraints",
    "indexes",
    "sequences",
    "functions",
    "triggers",
)
EXPECTED_EXCLUDED_DIMENSIONS = (
    "acl_grant",
    "audit_time",
    "comment",
    "database_name",
    "oid",
    "owner",
    "physical_file_location",
    "relation_size",
    "sequence_current_value",
    "statistics",
)

_FIELDS: dict[str, tuple[str, ...]] = {
    "relations": ("name", "relkind", "relpersistence", "is_partition"),
    "columns": (
        "relation",
        "ordinal_position",
        "name",
        "format_type",
        "not_null",
        "default",
        "identity",
        "generated",
    ),
    "constraints": (
        "relation",
        "name",
        "contype",
        "deferrable",
        "deferred",
        "validated",
        "definition",
    ),
    "indexes": (
        "relation",
        "name",
        "unique",
        "primary",
        "valid",
        "ready",
        "method",
        "definition",
        "predicate",
    ),
    "sequences": (
        "name",
        "data_type",
        "start",
        "min",
        "max",
        "increment",
        "cycle",
        "owned_by_relation",
        "owned_by_column",
    ),
    "functions": (
        "name",
        "kind",
        "identity_arguments",
        "return_type",
        "volatile",
        "security_definer",
        "language",
        "definition",
    ),
    "triggers": ("relation", "name", "enabled", "definition"),
}

_SORT_KEYS: dict[str, tuple[str, ...]] = {
    "relations": ("name",),
    "columns": ("relation", "ordinal_position"),
    "constraints": ("relation", "name"),
    "indexes": ("relation", "name"),
    "sequences": ("name",),
    "functions": ("name", "identity_arguments"),
    "triggers": ("relation", "name"),
}

_IDENTITY_KEYS = _SORT_KEYS


RELATIONS_SQL = """
SELECT c.relname, c.relkind, c.relpersistence, c.relispartition
FROM pg_catalog.pg_class AS c
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = %s
  AND c.relkind NOT IN ('i', 'I', 'c', 't')
ORDER BY c.relname
"""

COLUMNS_SQL = """
SELECT c.relname, a.attnum, a.attname,
       pg_catalog.format_type(a.atttypid, a.atttypmod),
       a.attnotnull,
       pg_catalog.pg_get_expr(ad.adbin, ad.adrelid),
       a.attidentity, a.attgenerated
FROM pg_catalog.pg_attribute AS a
JOIN pg_catalog.pg_class AS c ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
LEFT JOIN pg_catalog.pg_attrdef AS ad
       ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
WHERE n.nspname = %s
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY c.relname, a.attnum
"""

CONSTRAINTS_SQL = """
SELECT c.relname, con.conname, con.contype, con.condeferrable,
       con.condeferred, con.convalidated,
       pg_catalog.pg_get_constraintdef(con.oid, false)
FROM pg_catalog.pg_constraint AS con
JOIN pg_catalog.pg_class AS c ON c.oid = con.conrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = %s
ORDER BY c.relname, con.conname
"""

INDEXES_SQL = """
SELECT table_class.relname, index_class.relname,
       idx.indisunique, idx.indisprimary, idx.indisvalid, idx.indisready,
       am.amname,
       pg_catalog.pg_get_indexdef(idx.indexrelid, 0, false),
       pg_catalog.pg_get_expr(idx.indpred, idx.indrelid, false)
FROM pg_catalog.pg_index AS idx
JOIN pg_catalog.pg_class AS table_class ON table_class.oid = idx.indrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = table_class.relnamespace
JOIN pg_catalog.pg_class AS index_class ON index_class.oid = idx.indexrelid
JOIN pg_catalog.pg_am AS am ON am.oid = index_class.relam
WHERE n.nspname = %s
ORDER BY table_class.relname, index_class.relname
"""

SEQUENCES_SQL = """
SELECT sequence_class.relname,
       pg_catalog.format_type(seq.seqtypid, NULL),
       seq.seqstart, seq.seqmin, seq.seqmax, seq.seqincrement, seq.seqcycle,
       owned_table.relname, owned_attribute.attname
FROM pg_catalog.pg_sequence AS seq
JOIN pg_catalog.pg_class AS sequence_class ON sequence_class.oid = seq.seqrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = sequence_class.relnamespace
LEFT JOIN pg_catalog.pg_depend AS dep
       ON dep.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
      AND dep.objid = sequence_class.oid
      AND dep.objsubid = 0
      AND dep.refclassid = 'pg_catalog.pg_class'::pg_catalog.regclass
      AND dep.deptype IN ('a', 'i')
LEFT JOIN pg_catalog.pg_class AS owned_table ON owned_table.oid = dep.refobjid
LEFT JOIN pg_catalog.pg_attribute AS owned_attribute
       ON owned_attribute.attrelid = dep.refobjid
      AND owned_attribute.attnum = dep.refobjsubid
WHERE n.nspname = %s
ORDER BY sequence_class.relname
"""

FUNCTIONS_SQL = """
SELECT p.proname, p.prokind,
       pg_catalog.pg_get_function_identity_arguments(p.oid),
       pg_catalog.pg_get_function_result(p.oid),
       p.provolatile, p.prosecdef, language.lanname,
       pg_catalog.pg_get_functiondef(p.oid)
FROM pg_catalog.pg_proc AS p
JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
JOIN pg_catalog.pg_language AS language ON language.oid = p.prolang
WHERE n.nspname = %s
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend AS dep
      WHERE dep.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass
        AND dep.objid = p.oid
        AND dep.deptype = 'e'
  )
ORDER BY p.proname, pg_catalog.pg_get_function_identity_arguments(p.oid)
"""

TRIGGERS_SQL = """
SELECT c.relname, trigger.tgname, trigger.tgenabled,
       pg_catalog.pg_get_triggerdef(trigger.oid, false)
FROM pg_catalog.pg_trigger AS trigger
JOIN pg_catalog.pg_class AS c ON c.oid = trigger.tgrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = %s
  AND NOT trigger.tgisinternal
ORDER BY c.relname, trigger.tgname
"""


def _row_dicts(rows: Iterable[Sequence[Any]], fields: Sequence[str]) -> list[dict[str, Any]]:
    return [dict(zip(fields, row, strict=True)) for row in rows]


def _normalize_collection(name: str, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    expected_fields = _FIELDS[name]
    normalized: list[dict[str, Any]] = []
    for source in rows:
        if set(source) != set(expected_fields):
            raise SchemaStateError(f"catalog {name} entry has unexpected fields")
        entry = {field: source[field] for field in expected_fields}
        for field in ("default", "definition", "predicate"):
            if field in entry:
                entry[field] = normalize_catalog_sql(entry[field])
        normalized.append(entry)
    normalized.sort(key=lambda entry: tuple(entry[field] for field in _SORT_KEYS[name]))
    return normalized


def canonicalize_catalog(catalog: Mapping[str, Any]) -> dict[str, Any]:
    if catalog.get("schema_name") != "public":
        raise SchemaStateError("only the public schema is supported")
    result: dict[str, Any] = {"schema_name": "public"}
    for name in CATALOG_COLLECTIONS:
        rows = catalog.get(name)
        if not isinstance(rows, list):
            raise SchemaStateError(f"catalog collection is missing or invalid: {name}")
        result[name] = _normalize_collection(name, rows)
    return result


def collect_catalog_in_transaction(connection: Any, *, schema_name: str = "public") -> dict[str, Any]:
    if schema_name != "public":
        raise SchemaStateError("only the public schema is supported")

    relations = _row_dicts(connection.execute(RELATIONS_SQL, (schema_name,)).fetchall(), _FIELDS["relations"])
    allowed_relkinds = {"r", "p", "v", "m", "S", "f"}
    unknown = sorted({row["relkind"] for row in relations} - allowed_relkinds)
    if unknown:
        raise SchemaStateError(f"unrecognized public relation kinds: {unknown}")

    raw: dict[str, Any] = {
        "schema_name": schema_name,
        "relations": relations,
        "columns": _row_dicts(
            connection.execute(COLUMNS_SQL, (schema_name,)).fetchall(), _FIELDS["columns"]
        ),
        "constraints": _row_dicts(
            connection.execute(CONSTRAINTS_SQL, (schema_name,)).fetchall(), _FIELDS["constraints"]
        ),
        "indexes": _row_dicts(connection.execute(INDEXES_SQL, (schema_name,)).fetchall(), _FIELDS["indexes"]),
        "sequences": _row_dicts(
            connection.execute(SEQUENCES_SQL, (schema_name,)).fetchall(), _FIELDS["sequences"]
        ),
        "functions": _row_dicts(
            connection.execute(FUNCTIONS_SQL, (schema_name,)).fetchall(), _FIELDS["functions"]
        ),
        "triggers": _row_dicts(
            connection.execute(TRIGGERS_SQL, (schema_name,)).fetchall(), _FIELDS["triggers"]
        ),
    }
    return canonicalize_catalog(raw)


def collect_catalog(connection: Any, *, schema_name: str = "public") -> dict[str, Any]:
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return collect_catalog_in_transaction(connection, schema_name=schema_name)


def _validate_canonical_json(path: Path, data: Mapping[str, Any], raw: bytes) -> None:
    canonical = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    normalized_raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if normalized_raw != canonical:
        raise SchemaStateError(f"legacy baseline JSON is not in canonical stable-key order: {path.name}")


def load_legacy_baseline(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise SchemaStateError("legacy baseline JSON must not contain a UTF-8 BOM")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchemaStateError("legacy baseline JSON is not valid canonical UTF-8 JSON") from exc
    if not isinstance(data, dict):
        raise SchemaStateError("legacy baseline JSON root must be an object")
    _validate_canonical_json(path, data, raw)

    fixed = {
        "format_version": 1,
        "baseline_id": "legacy_baseline_v1",
        "schema_name": "public",
        "postgres_major_version": 16,
    }
    for key, expected in fixed.items():
        if data.get(key) != expected:
            raise SchemaStateError(f"legacy baseline has invalid {key}")
    if tuple(data.get("excluded_dimensions", ())) != EXPECTED_EXCLUDED_DIMENSIONS:
        raise SchemaStateError("legacy baseline excluded_dimensions is incomplete or unstable")

    catalog = canonicalize_catalog(data)
    expected_counts = {
        "tables": 8,
        "columns": 91,
        "constraints": 26,
        "indexes": 31,
        "sequences": 7,
        "functions": 0,
        "triggers": 0,
    }
    actual_counts = {
        "tables": sum(row["relkind"] in {"r", "p"} for row in catalog["relations"]),
        **{name: len(catalog[name]) for name in expected_counts if name != "tables"},
    }
    if data.get("object_counts") != expected_counts or actual_counts != expected_counts:
        raise SchemaStateError(
            f"legacy baseline object counts are invalid: expected {expected_counts}, found {actual_counts}"
        )

    audit = data.get("audit_source")
    if not isinstance(audit, dict):
        raise SchemaStateError("legacy baseline audit_source is missing")
    required_audit = {
        "schema_source": "docs/universal_schema.sql",
        "production_postgres_version_num": 160014,
        "production_schema_dump_sha256": "0b43d1b94e9c751a03d1ea4e793f55269f242059ae2717f79eb1faedf6b4eebb",
        "production_catalog_result": "MATCH",
    }
    for key, expected in required_audit.items():
        if audit.get(key) != expected:
            raise SchemaStateError(f"legacy baseline audit_source has invalid {key}")
    return data


def baseline_catalog(baseline: Mapping[str, Any]) -> dict[str, Any]:
    return canonicalize_catalog(baseline)


def _identity(collection: str, entry: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(entry[key] for key in _IDENTITY_KEYS[collection])


def _brief(value: Any, *, limit: int = 160) -> str:
    rendered = repr(value)
    return rendered if len(rendered) <= limit else f"{rendered[: limit - 3]}..."


def catalog_differences(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    *,
    limit: int = 12,
) -> tuple[str, ...]:
    differences: list[str] = []

    def add(message: str) -> None:
        if len(differences) < limit:
            differences.append(message)

    if expected.get("schema_name") != actual.get("schema_name"):
        add("schema_name differs")
    for collection in CATALOG_COLLECTIONS:
        expected_by_id = {_identity(collection, row): row for row in expected[collection]}
        actual_by_id = {_identity(collection, row): row for row in actual[collection]}
        for identity in sorted(expected_by_id.keys() - actual_by_id.keys()):
            add(f"{collection}{identity} is missing")
        for identity in sorted(actual_by_id.keys() - expected_by_id.keys()):
            add(f"{collection}{identity} is unexpected")
        for identity in sorted(expected_by_id.keys() & actual_by_id.keys()):
            expected_entry = expected_by_id[identity]
            actual_entry = actual_by_id[identity]
            for field in _FIELDS[collection]:
                if expected_entry[field] != actual_entry[field]:
                    add(
                        f"{collection}{identity}.{field} differs: "
                        f"expected={_brief(expected_entry[field])} actual={_brief(actual_entry[field])}"
                    )
    if len(differences) == limit:
        differences.append("additional catalog differences were omitted")
    return tuple(differences)


def catalog_is_empty(catalog: Mapping[str, Any]) -> bool:
    return all(not catalog[name] for name in CATALOG_COLLECTIONS)
