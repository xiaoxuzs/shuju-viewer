"""Read-only record previews. These are never conversion inputs or whole-file validation."""
from __future__ import annotations

import csv
import io
import itertools
import json
import math
from pathlib import Path
import posixpath
import zipfile

from lxml import etree

from .budget import BudgetedReader, BudgetTracker, InspectionBudgetExceeded
from .contracts import InspectionLimits

ROWS = 10
COLUMNS = 32
CELL_CHARS = 256
MAX_BYTES = 8 * 1024 * 1024


def bounded_value(value, depth=0):
    if depth >= 4 and isinstance(value, (dict, list, tuple)):
        return {"omitted": "nested_depth_limit"}
    if isinstance(value, str):
        return value if len(value) <= CELL_CHARS else value[:CELL_CHARS] + "…[truncated]"
    if isinstance(value, dict):
        result = {str(k): bounded_value(v, depth + 1) for k, v in itertools.islice(value.items(), COLUMNS)}
        if len(value) > COLUMNS:
            result["__omitted_fields__"] = len(value) - COLUMNS
        return result
    if isinstance(value, (list, tuple)):
        items = [bounded_value(v, depth + 1) for v in value[:ROWS]]
        return items if len(value) <= ROWS else {"items": items, "omitted_items": len(value) - ROWS}
    if isinstance(value, float) and not math.isfinite(value):
        return {"non_finite": str(value)}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return bounded_value(str(value), depth)


def preview_file(path: Path, *, row_offset=0, field_offset=0, field_limit=COLUMNS, purpose=None, sheet=None, sheet_offset=0):
    for name, number, maximum in (("row_offset", row_offset, 100_000), ("field_offset", field_offset, 10_000), ("sheet_offset", sheet_offset, 1000)):
        if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= maximum:
            raise ValueError(f"invalid {name}")
    if row_offset and (not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 300):
        raise ValueError("noninitial record ranges require a bounded research purpose")
    if type(field_limit) is not int or not 1 <= field_limit <= COLUMNS:
        raise ValueError("field_limit must be between 1 and 32")
    result = {"preview_only": True, "row_limit": ROWS, "row_offset": row_offset, "field_offset": field_offset,
              "cell_character_limit": CELL_CHARS, "nested_depth_limit": 4, "total_rows": None,
              "full_file_validated": False, "records": [], "truncation": []}
    tracker = BudgetTracker(InspectionLimits(max_bytes_read=MAX_BYTES, max_rows=100_010, max_seconds=5))
    suffix = path.suffix.casefold()
    try:
        if suffix == ".xlsx":
            from .preview_process import preview_xlsx
            return preview_xlsx(path, result, sheet, sheet_offset, row_offset, field_offset, field_limit)
        if suffix not in {".csv", ".tsv", ".txt", ".jsonl", ".ndjson", ".parquet"}:
            return {**result, "status": "UNSUPPORTED", "reason": "Use the registered bounded structure/metadata inspector; no raw content preview for this format."}
        with path.open("rb") as raw:
            metered = BudgetedReader(raw, tracker, file_size=path.stat().st_size)
            if suffix == ".parquet":
                import pyarrow.parquet as pq
                parquet = pq.ParquetFile(metered)
                fields = parquet.schema_arrow.names
                selected = fields[field_offset:field_offset + field_limit]
                result["total_rows"] = parquet.metadata.num_rows
                rows = (item for batch in parquet.iter_batches(batch_size=ROWS, columns=selected) for item in batch.to_pylist())
            else:
                text = io.TextIOWrapper(metered, encoding="utf-8-sig", errors="strict", newline="")
                if suffix in {".jsonl", ".ndjson"}:
                    def json_rows():
                        for line in text:
                            if line.strip():
                                value = json.loads(line)
                                if not isinstance(value, dict):
                                    raise ValueError("JSONL record must be an object")
                                yield value
                    rows = json_rows()
                    first = next(rows, None)
                    fields = list(first or {})
                    rows = itertools.chain([first], rows) if first is not None else iter(())
                else:
                    rows = csv.DictReader(text, delimiter="," if suffix == ".csv" else "\t")
                    fields = rows.fieldnames or []
                    if len(set(fields)) != len(fields) or any(not f for f in fields):
                        raise ValueError("Header is ambiguous: duplicate or empty names")
                    result["header_assumption"] = "first parsed record; not independently confirmed"
                selected = fields[field_offset:field_offset + field_limit]
            if any(len(f) > 512 for f in selected):
                raise ValueError("Field name exceeds safe identity length; cannot silently rename it")
            result.update({"fields": selected, "field_count": len(fields),
                           "next_field_offset": field_offset + field_limit if field_offset + field_limit < len(fields) else None})
            for index, row in enumerate(rows):
                tracker.take_row()
                if index < row_offset:
                    continue
                if len(result["records"]) >= ROWS:
                    result["truncation"].append("record_limit")
                    break
                if None in row:
                    raise ValueError("Record width exceeds header")
                result["records"].append({key: bounded_value(row.get(key)) for key in selected})
            result["status"] = "PREVIEW"
    except InspectionBudgetExceeded as exc:
        result.update(status="PARTIAL")
        result["truncation"].append("read_budget_" + exc.reason)
    except (ValueError, OSError, UnicodeError, csv.Error) as exc:
        result.update(status="INVALID", error_type=type(exc).__name__)
    result["budget"] = tracker.usage().model_dump(mode="json")
    return result


def _xlsx(path, result, sheet, sheet_offset, row_offset, field_offset, field_limit):
    # No Office/LibreOffice invocation, formula evaluation, links or macros. Never extract ZIP entries.
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > 4096 or sum(m.file_size for m in members) > 64 * 1024 * 1024:
            raise ValueError("XLSX container exceeds bounded preview budget")
        def xml(name):
            entry = archive.getinfo(name)
            if entry.file_size > MAX_BYTES or entry.flag_bits & 1:
                raise ValueError("XLSX member exceeds budget or is encrypted")
            with archive.open(entry) as stream:
                content = stream.read(MAX_BYTES + 1)
            if len(content) > MAX_BYTES or b"<!DOCTYPE" in content.upper():
                raise ValueError("Unsafe XLSX XML")
            return etree.fromstring(content, parser=etree.XMLParser(resolve_entities=False, no_network=True))
        workbook = xml("xl/workbook.xml")
        sheets = workbook.findall(".//{*}sheet")
        names = [s.get("name") for s in sheets]
        result.update({"sheets": names[sheet_offset:sheet_offset + 20], "sheet_count": len(names),
                       "next_sheet_offset": sheet_offset + 20 if sheet_offset + 20 < len(names) else None,
                       "formula_evaluation": "disabled", "external_link_refresh": "disabled",
                       "conversion_supported": False})
        if sheet is None:
            return {**result, "status": "SELECT_SHEET"}
        if not isinstance(sheet, str) or sheet not in names:
            raise ValueError("Choose an exact listed sheet name")
        rels = xml("xl/_rels/workbook.xml.rels")
        selected = sheets[names.index(sheet)]
        relid = selected.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        relationship = next((r for r in rels if r.get("Id") == relid), None)
        if relationship is None or relationship.get("TargetMode") == "External":
            raise ValueError("Invalid or external worksheet relationship")
        target = relationship.get("Target", "")
        target = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
        if not target.startswith("xl/worksheets/"):
            raise ValueError("Worksheet target is outside the worksheet container")
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(si.itertext()) for si in xml("xl/sharedStrings.xml")]
        document = xml(target)
        row_nodes = document.findall(".//{*}sheetData/{*}row")
        def cell_value(cell):
            value = cell.findtext("{*}v")
            kind = cell.get("t")
            if kind == "s" and value is not None:
                value = shared[int(value)]
            elif kind == "inlineStr":
                value = "".join(cell.find("{*}is").itertext())
            if cell.find("{*}f") is not None:
                return {"cached_value": bounded_value(value), "cache_validity": "unknown", "formula_not_evaluated": True}
            return bounded_value(value)
        def cells(row):
            return {"".join(c for c in cell.get("r", "") if c.isalpha()): cell_value(cell) for cell in row}
        header = cells(row_nodes[0]) if row_nodes else {}
        columns = list(header)[field_offset:field_offset + field_limit]
        result.update({"sheet": sheet, "fields": [{"column": c, "first_row_value": header[c]} for c in columns],
                       "next_field_offset": field_offset + field_limit if field_offset + field_limit < len(header) else None,
                       "header_status": "unconfirmed_first_row; multirow headers require clarification",
                       "merged_cells_present": bool(document.findall(".//{*}mergeCell")),
                       "status": "PREVIEW"})
        for row in row_nodes[1 + row_offset:1 + row_offset + ROWS]:
            values = cells(row)
            result["records"].append({c: values.get(c) for c in columns})
        if len(row_nodes) > 1 + row_offset + ROWS:
            result["truncation"].append("record_limit")
        return result
