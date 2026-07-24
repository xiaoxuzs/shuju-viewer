"""User-selected dataset import types shared by HTTP and worker layers."""

from __future__ import annotations

from enum import Enum


class ImportType(str, Enum):
    RAW_ONLY = "RAW_ONLY"
    MZML_ONLY = "MZML_ONLY"
    TOPPIC = "TOPPIC"
    PRSM = "PRSM"
    DIA_NN = "DIA_NN"
    DIA_CLIP = "DIA_CLIP"
