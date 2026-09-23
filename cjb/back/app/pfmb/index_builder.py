"""Build Viewer PFMB ``index.json`` from DIA-NN ``*.pos.pkl`` rows."""

from __future__ import annotations

import json
import pickle
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class BuiltPfmbIndex:
    index_path: Path
    item_count: int
    source_row_count: int


def count_pos_pkl_expansion(pos_pkl: Path | str) -> tuple[int, int]:
    """Return ``(source_row_count, expanded_slot_count)`` for one ``*.pos.pkl``."""

    with open(pos_pkl, "rb") as handle:
        raw = pickle.load(handle)
    source_row_count = 0
    item_count = 0
    for row in _iter_pos_rows(raw):
        rts = _required_float_list(row, _RT_KEYS, "frag.RT")
        source_row_count += 1
        item_count += len(rts)
    return source_row_count, item_count


def build_index_json_from_pos_pkl(
    pos_pkl: Path | str,
    index_path: Path | str,
    *,
    expected_record_count: int | None = None,
    expected_expanded_record_count: int | None = None,
    version: str = "generated_diann_pos_pkl",
) -> BuiltPfmbIndex:
    """Expand one ``*.pos.pkl`` into the PFMB slot index consumed by Viewer."""

    pos_pkl = Path(pos_pkl)
    index_path = Path(index_path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = index_path.with_name(index_path.name + ".tmp")

    with open(pos_pkl, "rb") as handle:
        raw = pickle.load(handle)

    item_count = 0
    source_row_count = 0
    with open(tmp_path, "w", encoding="utf-8") as out:
        out.write(json.dumps({"version": version}, ensure_ascii=False)[:-1])
        out.write(',"items":[\n')
        first = True
        for source_row, row in enumerate(_iter_pos_rows(raw)):
            peptide = _required_str(row, _PEPTIDE_KEYS, "peptide")
            charge = _required_int(row, _CHARGE_KEYS, "precursor charge")
            rts = _required_float_list(row, _RT_KEYS, "frag.RT")
            chrom_shape = _matrix_shape(_get_any(row, _CHROM_KEYS))
            apex_slot = _apex_slot(row, len(rts), chrom_shape)
            matrix_rows, matrix_cols = chrom_shape if chrom_shape is not None else (0, len(rts))

            source_row_count += 1
            for slot_index, slot_rt in enumerate(rts):
                item = {
                    "prsm_index": item_count,
                    "source_row": source_row,
                    "slot_index": slot_index,
                    "slot_rt": slot_rt,
                    "peptide": peptide,
                    "precursor_charge": charge,
                    "apex_slot": apex_slot,
                    "window_left": 0,
                    "window_right": len(rts) - 1,
                    "window_size": len(rts),
                    "matrix_rows": matrix_rows,
                    "matrix_cols": matrix_cols,
                }
                if not first:
                    out.write(",\n")
                out.write(json.dumps(item, ensure_ascii=False))
                first = False
                item_count += 1
        out.write("\n]}\n")

    if expected_record_count is not None and source_row_count != expected_record_count:
        tmp_path.unlink(missing_ok=True)
        raise ValueError(
            "PFMB index source row count mismatch: "
            f"index={source_row_count}, expected={expected_record_count}"
        )
    if expected_expanded_record_count is not None and item_count != expected_expanded_record_count:
        tmp_path.unlink(missing_ok=True)
        raise ValueError(
            "PFMB index expanded slot count mismatch: "
            f"index={item_count}, expected={expected_expanded_record_count}"
        )

    tmp_path.replace(index_path)
    return BuiltPfmbIndex(
        index_path=index_path.resolve(),
        item_count=item_count,
        source_row_count=source_row_count,
    )


def read_pfmb_record_count(pfmb_path: Path | str) -> int:
    """Read the record count from a PFMB bundle header without importing ``pfm``."""

    with open(pfmb_path, "rb") as handle:
        if handle.read(4) != b"PFMB":
            raise ValueError(f"not a PFMB bundle: {pfmb_path}")
        header_len = struct.unpack("<I", handle.read(4))[0]
        header = handle.read(header_len)
    if not header:
        raise ValueError(f"empty PFMB header: {pfmb_path}")
    if header[:1] == b"{":
        data = json.loads(header.decode("utf-8"))
        return int(data["record_count"])
    if len(header) < 12:
        raise ValueError(f"invalid PFMB binary header: {pfmb_path}")
    version, _index_version, record_count = struct.unpack_from("<III", header, 0)
    if version != 3:
        raise ValueError(f"unsupported PFMB bundle version {version}: {pfmb_path}")
    return int(record_count)


_PEPTIDE_KEYS = (
    "pre.peptide",
    "peptide",
    "modified_sequence",
    "Modified.Sequence",
    "sequence",
    "Stripped.Sequence",
    "input_peptide",
    "pep",
)
_CHARGE_KEYS = ("pre.charge", "precursor_charge", "Precursor.Charge", "charge", "z")
_RT_KEYS = ("frag.RT", "frag_rt", "fragRT", "slot_rt", "rt", "RT")
_CHROM_KEYS = ("frag.chrom", "frag_chrom", "fragChrom", "chrom", "matrix")
_APEX_KEYS = ("apex_slot", "frag.apex_slot", "apex")


def _iter_pos_rows(raw: Any) -> Iterable[Any]:
    if hasattr(raw, "to_dict"):
        try:
            records = raw.to_dict("records")
        except TypeError:
            records = None
        if records is not None:
            return records

    if isinstance(raw, dict):
        for key in ("items", "records", "rows", "prsms", "data"):
            value = raw.get(key)
            if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
                return value
        columnar = _columnar_rows(raw)
        if columnar is not None:
            return columnar
        if _get_any(raw, _RT_KEYS) is not None:
            return [raw]

    if isinstance(raw, Iterable) and not isinstance(raw, (str, bytes)):
        return raw
    raise ValueError("unsupported pos.pkl structure")


def _columnar_rows(raw: dict[str, Any]) -> list[dict[str, Any]] | None:
    length = None
    for key in (*_PEPTIDE_KEYS, *_CHARGE_KEYS):
        value = raw.get(key)
        if _is_row_sequence(value):
            length = len(value)
            break
    if length is None:
        return None
    return [
        {
            key: value[i] if _is_row_sequence(value) and len(value) == length else value
            for key, value in raw.items()
        }
        for i in range(length)
    ]


def _is_row_sequence(value: Any) -> bool:
    return (
        hasattr(value, "__len__")
        and not isinstance(value, (str, bytes, bytearray, dict))
        and np.asarray(value, dtype=object).ndim != 0
    )


def _get_any(row: Any, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = _get_value(row, key)
        if value is not None:
            return value
    return None


def _get_value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        if key in row:
            return row[key]
        lowered = {str(k).lower(): k for k in row}
        hit = lowered.get(key.lower())
        if hit is not None:
            return row[hit]
        if "." in key:
            value: Any = row
            for part in key.split("."):
                if not isinstance(value, dict):
                    return None
                value = value.get(part)
                if value is None:
                    return None
            return value
    attr = key.replace(".", "_")
    if hasattr(row, attr):
        return getattr(row, attr)
    return None


def _required_str(row: Any, keys: tuple[str, ...], label: str) -> str:
    value = _get_any(row, keys)
    if value is None or str(value).strip() == "":
        raise ValueError(f"pos.pkl row is missing {label}")
    return str(value)


def _required_int(row: Any, keys: tuple[str, ...], label: str) -> int:
    value = _get_any(row, keys)
    if value is None:
        raise ValueError(f"pos.pkl row is missing {label}")
    return int(value)


def _required_float_list(row: Any, keys: tuple[str, ...], label: str) -> list[float]:
    value = _get_any(row, keys)
    if value is None:
        raise ValueError(f"pos.pkl row is missing {label}")
    values = _to_list(value)
    if not values:
        raise ValueError(f"pos.pkl row has empty {label}")
    return [float(v) for v in values]


def _to_list(value: Any) -> list[Any]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _matrix_shape(value: Any) -> tuple[int, int] | None:
    if value is None:
        return None
    arr = np.asarray(value)
    if arr.ndim == 1:
        return (1, int(arr.shape[0]))
    if arr.ndim >= 2:
        return (int(arr.shape[0]), int(arr.shape[1]))
    return None


def _apex_slot(row: Any, rt_count: int, chrom_shape: tuple[int, int] | None) -> int | None:
    explicit = _get_any(row, _APEX_KEYS)
    if explicit is not None:
        return int(explicit)
    chrom = _get_any(row, _CHROM_KEYS)
    if chrom is not None and chrom_shape is not None and chrom_shape[1] == rt_count:
        arr = np.asarray(chrom, dtype=float)
        if arr.ndim == 1:
            return int(np.nanargmax(np.nan_to_num(arr, nan=0.0)))
        return int(np.nanargmax(np.nan_to_num(arr, nan=0.0).sum(axis=0)))
    return rt_count // 2 if rt_count else None
