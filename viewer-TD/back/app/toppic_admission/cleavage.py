"""Build TopPIC-style cleavage annotations from matched fragment ions."""

from __future__ import annotations

from typing import Any


def _as_matched_ion_list(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def build_cleavage(peaks: list[dict[str, Any]], *, protein_length: int) -> list[dict[str, Any]]:
    """Derive cleavage sites from matched B/Y (and related) ions on assembled peaks."""
    b_by_pos: dict[int, list[tuple[str, dict[str, Any]]]] = {}
    y_by_pos: dict[int, list[tuple[str, dict[str, Any]]]] = {}

    for peak in peaks:
        peak_id = str(peak.get("peak_id", ""))
        spec_id = str(peak.get("spec_id", ""))
        peak_charge = str(peak.get("charge", ""))
        for ion in _as_matched_ion_list(peak.get("matched_ions", {}).get("matched_ion")):
            ion_type = str(ion.get("ion_type", "")).upper()
            try:
                ion_position = int(float(str(ion.get("ion_position", ""))))
            except ValueError:
                continue

            matched_peak = {
                "ion_type": ion_type,
                "ion_position": str(ion_position),
                "ion_display_position": str(ion.get("ion_display_position", ion_position)),
                "spec_id": spec_id,
                "peak_id": peak_id,
                "peak_charge": peak_charge,
            }
            if ion_type == "B":
                b_by_pos.setdefault(ion_position, []).append((peak_id, matched_peak))
            else:
                y_pos = protein_length - ion_position
                y_by_pos.setdefault(y_pos, []).append((peak_id, matched_peak))

    cleavages: list[dict[str, Any]] = []
    for position in range(protein_length + 1):
        n_hits = [item for _, item in b_by_pos.get(position, [])]
        c_hits = [item for _, item in y_by_pos.get(position, [])]
        all_hits = n_hits + c_hits
        cleavages.append(
            {
                "position": str(position),
                "exist_n_ion": "1" if n_hits else "0",
                "exist_c_ion": "1" if c_hits else "0",
                "matched_peaks": (
                    None
                    if not all_hits
                    else {"matched_peak": all_hits[0] if len(all_hits) == 1 else all_hits}
                ),
            }
        )
    return cleavages
