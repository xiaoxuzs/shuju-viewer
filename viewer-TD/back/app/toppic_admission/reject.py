"""Stable reject codes and English user-facing messages."""

from __future__ import annotations

REJECT_BU_DIANN = "bu_diann_not_supported"
REJECT_PRSM_LAYOUT = "prsm_files_unrecognized_layout"
REJECT_ONLY_MZML = "only_mzml"
REJECT_MISSING_TOPFD = "missing_topfd"
REJECT_MISSING_TOPPIC = "missing_toppic"
REJECT_MISSING_PRSM_XML = "missing_prsm_xml"
REJECT_MISSING_MS2_MSALIGN = "missing_ms2_msalign"
REJECT_MISSING_MZML = "missing_mzml"
REJECT_UNPAIRED_RUN = "unpaired_run"
REJECT_AMBIGUOUS_PAIRING = "ambiguous_pairing"
REJECT_UNKNOWN_LAYOUT = "unknown_layout"

_MESSAGES: dict[str, str] = {
    REJECT_BU_DIANN: (
        "This folder matches a DIA-NN Bottom-Up layout. "
        "viewer-TD currently supports TopPIC Top-Down datasets only."
    ),
    REJECT_PRSM_LAYOUT: (
        "Supported PrSM detail files (prsm*.js|json|txt) were found, but the folder layout "
        "does not match a TopPIC HTML tree or a PrSM bundle under data/ or data/prsms/."
    ),
    REJECT_ONLY_MZML: (
        "The folder contains mzML spectra files but no TopPIC interpretation outputs: "
        "no supported prsm* files and no complete topfd/ + toppic/ pipeline."
    ),
    REJECT_MISSING_TOPFD: (
        "This TopPIC pipeline folder is missing a topfd/ directory with MS2 msalign files."
    ),
    REJECT_MISSING_TOPPIC: (
        "This TopPIC pipeline folder is missing a toppic/ directory with PrSM XML output."
    ),
    REJECT_MISSING_PRSM_XML: (
        "The toppic/ directory does not contain any *_toppic_prsm.xml files required for PFMB ingest."
    ),
    REJECT_MISSING_MS2_MSALIGN: (
        "The topfd/ directory does not contain any *_ms2.msalign files required for PFMB ingest."
    ),
    REJECT_MISSING_MZML: (
        "No mzML spectra files were found under the dataset root. "
        "TopPIC pipeline imports require at least one *.mzML file."
    ),
    REJECT_UNPAIRED_RUN: (
        "Could not pair every TopPIC PrSM XML file with a matching *_ms2.msalign and mzML file "
        "by run name."
    ),
    REJECT_AMBIGUOUS_PAIRING: (
        "Multiple TopPIC pipeline files map to the same run key; "
        "each run must have exactly one PrSM XML, one MS2 msalign, and one mzML."
    ),
    REJECT_UNKNOWN_LAYOUT: (
        "Unsupported dataset folder layout. Expected either (1) TopPIC HTML output with supported "
        "prsm* detail files, (2) a PrSM bundle under data/ or data/prsms/ with mzML, or "
        "(3) a TopPIC pipeline package with topfd/, toppic/, *_toppic_prsm.xml, *_ms2.msalign, "
        "and mzML."
    ),
}


def reject_message(code: str, *, detail: str | None = None) -> str:
    base = _MESSAGES.get(code, _MESSAGES[REJECT_UNKNOWN_LAYOUT])
    if detail:
        return f"{base} {detail}"
    return base
