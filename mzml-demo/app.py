"""
Standalone demo: mzML in-memory viewer + TopPIC `prsm*.js` interpreter.

Not integrated into the main viewer. Run with:

    python app.py --mzml <path/to.mzML> --data <dir/with/prsm*.js>

Then open http://127.0.0.1:8765/ in a browser.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pyteomics import mzml


# ---------------------------------------------------------------------------
# In-memory mzML store
# ---------------------------------------------------------------------------

_SCAN_RE = re.compile(r"scan=(\d+)")


class MzmlStore:
    """Holds every spectrum of one mzML file in memory, keyed by scan number."""

    def __init__(self) -> None:
        self.path: Path | None = None
        self.spectra: dict[int, dict[str, Any]] = {}

    def load(self, path: Path) -> None:
        self.path = path.resolve()
        self.spectra = {}
        print(f"[mzml] loading: {self.path}", flush=True)
        count = 0
        with mzml.read(str(self.path)) as reader:
            for spec in reader:
                scan = _parse_scan(spec.get("id", ""))
                if scan is None:
                    continue
                self.spectra[scan] = _extract_spectrum(spec, scan)
                count += 1
                if count % 500 == 0:
                    print(f"[mzml]   {count} spectra loaded", flush=True)
        print(f"[mzml] done: {count} spectra", flush=True)

    def status(self) -> dict[str, Any]:
        return {
            "path": str(self.path) if self.path else None,
            "loaded_scans": len(self.spectra),
            "ms1_count": sum(1 for s in self.spectra.values() if s["ms_level"] == 1),
            "ms2_count": sum(1 for s in self.spectra.values() if s["ms_level"] == 2),
        }


def _parse_scan(native_id: str) -> int | None:
    m = _SCAN_RE.search(native_id or "")
    return int(m.group(1)) if m else None


def _rt_seconds(spec: dict[str, Any]) -> float:
    for s in spec.get("scanList", {}).get("scan", []):
        t = s.get("scan start time")
        if t is None:
            continue
        unit = str(getattr(t, "unit_info", "")).lower()
        val = float(t)
        return val * 60.0 if "minute" in unit else val
    return 0.0


def _extract_precursor(spec: dict[str, Any]) -> dict[str, Any] | None:
    precs = spec.get("precursorList", {}).get("precursor", [])
    if not precs:
        return None
    p = precs[0]
    iso = p.get("isolationWindow", {}) or {}
    sel_list = p.get("selectedIonList", {}).get("selectedIon", [])
    sel = sel_list[0] if sel_list else {}

    parent_scan = _parse_scan(p.get("spectrumRef") or "")

    def _f(d: dict[str, Any], *keys: str) -> float | None:
        for k in keys:
            if k in d and d[k] is not None:
                try:
                    return float(d[k])
                except (TypeError, ValueError):
                    return None
        return None

    def _i(d: dict[str, Any], *keys: str) -> int | None:
        v = _f(d, *keys)
        return int(v) if v is not None else None

    return {
        "parent_scan": parent_scan,
        "target_mz": _f(iso, "isolation window target m/z"),
        "lower_offset": _f(iso, "isolation window lower offset"),
        "upper_offset": _f(iso, "isolation window upper offset"),
        "selected_mz": _f(sel, "selected ion m/z"),
        "charge": _i(sel, "charge state"),
    }


def _extract_spectrum(spec: dict[str, Any], scan: int) -> dict[str, Any]:
    mz_arr = spec.get("m/z array")
    int_arr = spec.get("intensity array")
    return {
        "scan": scan,
        "ms_level": int(spec.get("ms level", 1)),
        "rt_seconds": _rt_seconds(spec),
        "mz": mz_arr.tolist() if mz_arr is not None else [],
        "intensity": int_arr.tolist() if int_arr is not None else [],
        "precursor": _extract_precursor(spec),
    }


# ---------------------------------------------------------------------------
# prsm.js parser  (TopPIC HTML output format, same as prsm0.js)
# ---------------------------------------------------------------------------

_PRSM_HEAD = re.compile(r"^\s*prsm_data\s*=\s*")


def load_prsm_js(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    m = _PRSM_HEAD.match(text)
    if not m:
        raise ValueError(f"not a prsm_data file: {path}")
    body = text[m.end():].strip()
    if body.endswith(";"):
        body = body[:-1]
    return json.loads(body)


def _as_list(obj: Any) -> list:
    if obj is None:
        return []
    return obj if isinstance(obj, list) else [obj]


def combine_payload(prsm_data: dict[str, Any], store: MzmlStore) -> dict[str, Any]:
    prsm = prsm_data["prsm"]
    header = prsm["ms"]["ms_header"]

    ms2_scan = int(str(header["scans"]).split()[0])
    ms1_scan_raw = header.get("ms1_scans", "") or ""
    ms1_scan = int(str(ms1_scan_raw).split()[0]) if str(ms1_scan_raw).strip() else None

    ms2_raw = store.spectra.get(ms2_scan)
    if ms2_raw is None:
        raise HTTPException(404, f"MS2 scan {ms2_scan} not in mzML (file={store.path})")

    if ms1_scan is None and ms2_raw.get("precursor", {}).get("parent_scan"):
        ms1_scan = ms2_raw["precursor"]["parent_scan"]
    ms1_raw = store.spectra.get(ms1_scan) if ms1_scan else None

    # deconvoluted peaks from prsm.js
    deconv_peaks = _as_list(prsm["ms"]["peaks"].get("peak"))
    matched_flat: list[dict[str, Any]] = []
    deconv_out: list[dict[str, Any]] = []
    for p in deconv_peaks:
        item = {
            "peak_id": int(p["peak_id"]),
            "monoisotopic_mass": float(p["monoisotopic_mass"]),
            "monoisotopic_mz": float(p["monoisotopic_mz"]),
            "charge": int(p["charge"]),
            "intensity": float(p["intensity"]),
            "matched": False,
        }
        mi = p.get("matched_ions")
        if mi:
            item["matched"] = True
            for ion in _as_list(mi.get("matched_ion")):
                matched_flat.append({
                    **item,
                    "ion_type": ion.get("ion_type"),
                    "ion_position": int(ion.get("ion_position", 0)),
                    "ion_display_position": int(ion.get("ion_display_position", 0)),
                    "theoretical_mass": float(ion.get("theoretical_mass", 0.0)),
                    "ppm": float(ion.get("ppm", 0.0)),
                    "match_shift": float(ion.get("match_shift", 0.0)),
                })
        deconv_out.append(item)

    annotated = prsm.get("annotated_protein", {})
    annotation = annotated.get("annotation", {})

    return {
        "summary": {
            "prsm_id": prsm.get("prsm_id"),
            "p_value": prsm.get("p_value"),
            "e_value": prsm.get("e_value"),
            "fdr": prsm.get("fdr"),
            "matched_peak_number": prsm.get("matched_peak_number"),
            "matched_fragment_number": prsm.get("matched_fragment_number"),
            "sequence_name": annotated.get("sequence_name"),
            "sequence_description": annotated.get("sequence_description"),
            "proteoform_mass": annotated.get("proteoform_mass"),
            "n_acetylation": annotated.get("n_acetylation"),
            "precursor_mass": header.get("precursor_mono_mass"),
            "precursor_charge": header.get("precursor_charge"),
            "precursor_mz": header.get("precursor_mz"),
            "ms1_scan": ms1_scan,
            "ms2_scan": ms2_scan,
        },
        "ms1": {
            "scan": ms1_scan,
            "rt_seconds": ms1_raw["rt_seconds"] if ms1_raw else None,
            "mz": ms1_raw["mz"] if ms1_raw else [],
            "intensity": ms1_raw["intensity"] if ms1_raw else [],
            "precursor": ms2_raw.get("precursor"),
            "not_found": ms1_raw is None,
        },
        "ms2": {
            "scan": ms2_scan,
            "rt_seconds": ms2_raw["rt_seconds"],
            "mz": ms2_raw["mz"],
            "intensity": ms2_raw["intensity"],
            "deconv_peaks": deconv_out,
            "matched_peaks": matched_flat,
        },
        "annotation": {
            "annotated_seq": annotation.get("annotated_seq"),
            "protein_length": annotation.get("protein_length"),
            "first_residue_position": annotation.get("first_residue_position"),
            "last_residue_position": annotation.get("last_residue_position"),
            "residue": annotation.get("residue", []),
            "cleavage": annotation.get("cleavage", []),
            "mass_shift": annotation.get("mass_shift"),
        },
    }


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

STORE = MzmlStore()
DATA_DIR: Path = Path(__file__).parent / "data"

app = FastAPI(title="mzML + prsm.js demo")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/mzml/status")
def mzml_status() -> dict[str, Any]:
    return STORE.status()


@app.get("/api/prsm/list")
def prsm_list() -> list[str]:
    if not DATA_DIR.exists():
        return []
    return sorted(p.name for p in DATA_DIR.glob("prsm*.js"))


@app.get("/api/prsm/view")
def prsm_view(file: str = Query(..., description="prsm*.js file name inside data dir")) -> Any:
    safe_name = Path(file).name  # prevent path traversal
    prsm_path = DATA_DIR / safe_name
    if not prsm_path.exists():
        raise HTTPException(404, f"not found: {safe_name}")
    try:
        raw = load_prsm_js(prsm_path)
    except Exception as exc:
        raise HTTPException(400, f"parse error: {exc}") from exc
    return JSONResponse(combine_payload(raw, STORE))


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mzml", required=True, help="path to mzML file")
    parser.add_argument("--data", default=str(Path(__file__).parent / "data"),
                        help="directory containing prsm*.js files")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    return parser.parse_args(argv)


def main() -> None:
    import uvicorn

    args = parse_args()
    mzml_path = Path(args.mzml)
    if not mzml_path.exists():
        print(f"mzML not found: {mzml_path}", file=sys.stderr)
        sys.exit(2)

    global DATA_DIR
    DATA_DIR = Path(args.data).resolve()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    STORE.load(mzml_path)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
