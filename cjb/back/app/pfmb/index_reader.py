"""Read the PFMB sidecar ``index.json`` and expose narrow lookups.

This module is deliberately free of any PFMB *binary* dependency (the external
``pfm`` package). It only reads the plain ``index.json`` shipped with the
``dia-ms2-pipei`` delivery, so it can be built and tested on its own.

``index.json`` layout::

    {"version": "...", "items": [
        {"prsm_index", "source_row", "slot_index", "slot_rt",
         "peptide", "precursor_charge", "apex_slot", ...},
        ...
    ]}

Granularity: one ``source_row`` (one DIA-NN precursor / one ``pos.pkl`` row)
expands to N items, one per retention-time slot (``slot_index`` / ``slot_rt``).

Two narrow lookups are provided:

* :meth:`IndexReader.resolve_source_row` — map a DIA-NN match
  ``(peptide, charge, rt)`` to its ``source_row``. ``peptide`` may carry
  modifications (``C[+57.021464]``); they are stripped before matching because
  ``index.json`` stores the *modified* sequence while DIA-NN parquet matches are
  keyed on the *stripped* sequence. When several source rows share the same
  ``(stripped_peptide, charge)`` the nearest apex ``slot_rt`` to *rt* wins.
* :meth:`IndexReader.get_slots` — list every RT slot of a ``source_row``.

Note on units: ``slot_rt`` is in **seconds** (as produced upstream). The caller
must pass *rt* in the same unit for the disambiguation to be meaningful.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# Strips modification brackets, e.g. "AAAAC[+57.021464]LDK" -> "AAAACLDK".
_MOD_RE = re.compile(r"\[.*?\]")


def strip_mods(sequence: str) -> str:
    """Return *sequence* with any ``[...]`` modification annotations removed."""

    return _MOD_RE.sub("", sequence)


@dataclass(frozen=True, slots=True)
class SlotItem:
    """One retention-time slot of a precursor (one ``index.json`` item)."""

    prsm_index: int
    source_row: int
    slot_index: int
    slot_rt: float
    apex_slot: int | None = None


class IndexReader:
    """Lazy in-memory index over ``index.json`` (built once on first use)."""

    def __init__(self, index_path: Path | str) -> None:
        self._index_path = Path(index_path)
        self._by_source_row: dict[int, list[SlotItem]] = {}
        # (stripped_peptide, charge) -> ordered unique source rows.
        self._by_key: dict[tuple[str, int], list[int]] = {}
        # source_row -> representative (apex) retention time, for disambiguation.
        self._apex_rt: dict[int, float] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with open(self._index_path, encoding="utf-8") as handle:
            data = json.load(handle)

        for item in data["items"]:
            source_row = int(item["source_row"])
            charge = int(item["precursor_charge"])
            slot = SlotItem(
                prsm_index=int(item["prsm_index"]),
                source_row=source_row,
                slot_index=int(item["slot_index"]),
                slot_rt=float(item["slot_rt"]),
                apex_slot=None if item.get("apex_slot") is None else int(item["apex_slot"]),
            )
            slots = self._by_source_row.get(source_row)
            if slots is None:
                slots = []
                self._by_source_row[source_row] = slots
                key = (strip_mods(item["peptide"]), charge)
                self._by_key.setdefault(key, []).append(source_row)
            slots.append(slot)

        for source_row, slots in self._by_source_row.items():
            slots.sort(key=lambda s: s.slot_index)
            self._apex_rt[source_row] = _apex_rt(slots)

        self._loaded = True

    def resolve_source_row(
        self,
        peptide: str,
        charge: int,
        rt: float | None = None,
    ) -> int | None:
        """Return the ``source_row`` for a DIA-NN match, or ``None`` if absent.

        Modifications in *peptide* are stripped before matching. When several
        source rows share ``(stripped_peptide, charge)``, the one whose apex
        ``slot_rt`` is closest to *rt* is returned; if *rt* is ``None`` the first
        registered source row is returned.
        """

        self._ensure_loaded()
        rows = self._by_key.get((strip_mods(peptide), int(charge)))
        if not rows:
            return None
        if len(rows) == 1 or rt is None:
            return rows[0]
        return min(rows, key=lambda sr: abs(self._apex_rt[sr] - rt))

    def get_slots(self, source_row: int) -> list[SlotItem]:
        """Return every RT slot of *source_row*, ordered by ``slot_index``."""

        self._ensure_loaded()
        return list(self._by_source_row.get(int(source_row), ()))

    @property
    def source_row_count(self) -> int:
        """Number of distinct source rows (precursors) in the index."""

        self._ensure_loaded()
        return len(self._by_source_row)


def _apex_rt(slots: list[SlotItem]) -> float:
    """Representative RT of a source row: the apex slot's ``slot_rt``.

    Falls back to the middle slot when ``apex_slot`` is missing or out of range.
    """

    apex_slot = slots[0].apex_slot
    if apex_slot is not None:
        for slot in slots:
            if slot.slot_index == apex_slot:
                return slot.slot_rt
    return slots[len(slots) // 2].slot_rt
