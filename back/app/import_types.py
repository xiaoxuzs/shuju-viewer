"""User-selected dataset import types shared by HTTP and worker layers."""

from __future__ import annotations

from enum import Enum


class ImportType(str, Enum):
    TD_RAW = "TD_RAW"
    TD_MZML = "TD_MZML"
    TD_TOPPIC_HTML = "TD_TOPPIC_HTML"
    TD_PRSM_BUNDLE = "TD_PRSM_BUNDLE"
    TD_TOPPIC_NATIVE = "TD_TOPPIC_NATIVE"
    BU_DIA_NN = "BU_DIA_NN"
    BU_DIA_CLIP = "BU_DIA_CLIP"
    DDA_RAW = "DDA_RAW"

    # Legacy API values remain valid for queued jobs and saved upload sessions.
    RAW_ONLY = "RAW_ONLY"
    MZML_ONLY = "MZML_ONLY"
    TOPPIC = "TOPPIC"
    PRSM = "PRSM"
    DIA_NN = "DIA_NN"
    DIA_CLIP = "DIA_CLIP"
