from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, is_dataclass
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from .blocks import ExtensionBlock
from .exceptions import ZpReadError, ZpWriteError
from .serialization import canonical_json_bytes, parse_json_bytes, to_primitive


V3_EXTENSIONS_ENCODING = "zp-extensions-v3"

_HEADER = struct.Struct("<8sHBBIQQQ24s")
_MAGIC = b"ZPEXTV3\0"
_VERSION = 3
_ENDIANNESS_LITTLE = 1
_RESERVED_KEY = "__zp_v3_table__"
_KIND_KEY = "__zp_v3_kind__"
_MIN_TABLE_ROWS = 64


@dataclass(frozen=True, slots=True)
class EncodedV3Extensions:
    payload: bytes
    table_count: int
    manifest_length: int
    table_payload_length: int


@dataclass(frozen=True, slots=True)
class V3ColumnarTable:
    table: pa.Table

    def to_pydict(self) -> dict[str, list[object]]:
        return self.table.to_pydict()


def encode_v3_extensions(extensions: list[ExtensionBlock]) -> EncodedV3Extensions:
    if not isinstance(extensions, list) or any(
        not isinstance(item, ExtensionBlock) for item in extensions
    ):
        raise ZpWriteError("extensions must be a list of ExtensionBlock values")
    source = [
        {
            "extension_type": item.extension_type,
            "extension_version": item.extension_version,
            "payload": item.payload,
        }
        for item in extensions
    ]
    tables: list[bytes] = []
    table_rows: list[int] = []
    skeleton = _extract_tables(source, tables, table_rows)
    table_entries: list[dict[str, object]] = []
    table_offset = 0
    for table_id, (payload, row_count) in enumerate(zip(tables, table_rows)):
        table_entries.append(
            {
                "table_id": table_id,
                "offset": table_offset,
                "length": len(payload),
                "row_count": row_count,
                "checksum": hashlib.sha256(payload).hexdigest(),
            }
        )
        table_offset += len(payload)
    manifest = canonical_json_bytes(
        {
            "schema_version": _VERSION,
            "skeleton": skeleton,
            "tables": table_entries,
        }
    )
    payload_offset = _align8(_HEADER.size + len(manifest))
    padding = b"\0" * (payload_offset - _HEADER.size - len(manifest))
    header = _HEADER.pack(
        _MAGIC,
        _VERSION,
        _ENDIANNESS_LITTLE,
        0,
        len(tables),
        len(manifest),
        payload_offset,
        table_offset,
        b"\0" * 24,
    )
    return EncodedV3Extensions(
        payload=b"".join((header, manifest, padding, *tables)),
        table_count=len(tables),
        manifest_length=len(manifest),
        table_payload_length=table_offset,
    )


def decode_v3_extensions(
    payload: bytes,
    *,
    materialize_column_tables: bool = True,
) -> list[dict[str, object]]:
    if len(payload) < _HEADER.size:
        raise ZpReadError("ZP v3 extensions block is shorter than its fixed header")
    (
        magic,
        version,
        endianness,
        flags,
        table_count,
        manifest_length,
        payload_offset,
        table_payload_length,
        reserved,
    ) = _HEADER.unpack_from(payload)
    if magic != _MAGIC:
        raise ZpReadError("Invalid ZP v3 extensions magic")
    if version != _VERSION or endianness != _ENDIANNESS_LITTLE or flags != 0:
        raise ZpReadError("Unsupported ZP v3 extensions header")
    if reserved != b"\0" * 24:
        raise ZpReadError("ZP v3 extensions reserved bytes must be zero")
    manifest_end = _HEADER.size + manifest_length
    if payload_offset != _align8(manifest_end):
        raise ZpReadError("Invalid ZP v3 extensions payload offset")
    if payload_offset + table_payload_length != len(payload):
        raise ZpReadError("Invalid ZP v3 extensions payload length")
    if any(payload[manifest_end:payload_offset]):
        raise ZpReadError("ZP v3 extensions padding must be zero")
    manifest_raw = payload[_HEADER.size:manifest_end]
    try:
        manifest = parse_json_bytes(manifest_raw)
    except (UnicodeError, ValueError) as exc:
        raise ZpReadError(f"Invalid ZP v3 extensions manifest: {exc}") from exc
    if canonical_json_bytes(manifest) != manifest_raw:
        raise ZpReadError("ZP v3 extensions manifest is not canonical JSON")
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema_version", "skeleton", "tables"}
        or manifest.get("schema_version") != _VERSION
        or not isinstance(manifest.get("tables"), list)
    ):
        raise ZpReadError("Invalid ZP v3 extensions manifest schema")
    raw_entries = manifest["tables"]
    if len(raw_entries) != table_count:
        raise ZpReadError("ZP v3 extensions table count does not match the manifest")
    decoded_tables: list[tuple[str, object]] = []
    expected_offset = 0
    for table_id, entry in enumerate(raw_entries):
        if (
            not isinstance(entry, dict)
            or set(entry)
            != {"table_id", "offset", "length", "row_count", "checksum"}
            or entry.get("table_id") != table_id
        ):
            raise ZpReadError("Invalid ZP v3 extensions table entry")
        offset = entry.get("offset")
        length = entry.get("length")
        row_count = entry.get("row_count")
        checksum = entry.get("checksum")
        if (
            not _nonnegative_int(offset)
            or not _nonnegative_int(length)
            or not _nonnegative_int(row_count)
            or not isinstance(checksum, str)
            or len(checksum) != 64
            or offset != expected_offset
            or offset + length > table_payload_length
        ):
            raise ZpReadError("Invalid ZP v3 extensions table bounds")
        start = payload_offset + offset
        table_payload = payload[start : start + length]
        if hashlib.sha256(table_payload).hexdigest() != checksum:
            raise ZpReadError("ZP v3 extensions table checksum mismatch")
        try:
            table = pa.ipc.open_stream(pa.BufferReader(table_payload)).read_all()
        except (pa.ArrowException, OSError, ValueError) as exc:
            raise ZpReadError(f"Invalid ZP v3 Arrow table: {exc}") from exc
        if table.num_rows != row_count:
            raise ZpReadError("ZP v3 extensions Arrow row count mismatch")
        if _table_has_nonfinite(table):
            raise ZpReadError("ZP v3 extensions Arrow table contains a non-finite value")
        decoded_tables.append(("records", table))
        expected_offset += length
    if expected_offset != table_payload_length:
        raise ZpReadError("ZP v3 extensions tables do not cover the payload")
    restored = _restore_tables(
        manifest["skeleton"],
        decoded_tables,
        materialize_column_tables=materialize_column_tables,
    )
    if not isinstance(restored, list) or not all(
        isinstance(item, dict) for item in restored
    ):
        raise ZpReadError("ZP v3 extensions skeleton did not restore a list")
    return restored


def _extract_tables(
    value: object,
    tables: list[bytes],
    table_rows: list[int],
) -> object:
    if isinstance(value, pa.RecordBatch):
        return _store_table(
            pa.Table.from_batches([value]),
            "columns",
            tables,
            table_rows,
        )
    if isinstance(value, pa.Table):
        return _store_table(value, "columns", tables, table_rows)
    if isinstance(value, dict):
        if _RESERVED_KEY in value or _KIND_KEY in value:
            raise ZpWriteError(
                f"Extension payload uses reserved ZP v3 key {_RESERVED_KEY!r}"
            )
        column_table = _column_mapping_table(value)
        if column_table is not None:
            return _store_table(column_table, "columns", tables, table_rows)
        return {
            str(key): _extract_tables(item, tables, table_rows)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        record_table = _record_table(value)
        if record_table is not None:
            return _store_table(record_table, "records", tables, table_rows)
        return [_extract_tables(item, tables, table_rows) for item in value]
    if is_dataclass(value):
        return _extract_tables(to_primitive(value), tables, table_rows)
    return to_primitive(value)


def _record_table(value: list[object] | tuple[object, ...]) -> pa.Table | None:
    if len(value) < _MIN_TABLE_ROWS or not all(
        isinstance(item, dict) for item in value
    ):
        return None
    try:
        return pa.Table.from_pylist(list(value))
    except (pa.ArrowException, OverflowError, TypeError, ValueError):
        return None


def _column_mapping_table(value: dict[object, object]) -> pa.Table | None:
    if not value or not all(
        isinstance(key, str) and isinstance(item, (list, tuple))
        for key, item in value.items()
    ):
        return None
    lengths = {len(item) for item in value.values()}  # type: ignore[arg-type]
    if len(lengths) != 1 or next(iter(lengths)) < _MIN_TABLE_ROWS:
        return None
    try:
        return pa.table({str(key): item for key, item in value.items()})
    except (pa.ArrowException, OverflowError, TypeError, ValueError):
        return None


def _store_table(
    table: pa.Table,
    kind: str,
    tables: list[bytes],
    table_rows: list[int],
) -> dict[str, object]:
    if _table_has_nonfinite(table):
        raise ZpWriteError("ZP v3 extension tables cannot contain non-finite values")
    sink = pa.BufferOutputStream()
    options = pa.ipc.IpcWriteOptions(compression="zstd")
    try:
        with pa.ipc.new_stream(sink, table.schema, options=options) as writer:
            writer.write_table(table, max_chunksize=65_536)
        payload = sink.getvalue().to_pybytes()
    except (pa.ArrowException, OSError, ValueError) as exc:
        raise ZpWriteError(f"Failed to encode a ZP v3 extension table: {exc}") from exc
    table_id = len(tables)
    tables.append(payload)
    table_rows.append(table.num_rows)
    return {_RESERVED_KEY: table_id, _KIND_KEY: kind}


def _restore_tables(
    value: object,
    tables: list[tuple[str, object]],
    *,
    materialize_column_tables: bool,
) -> object:
    if isinstance(value, dict):
        if set(value) == {_RESERVED_KEY, _KIND_KEY}:
            table_id = value.get(_RESERVED_KEY)
            kind = value.get(_KIND_KEY)
            if (
                not _nonnegative_int(table_id)
                or table_id >= len(tables)
                or kind not in {"records", "columns"}
            ):
                raise ZpReadError("Invalid ZP v3 extension table reference")
            table = tables[table_id][1]
            if not isinstance(table, pa.Table):
                raise ZpReadError("Invalid decoded ZP v3 extension table")
            if kind == "records":
                return table.to_pylist()
            return table.to_pydict() if materialize_column_tables else V3ColumnarTable(table)
        return {
            key: _restore_tables(
                item,
                tables,
                materialize_column_tables=materialize_column_tables,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _restore_tables(
                item,
                tables,
                materialize_column_tables=materialize_column_tables,
            )
            for item in value
        ]
    return value


def _table_has_nonfinite(table: pa.Table) -> bool:
    return any(_array_has_nonfinite(table.column(position)) for position in range(table.num_columns))


def _array_has_nonfinite(value: pa.Array | pa.ChunkedArray) -> bool:
    data_type = value.type
    if pa.types.is_floating(data_type):
        invalid = pc.invert(pc.is_finite(value))
        result = pc.any(pc.fill_null(invalid, False)).as_py()
        return bool(result)
    if pa.types.is_list(data_type) or pa.types.is_large_list(data_type):
        return _array_has_nonfinite(pc.list_flatten(value))
    if pa.types.is_fixed_size_list(data_type):
        return _array_has_nonfinite(pc.list_flatten(value))
    if pa.types.is_struct(data_type):
        return any(
            _array_has_nonfinite(pc.struct_field(value, position))
            for position in range(data_type.num_fields)
        )
    if pa.types.is_map(data_type):
        if isinstance(value, pa.ChunkedArray):
            return any(_array_has_nonfinite(chunk) for chunk in value.chunks)
        return _array_has_nonfinite(value.keys) or _array_has_nonfinite(value.items)
    return False


def _align8(value: int) -> int:
    return (value + 7) & ~7


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
