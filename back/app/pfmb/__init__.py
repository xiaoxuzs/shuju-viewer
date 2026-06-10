"""PFMB sidecar read modules for the MS2 pre-computed annotation layer.

* :mod:`app.pfmb.index_reader` — reads ``index.json`` (no binary dependency).
* :mod:`app.pfmb.reader` — reads ``results.pfmb`` via the ``pfm`` module
  (imported lazily, only when a reader is constructed).
"""

from app.pfmb.index_reader import IndexReader, SlotItem, strip_mods
from app.pfmb.reader import MatchedIon, PfmbAnnotation, PfmbAnnotationReader

__all__ = [
    "IndexReader",
    "SlotItem",
    "strip_mods",
    "PfmbAnnotationReader",
    "PfmbAnnotation",
    "MatchedIon",
]
