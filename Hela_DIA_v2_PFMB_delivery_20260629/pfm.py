from __future__ import annotations

import json
import mmap
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple, Union

import numpy as np

MAGIC = b"PFM1"
MAGIC2 = b"PFM2"  # lean record: binary header + columnar matches
BUNDLE_MAGIC = b"PFMB"
VERSION = 1
BUNDLE_FORMAT_VERSION = 3  # v3: binary bundle header + PFM2 records (v2 = JSON bundle + PFM1)
INDEX_VERSION = 1

# (列名, numpy dtype 字符串)
_COLS: List[tuple] = [
    ("peak_id",                   "<i4"),
    ("fragment_ordinal",          "<i2"),
    ("series_idx",                "u1"),
    ("observed_neutral_mass",     "<f4"),
    ("theoretical_neutral_mass",  "<f4"),
    ("mass_error_ppm",            "<f4"),
    ("mass_error_da",             "<f4"),
    ("intensity",                 "<f4"),
    ("charge",                    "<i2"),
]


def encode_pfm_columns(
    metadata: Dict,
    summary: Dict,
    columns: Dict,
    series_table: List[str],
    *,
    timing: Optional[Dict] = None,
) -> bytes:
    """Encode columnar match arrays directly (no Python dict roundtrip).

    columns must contain numpy arrays with keys matching _COLS (peak_id, fragment_ordinal, ...).
    series_table is the lookup for series_idx (already encoded in `columns["series_idx"]`).
    """
    header: Dict = {**metadata, "summary": summary, "series_table": series_table}
    if timing:
        header["timing"] = timing
    hdr_bytes = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    N = int(columns["peak_id"].shape[0]) if "peak_id" in columns else 0
    chunks = [
        MAGIC,
        struct.pack("<I", len(hdr_bytes)),
        hdr_bytes,
        struct.pack("<I", N),
    ]
    for col, dt in _COLS:
        if col in columns:
            arr = np.ascontiguousarray(columns[col], dtype=np.dtype(dt))
            chunks.append(arr.tobytes())
        else:
            chunks.append(np.zeros(N, dtype=np.dtype(dt)).tobytes())
    return b"".join(chunks)


def matches_to_columns(matches: List[Dict]) -> Tuple[Dict[str, np.ndarray], List[str]]:
    """把 JSON 风格的 match 列表转成列数组 + series_table（供保留路径调用）。"""
    series_table: List[str] = []
    series_index: Dict[str, int] = {}
    for m in matches:
        s = m.get("fragment_series", "")
        if s not in series_index:
            series_index[s] = len(series_table)
            series_table.append(s)

    n = len(matches)
    columns: Dict[str, np.ndarray] = {col: np.zeros(n, dtype=dt) for col, dt in _COLS}
    for i, m in enumerate(matches):
        columns["peak_id"][i] = m.get("peak_id", 0)
        columns["fragment_ordinal"][i] = m.get("fragment_ordinal", 0)
        columns["series_idx"][i] = series_index.get(m.get("fragment_series", ""), 0)
        columns["observed_neutral_mass"][i] = m.get("observed_neutral_mass", 0.0)
        columns["theoretical_neutral_mass"][i] = m.get("theoretical_neutral_mass", 0.0)
        columns["mass_error_ppm"][i] = m.get("mass_error_ppm", 0.0)
        columns["mass_error_da"][i] = m.get("mass_error_da", 0.0)
        columns["intensity"][i] = m.get("intensity", 0.0)
        columns["charge"][i] = m.get("charge", 0)
    return columns, series_table


def encode_pfm_record(
    metadata: Dict,
    summary: Dict,
    matches: List[Dict],
    *,
    timing: Optional[Dict] = None,
) -> bytes:
    """保留路径：dict 列表 → 列 → encode_pfm_columns（与快路径同一套 PFM1 布局）。"""
    columns, series_table = matches_to_columns(matches)
    return encode_pfm_columns(metadata, summary, columns, series_table, timing=timing)


def write_pfm(
    path: Path,
    metadata: Dict,
    summary: Dict,
    matches: List[Dict],
    *,
    timing: Optional[Dict] = None,
) -> None:
    """将一条 PRSM 的匹配结果写成 .pfm 二进制文件。"""
    path.write_bytes(encode_pfm_record(metadata, summary, matches, timing=timing))


def write_pfmb_lean_bundle(
    bundle_path: Path,
    *,
    metadata: Optional[List[dict]] = None,
    meta_prsm_index: Optional[np.ndarray] = None,
    meta_scan: Optional[np.ndarray] = None,
    meta_spec_id: Optional[np.ndarray] = None,
    meta_peptides: Optional[Sequence[str]] = None,
    peak_offsets: np.ndarray,
    out_peak_global: np.ndarray,
    out_frag_local: np.ndarray,
    out_da: np.ndarray,
    out_ppm: np.ndarray,
    out_match_counts: np.ndarray,
    frag_offsets: np.ndarray,
    flat_frag_mass: np.ndarray,
    flat_frag_ord: np.ndarray,
    flat_frag_sidx: np.ndarray,
    all_peak_id: np.ndarray,
    all_peak_intensity: np.ndarray,
    all_peak_charge: np.ndarray,
    all_peak_mass: np.ndarray,
    series_global: List[str],
    top_n: int,
) -> None:
    """Turbo 批量写 results.pfmb：包头 series_table_global，每条记录仍是 _COLS 列布局。"""
    if metadata is not None:
        n_prsm = len(metadata)
    elif meta_peptides is not None:
        n_prsm = len(meta_peptides)
    else:
        raise ValueError("write_pfmb_lean_bundle requires metadata or meta_peptides")
    slot_starts = peak_offsets[:n_prsm] * top_n
    cum_counts = np.concatenate([[0], np.cumsum(out_match_counts)])
    total_matches = int(cum_counts[-1])

    if total_matches > 0:
        per_prsm_offsets = np.repeat(slot_starts, out_match_counts.astype(np.int64))
        local_pos = np.arange(total_matches) - np.repeat(cum_counts[:n_prsm], out_match_counts.astype(np.int64))
        global_slots = per_prsm_offsets + local_pos
        peak_global_flat = out_peak_global[global_slots]
        frag_local_flat = out_frag_local[global_slots]
        ppm_flat = out_ppm[global_slots].astype(np.float32, copy=False)
        da_flat = out_da[global_slots].astype(np.float32, copy=False)
        per_prsm_frag_base = np.repeat(frag_offsets[:n_prsm], out_match_counts.astype(np.int64))
        frag_global = per_prsm_frag_base + frag_local_flat
        peak_id_flat = all_peak_id[peak_global_flat].astype(np.int32, copy=False)
        obs_flat = all_peak_mass[peak_global_flat].astype(np.float32, copy=False)
        inten_flat = all_peak_intensity[peak_global_flat].astype(np.float32, copy=False)
        charge_flat = all_peak_charge[peak_global_flat].astype(np.int16, copy=False)
        ord_flat = flat_frag_ord[frag_global].astype(np.int16, copy=False)
        sidx_flat = flat_frag_sidx[frag_global].astype(np.uint8, copy=False)
        theo_flat = flat_frag_mass[frag_global].astype(np.float32, copy=False)
    else:
        peak_id_flat = np.zeros(0, dtype=np.int32)
        obs_flat = np.zeros(0, dtype=np.float32)
        inten_flat = np.zeros(0, dtype=np.float32)
        charge_flat = np.zeros(0, dtype=np.int16)
        ord_flat = np.zeros(0, dtype=np.int16)
        sidx_flat = np.zeros(0, dtype=np.uint8)
        theo_flat = np.zeros(0, dtype=np.float32)
        ppm_flat = np.zeros(0, dtype=np.float32)
        da_flat = np.zeros(0, dtype=np.float32)

    col_bytes = {
        "peak_id": peak_id_flat.tobytes(),
        "fragment_ordinal": ord_flat.tobytes(),
        "series_idx": sidx_flat.tobytes(),
        "observed_neutral_mass": obs_flat.tobytes(),
        "theoretical_neutral_mass": theo_flat.tobytes(),
        "mass_error_ppm": ppm_flat.tobytes(),
        "mass_error_da": da_flat.tobytes(),
        "intensity": inten_flat.tobytes(),
        "charge": charge_flat.tobytes(),
    }
    col_sizes = {name: np.dtype(dt).itemsize for name, dt in _COLS}

    bundle_hdr = _encode_bundle_header_v3(n_prsm, series_global)
    index_bytes = 8 * n_prsm
    data_start = 4 + 4 + len(bundle_hdr) + index_bytes
    offsets = np.empty(n_prsm, dtype=np.uint64)

    with bundle_path.open("wb") as fout:
        fout.write(BUNDLE_MAGIC)
        fout.write(struct.pack("<I", len(bundle_hdr)))
        fout.write(bundle_hdr)
        fout.write(b"\x00" * index_bytes)

        match_cursor = 0
        pos = data_start
        for i in range(n_prsm):
            cnt = int(out_match_counts[i])
            if metadata is not None:
                meta = metadata[i]
            else:
                meta = {
                    "prsm_index": int(meta_prsm_index[i]),
                    "scan": int(meta_scan[i]),
                    "spec_id": int(meta_spec_id[i]),
                    "input_peptide": meta_peptides[i],
                }
            slices: Dict[str, bytes] = {}
            if cnt:
                for col, _ in _COLS:
                    sz = col_sizes[col]
                    slices[col] = col_bytes[col][match_cursor * sz : (match_cursor + cnt) * sz]
            else:
                slices = {col: b"" for col, _ in _COLS}
            rec = _encode_pfm2_record(meta, cnt, slices, col_sizes)
            offsets[i] = pos
            fout.write(struct.pack("<Q", len(rec)))
            fout.write(rec)
            pos += 8 + len(rec)
            match_cursor += cnt

        fout.seek(4 + 4 + len(bundle_hdr))
        fout.write(offsets.tobytes())


def write_pfm_bundle(
    path: Path,
    records: List[bytes],
    *,
    metadata: Optional[Dict] = None,
    series_table_global: Optional[List[str]] = None,
) -> None:
    """Write many PFM/PFM2 records into one PFMB v3 bundle (uint64 offset index)."""
    n = len(records)
    extra = dict(metadata or {})
    series = list(series_table_global or extra.pop("series_table_global", []))
    hdr_bytes = _encode_bundle_header_v3(n, series)
    if extra:
        # Non-struct extras are not stored in v3 binary header; callers should avoid relying on them.
        pass
    data_start = 4 + 4 + len(hdr_bytes) + 8 * n
    offsets = np.empty(n, dtype=np.uint64)
    pos = data_start
    for i, rec in enumerate(records):
        offsets[i] = pos
        pos += 8 + len(rec)

    buf = bytearray()
    buf.extend(BUNDLE_MAGIC)
    buf.extend(struct.pack("<I", len(hdr_bytes)))
    buf.extend(hdr_bytes)
    buf.extend(offsets.tobytes())
    for rec in records:
        buf.extend(struct.pack("<Q", len(rec)))
        buf.extend(rec)
    path.write_bytes(buf)


def read_pfm(path: Path) -> Dict:
    """读取 .pfm 文件，返回与旧 JSON 格式兼容的 dict。

    返回键：metadata, summary, matches, timing（可选）
    matches 列表里每项含与 JSON 版相同的字段名。
    """
    with path.open("rb") as f:
        magic = f.read(4)
        if magic != MAGIC:
            raise ValueError(f"不是有效的 PFM 文件（magic={magic!r}）: {path}")
        (hdr_len,) = struct.unpack("<I", f.read(4))
        header: Dict = json.loads(f.read(hdr_len).decode("utf-8"))
        (N,) = struct.unpack("<I", f.read(4))

        arrays: Dict[str, np.ndarray] = {}
        for col, dt in _COLS:
            dtype = np.dtype(dt)
            raw = f.read(N * dtype.itemsize)
            arrays[col] = np.frombuffer(raw, dtype=dtype)

    series_table: List[str] = header.pop("series_table", [])
    summary = header.pop("summary", {})
    timing = header.pop("timing", None)

    matches: List[Dict] = []
    for i in range(N):
        sidx = int(arrays["series_idx"][i])
        matches.append({
            "peak_id":                   int(arrays["peak_id"][i]),
            "fragment_series":           series_table[sidx] if sidx < len(series_table) else "",
            "fragment_ordinal":          int(arrays["fragment_ordinal"][i]),
            "observed_neutral_mass":     float(arrays["observed_neutral_mass"][i]),
            "theoretical_neutral_mass":  float(arrays["theoretical_neutral_mass"][i]),
            "mass_error_ppm":            float(arrays["mass_error_ppm"][i]),
            "mass_error_da":             float(arrays["mass_error_da"][i]),
            "intensity":                 float(arrays["intensity"][i]),
            "charge":                    int(arrays["charge"][i]),
        })

    result: Dict = {"metadata": header, "summary": summary, "matches": matches}
    if timing is not None:
        result["timing"] = timing
    return result


def pfm_to_json(pfm_path: Path, json_path: Optional[Path] = None) -> Path:
    """把 .pfm 文件转换为可读 JSON（调试用）。"""
    data = read_pfm(pfm_path)
    out = json_path or pfm_path.with_suffix(".json")
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


_MATCH_ROW_BYTES = int(sum(np.dtype(dt).itemsize for _, dt in _COLS))

# PFM2 record header (after magic): prsm(i32) scan(i32) spec(i32) pep_len(u16) pep utf-8, then N(u32)
_PFM2_HDR_PREFIX_BYTES = 4 + 4 + 4 + 2  # prsm, scan, spec, pep_len field


def _encode_bundle_header_v3(record_count: int, series_global: List[str]) -> bytes:
    parts = [
        struct.pack("<IIIH", BUNDLE_FORMAT_VERSION, INDEX_VERSION, record_count, len(series_global)),
    ]
    for name in series_global:
        nb = name.encode("utf-8")
        if len(nb) > 255:
            raise ValueError(f"series name too long: {name!r}")
        parts.append(struct.pack("<B", len(nb)))
        parts.append(nb)
    return b"".join(parts)


def _decode_bundle_header_v3(hdr_bytes: bytes) -> Tuple[Dict, List[str]]:
    o = 0
    (bundle_version, index_version, record_count, series_count) = struct.unpack_from(
        "<IIIH", hdr_bytes, o
    )
    o += 14
    if bundle_version != BUNDLE_FORMAT_VERSION:
        raise ValueError(f"Unsupported PFMB bundle version {bundle_version} (expected {BUNDLE_FORMAT_VERSION})")
    series_global: List[str] = []
    for _ in range(series_count):
        (nlen,) = struct.unpack_from("<B", hdr_bytes, o)
        o += 1
        series_global.append(hdr_bytes[o : o + nlen].decode("utf-8"))
        o += nlen
    bundle_header: Dict = {
        "version": bundle_version,
        "index_version": index_version,
        "record_count": record_count,
        "output_format": "pfmbundle",
        "header_encoding": "binary",
        "series_table_global": series_global,
    }
    return bundle_header, series_global


def _parse_bundle_header_blob(hdr_bytes: bytes) -> Tuple[Dict, List[str]]:
    """v2: JSON blob; v3: binary blob (first byte is not '{')."""
    if hdr_bytes[:1] == b"{":
        bundle_header = json.loads(hdr_bytes.decode("utf-8"))
        series_global = list(bundle_header.get("series_table_global", []))
        bundle_header.setdefault("header_encoding", "json")
        return bundle_header, series_global
    return _decode_bundle_header_v3(hdr_bytes)


def _encode_pfm2_record(meta: Dict, cnt: int, col_slices: Dict[str, bytes], col_sizes: Dict[str, int]) -> bytes:
    peptide = str(meta["input_peptide"]).encode("utf-8")
    if len(peptide) > 65535:
        raise ValueError("peptide UTF-8 length exceeds uint16")
    rec_parts = [
        MAGIC2,
        struct.pack(
            "<iiiH",
            int(meta["prsm_index"]),
            int(meta["scan"]),
            int(meta["spec_id"]),
            len(peptide),
        ),
        peptide,
        struct.pack("<I", cnt),
    ]
    if cnt:
        for col, _ in _COLS:
            sz = col_sizes[col]
            rec_parts.append(col_slices[col])
    return b"".join(rec_parts)


def _decode_pfm2_bytes(
    raw: Union[bytes, mmap.mmap],
    offset: int,
    *,
    series_global: List[str],
) -> Tuple[Dict, List[Dict], int]:
    if raw[offset : offset + 4] != MAGIC2:
        raise ValueError(f"Bad PFM2 magic at offset {offset}")
    o = offset + 4
    prsm_index, scan, spec_id, pep_len = struct.unpack_from("<iiiH", raw, o)
    o += _PFM2_HDR_PREFIX_BYTES
    peptide = raw[o : o + pep_len].decode("utf-8")
    o += pep_len
    (N,) = struct.unpack_from("<I", raw, o)
    o += 4

    series_table = series_global
    cols: Dict[str, np.ndarray] = {}
    for name, dt in _COLS:
        dtype = np.dtype(dt)
        nbytes = N * dtype.itemsize
        cols[name] = np.frombuffer(raw, dtype=dtype, count=N, offset=o)
        o += nbytes

    rec_hdr: Dict = {
        "i": prsm_index,
        "prsm_index": prsm_index,
        "scan": scan,
        "spec": spec_id,
        "spec_id": spec_id,
        "pep": peptide,
        "input_peptide": peptide,
        "n": N,
    }
    matches: List[Dict] = []
    for i in range(N):
        sidx = int(cols["series_idx"][i])
        matches.append({
            "peak_id": int(cols["peak_id"][i]),
            "fragment_series": series_table[sidx] if sidx < len(series_table) else str(sidx),
            "fragment_ordinal": int(cols["fragment_ordinal"][i]),
            "observed_neutral_mass": float(cols["observed_neutral_mass"][i]),
            "theoretical_neutral_mass": float(cols["theoretical_neutral_mass"][i]),
            "mass_error_ppm": float(cols["mass_error_ppm"][i]),
            "mass_error_da": float(cols["mass_error_da"][i]),
            "intensity": float(cols["intensity"][i]),
            "charge": int(cols["charge"][i]),
        })
    return rec_hdr, matches, o


def _read_record_header_only_bytes(
    raw: Union[bytes, mmap.mmap],
    body_off: int,
) -> Dict:
    magic = raw[body_off : body_off + 4]
    if magic == MAGIC2:
        o = body_off + 4
        prsm_index, scan, spec_id, pep_len = struct.unpack_from("<iiiH", raw, o)
        o += _PFM2_HDR_PREFIX_BYTES
        peptide = raw[o : o + pep_len].decode("utf-8")
        o += pep_len
        (N,) = struct.unpack_from("<I", raw, o)
        return {
            "i": prsm_index,
            "scan": scan,
            "spec": spec_id,
            "pep": peptide,
            "n": N,
        }
    if magic == MAGIC:
        o = body_off + 4
        (rec_hdr_len,) = struct.unpack_from("<I", raw, o)
        o += 4
        return json.loads(raw[o : o + rec_hdr_len].decode("utf-8"))
    raise ValueError(f"Bad record magic at offset {body_off}: {magic!r}")


def _decode_record_bytes(
    raw: Union[bytes, mmap.mmap],
    offset: int,
    *,
    series_global: List[str],
) -> Tuple[Dict, List[Dict], int]:
    magic = raw[offset : offset + 4]
    if magic == MAGIC2:
        return _decode_pfm2_bytes(raw, offset, series_global=series_global)
    if magic == MAGIC:
        return _decode_pfm1_bytes(raw, offset, series_global=series_global)
    raise ValueError(f"Unknown record magic at offset {offset}: {magic!r}")


@dataclass
class PfmbRecord:
    """One PRSM record decoded from a PFMB bundle."""

    record_index: int
    prsm_index: int
    scan: int
    spec_id: int
    peptide: str
    metadata: Dict
    summary: Dict
    matches: List[Dict]
    timing: Optional[Dict] = None


def _decode_pfm1_bytes(
    raw: Union[bytes, mmap.mmap],
    offset: int,
    *,
    series_global: List[str],
) -> Tuple[Dict, List[Dict], int]:
    """Decode one PFM1 record at `offset` (points to PFM1 magic). Returns (rec_hdr, matches, end_offset)."""
    if raw[offset : offset + 4] != MAGIC:
        raise ValueError(f"Bad PFM1 magic at offset {offset}")
    o = offset + 4
    (rec_hdr_len,) = struct.unpack_from("<I", raw, o)
    o += 4
    rec_hdr: Dict = json.loads(raw[o : o + rec_hdr_len].decode("utf-8"))
    o += rec_hdr_len
    (N,) = struct.unpack_from("<I", raw, o)
    o += 4

    series_table: List[str] = rec_hdr.get("series_table") or series_global
    cols: Dict[str, np.ndarray] = {}
    for name, dt in _COLS:
        dtype = np.dtype(dt)
        nbytes = N * dtype.itemsize
        cols[name] = np.frombuffer(raw, dtype=dtype, count=N, offset=o)
        o += nbytes

    matches: List[Dict] = []
    for i in range(N):
        sidx = int(cols["series_idx"][i])
        matches.append({
            "peak_id": int(cols["peak_id"][i]),
            "fragment_series": series_table[sidx] if sidx < len(series_table) else str(sidx),
            "fragment_ordinal": int(cols["fragment_ordinal"][i]),
            "observed_neutral_mass": float(cols["observed_neutral_mass"][i]),
            "theoretical_neutral_mass": float(cols["theoretical_neutral_mass"][i]),
            "mass_error_ppm": float(cols["mass_error_ppm"][i]),
            "mass_error_da": float(cols["mass_error_da"][i]),
            "intensity": float(cols["intensity"][i]),
            "charge": int(cols["charge"][i]),
        })
    return rec_hdr, matches, o


def _pfm_record_to_pfmb_record(
    record_index: int,
    rec_hdr: Dict,
    matches: List[Dict],
) -> PfmbRecord:
    prsm_index = int(rec_hdr.get("i", rec_hdr.get("prsm_index", record_index)))
    peptide = str(rec_hdr.get("pep", rec_hdr.get("input_peptide", "")))
    summary = rec_hdr.get("summary", {})
    timing = rec_hdr.get("timing")
    meta = {
        k: v
        for k, v in rec_hdr.items()
        if k not in ("series_table", "summary", "timing", "pep", "input_peptide")
    }
    if "input_peptide" not in meta and peptide:
        meta["input_peptide"] = peptide
    return PfmbRecord(
        record_index=record_index,
        prsm_index=prsm_index,
        scan=int(rec_hdr.get("scan", 0)),
        spec_id=int(rec_hdr.get("spec", rec_hdr.get("spec_id", 0))),
        peptide=peptide,
        metadata=meta,
        summary=summary,
        matches=matches,
        timing=timing,
    )


class PfmbReader:
    """PFMB IO: O(1) random read by record index when index_version >= 1; sequential scan for legacy files."""

    def __init__(self, path: Path, *, use_mmap: bool = True) -> None:
        self.path = Path(path)
        self._fh = self.path.open("rb")
        if use_mmap:
            self._raw: Union[bytes, mmap.mmap] = mmap.mmap(
                self._fh.fileno(), 0, access=mmap.ACCESS_READ
            )
        else:
            self._raw = self._fh.read()

        if self._raw[:4] != BUNDLE_MAGIC:
            raise ValueError(f"Not a PFMB bundle: {self.path}")

        o = 4
        (hdr_len,) = struct.unpack_from("<I", self._raw, o)
        o += 4
        hdr_blob = self._raw[o : o + hdr_len]
        o += hdr_len
        self.bundle_header, self.series_global = _parse_bundle_header_blob(hdr_blob)
        self.count = int(self.bundle_header.get("record_count", 0))

        if int(self.bundle_header.get("index_version", 0)) >= INDEX_VERSION:
            self._offsets = np.frombuffer(
                self._raw, dtype="<u8", count=self.count, offset=o
            ).copy()
        else:
            self._offsets = self._scan_v1_offsets(o)

        self._prsm_to_record: Optional[Dict[int, int]] = None

    def _scan_v1_offsets(self, start: int) -> np.ndarray:
        """One-time sequential scan for legacy bundles without index table."""
        offsets = np.empty(self.count, dtype=np.uint64)
        o = start
        for i in range(self.count):
            offsets[i] = o
            (rec_len,) = struct.unpack_from("<Q", self._raw, o)
            o += 8 + rec_len
        return offsets

    def close(self) -> None:
        try:
            if hasattr(self._raw, "close"):
                self._raw.close()  # type: ignore[union-attr]
        finally:
            self._fh.close()

    def __enter__(self) -> "PfmbReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __len__(self) -> int:
        return self.count

    def record_offset(self, record_index: int) -> int:
        """Byte offset of uint64 record_len for this record (then +8 → PFM1 magic)."""
        if record_index < 0 or record_index >= self.count:
            raise IndexError(record_index)
        return int(self._offsets[record_index])

    def _record_body_offset(self, record_index: int) -> int:
        return self.record_offset(record_index) + 8

    def read_record(self, record_index: int) -> PfmbRecord:
        """Random read by 0..count-1 (same order as batch write)."""
        body_off = self._record_body_offset(record_index)
        rec_hdr, matches, _ = _decode_record_bytes(
            self._raw, body_off, series_global=self.series_global
        )
        return _pfm_record_to_pfmb_record(record_index, rec_hdr, matches)

    def read_record_header_only(self, record_index: int) -> Dict:
        """Read only record header (binary PFM2 or JSON PFM1); cheap prsm_index lookup."""
        body_off = self._record_body_offset(record_index)
        return _read_record_header_only_bytes(self._raw, body_off)

    def _build_prsm_map(self) -> None:
        m: Dict[int, int] = {}
        for i in range(self.count):
            hdr = self.read_record_header_only(i)
            prsm = int(hdr.get("i", hdr.get("prsm_index", i)))
            m[prsm] = i
        self._prsm_to_record = m

    def read_by_prsm_index(self, prsm_index: int) -> PfmbRecord:
        """Random read by TopPIC prsm number (e.g. prsm123 → 123)."""
        if self._prsm_to_record is None:
            self._build_prsm_map()
        assert self._prsm_to_record is not None
        if prsm_index not in self._prsm_to_record:
            raise KeyError(f"prsm_index {prsm_index} not in bundle")
        return self.read_record(self._prsm_to_record[prsm_index])

    def iter_records(self) -> Iterator[PfmbRecord]:
        for i in range(self.count):
            yield self.read_record(i)

    def to_legacy_dict(self) -> Dict[int, List[Dict]]:
        """{prsm_index: [match_dict, ...]} for evaluate_peak_level compatibility."""
        out: Dict[int, List[Dict]] = {}
        for rec in self.iter_records():
            out[rec.prsm_index] = rec.matches
        return out


def load_pfmb_bundle(path: Path, *, use_mmap: bool = True) -> Dict[int, List[Dict]]:
    """Read entire .pfmb → {prsm_index: matches}. Prefer PfmbReader for single-record access."""
    with PfmbReader(path, use_mmap=use_mmap) as reader:
        return reader.to_legacy_dict()


def summarize_pfmb(path: Path, *, head: int = 8) -> None:
    """Print bundle header + first `head` records (uses offset index when present)."""
    with PfmbReader(path) as reader:
        print(json.dumps(reader.bundle_header, indent=2, ensure_ascii=False))
        print(f"\n--- first {head} records ---")
        for i in range(min(head, reader.count)):
            hdr = reader.read_record_header_only(i)
            prsm = hdr.get("i", hdr.get("prsm_index", "?"))
            pep = str(hdr.get("pep", hdr.get("input_peptide", "")))[:60]
            print(f"  [{i}] prsm={prsm}  matches={hdr.get('n', '?')}  peptide={pep!r}")
        print(f"\n(Total records: {reader.count})")


def export_pfmb_prsm_to_json(pfmb_path: Path, prsm_index: int, out_path: Path) -> None:
    """Decode one PRSM record from a .pfmb into a human-readable JSON file."""
    with PfmbReader(pfmb_path) as reader:
        rec = reader.read_by_prsm_index(prsm_index)
    payload: Dict = {
        "metadata": {**rec.metadata, "input_peptide": rec.peptide},
        "summary": rec.summary,
        "matches": rec.matches,
    }
    if rec.timing is not None:
        payload["timing"] = rec.timing
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PFM 工具：转换 / 查看二进制文件。")
    sub = parser.add_subparsers(dest="cmd")

    p_show = sub.add_parser("show", help="打印 .pfm 头部信息")
    p_show.add_argument("file")

    p_conv = sub.add_parser("to-json", help="转换 .pfm → JSON")
    p_conv.add_argument("file")
    p_conv.add_argument("--out", default=None)

    p_bshow = sub.add_parser(
        "bundle-show",
        help="Print PFMB bundle header + first N records (binary cannot open as text).",
    )
    p_bshow.add_argument("file", help="Path to .pfmb")
    p_bshow.add_argument("--head", type=int, default=8, help="How many records to preview")

    p_bexp = sub.add_parser(
        "bundle-export",
        help="Export one PRSM from .pfmb to readable JSON (for debugging / handoff).",
    )
    p_bexp.add_argument("file", help="Path to .pfmb")
    p_bexp.add_argument("--prsm", type=int, required=True, help="prsm index, e.g. 0")
    p_bexp.add_argument("--out", required=True, help="Output .json path")

    args = parser.parse_args()
    if args.cmd == "show":
        d = read_pfm(Path(args.file))
        print(json.dumps({k: v for k, v in d.items() if k != "matches"}, indent=2, ensure_ascii=False))
        print(f"matches: {len(d['matches'])} 条")
    elif args.cmd == "to-json":
        out = pfm_to_json(Path(args.file), Path(args.out) if args.out else None)
        print(f"written: {out}")
    elif args.cmd == "bundle-show":
        summarize_pfmb(Path(args.file), head=args.head)
    elif args.cmd == "bundle-export":
        export_pfmb_prsm_to_json(Path(args.file), args.prsm, Path(args.out))
        print(f"written: {args.out}")
    else:
        parser.print_help()