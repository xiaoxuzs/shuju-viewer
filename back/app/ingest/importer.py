"""End-to-end ingest of a TopPIC output folder.

The dataset root is expected to look like::

    <root>/
      topfd/{ms1_json,ms2_json}/spectrum*.js
      toppic_prsm_cutoff/data_js/
      toppic_proteoform_cutoff/data_js/

For every cutoff (prsm / proteoform) we load the aggregated ``proteins.js``
to populate Protein + Proteoform rows, then walk ``prsms/prsm*.js`` one by
one to fill PrSM details.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from tqdm import tqdm

from app.core.logging import get_logger
from app.ingest.utils import best_prsm, ensure_list, to_float, to_int
from app.models import Cutoff, Dataset, Protein, Proteoform, Prsm
from app.services.js_parser import load_js_object

log = get_logger(__name__)


CUTOFF_DIRS = {
    "prsm": "toppic_prsm_cutoff",
    "proteoform": "toppic_proteoform_cutoff",
}


@dataclass
class IngestStats:
    dataset_id: int
    proteins: int = 0
    proteoforms: int = 0
    prsms: int = 0


def ingest_dataset(
    session: Session,
    *,
    root: Path,
    slug: str,
    name: str,
    description: str | None = None,
    clear_existing: bool = True,
) -> IngestStats:
    """Import a dataset, returning the populated counts."""
    root = root.resolve()
    if not root.exists():
        raise FileNotFoundError(root)

    dataset = session.execute(select(Dataset).where(Dataset.slug == slug)).scalar_one_or_none()
    if dataset and clear_existing:
        log.warning("dataset %s already exists, clearing rows first", slug)
        session.delete(dataset)
        session.flush()
        dataset = None

    if dataset is None:
        dataset = Dataset(slug=slug, name=name, description=description, source_path=str(root))
        session.add(dataset)
        session.flush()

    stats = IngestStats(dataset_id=dataset.id)
    for kind, folder_name in CUTOFF_DIRS.items():
        cutoff_root = root / folder_name / "data_js"
        if not cutoff_root.exists():
            log.warning("cutoff folder missing: %s", cutoff_root)
            continue
        cutoff = Cutoff(
            dataset=dataset,
            kind=kind,
            label=f"TopPIC {kind} cutoff",
            data_path=str(cutoff_root),
        )
        session.add(cutoff)
        session.flush()
        _import_cutoff(session, cutoff=cutoff, cutoff_root=cutoff_root, stats=stats)
        session.commit()

    return stats


def _import_cutoff(session: Session, *, cutoff: Cutoff, cutoff_root: Path, stats: IngestStats) -> None:
    proteins_file = cutoff_root / "proteins.js"
    if not proteins_file.exists():
        log.error("proteins.js missing in %s, skipping cutoff", cutoff_root)
        return

    log.info("[%s] loading proteins.js (%.1f MB)", cutoff.kind, proteins_file.stat().st_size / 1_048_576)
    proteins_doc = load_js_object(proteins_file)
    protein_list = (
        proteins_doc.get("protein_list", {}).get("proteins", {}).get("protein")
        or proteins_doc.get("prsm_data", {}).get("protein_list", {}).get("proteins", {}).get("protein")
    )
    protein_list = ensure_list(protein_list or [])

    log.info("[%s] inserting %d proteins and their proteoforms", cutoff.kind, len(protein_list))
    protein_rows: dict[int, Protein] = {}
    # proteoform_id is unique **within a protein**, so we key by (sequence_id, proteoform_id).
    proteoform_rows: dict[tuple[int, int], Proteoform] = {}

    for p in protein_list:
        seq_id = to_int(p.get("sequence_id"))
        if seq_id is None:
            continue
        compat_list = ensure_list(p.get("compatible_proteoform"))
        prsm_total = 0
        protein_best_id: int | None = None
        protein_best_e: float | None = None
        for form in compat_list:
            prsm_total += to_int(form.get("prsm_number"), 0) or 0
            form_prsms = ensure_list(form.get("prsm"))
            form_best_id, form_best_e = best_prsm(form_prsms)
            if form_best_id is not None and (
                protein_best_e is None or (form_best_e is not None and form_best_e < protein_best_e)
            ):
                protein_best_id = form_best_id
                protein_best_e = form_best_e

        protein = Protein(
            cutoff_id=cutoff.id,
            sequence_id=seq_id,
            sequence_name=str(p.get("sequence_name", "")),
            sequence_description=p.get("sequence_description"),
            compatible_proteoform_number=to_int(p.get("compatible_proteoform_number"), len(compat_list)) or 0,
            prsm_number=prsm_total,
            best_prsm_id=protein_best_id,
            best_prsm_e_value=protein_best_e,
        )
        session.add(protein)
        session.flush()
        protein_rows[seq_id] = protein
        stats.proteins += 1

        for form in compat_list:
            pf_id = to_int(form.get("proteoform_id"))
            if pf_id is None:
                continue
            form_prsms = ensure_list(form.get("prsm"))
            form_best_id, form_best_e = best_prsm(form_prsms)
            pf_mass = _extract_proteoform_mass(form_prsms)
            proteoform = Proteoform(
                cutoff_id=cutoff.id,
                protein_id=protein.id,
                proteoform_id=pf_id,
                sequence_id=seq_id,
                sequence_name=str(form.get("sequence_name", p.get("sequence_name", ""))),
                proteoform_mass=pf_mass,
                prsm_number=to_int(form.get("prsm_number"), len(form_prsms)) or 0,
                best_prsm_id=form_best_id,
                best_prsm_e_value=form_best_e,
                n_acetylation=None,
                unexpected_shift_number=None,
            )
            session.add(proteoform)
            session.flush()
            proteoform_rows[(seq_id, pf_id)] = proteoform
            stats.proteoforms += 1

    _import_prsms(session, cutoff=cutoff, cutoff_root=cutoff_root, proteoform_rows=proteoform_rows, stats=stats)


def _extract_proteoform_mass(form_prsms: list[dict[str, Any]]) -> float | None:
    for p in form_prsms:
        ap = p.get("annotated_protein")
        if ap and ap.get("proteoform_mass"):
            v = to_float(ap.get("proteoform_mass"))
            if v is not None:
                return v
    return None


def _import_prsms(
    session: Session,
    *,
    cutoff: Cutoff,
    cutoff_root: Path,
    proteoform_rows: dict[tuple[int, int], Proteoform],
    stats: IngestStats,
) -> None:
    prsms_dir = cutoff_root / "prsms"
    if not prsms_dir.exists():
        log.error("prsms/ directory missing in %s, skipping", cutoff_root)
        return

    files = sorted(prsms_dir.glob("prsm*.js"), key=_prsm_sort_key)
    log.info("[%s] importing %d PrSMs", cutoff.kind, len(files))

    buf: list[Prsm] = []
    batch_size = 200

    bar = tqdm(total=len(files), desc=f"{cutoff.kind} PrSMs", unit="prsm", ascii=True)
    try:
        for path in files:
            row = _build_prsm_row(path, cutoff_id=cutoff.id, proteoform_rows=proteoform_rows)
            if row is not None:
                buf.append(row)
                stats.prsms += 1
            if len(buf) >= batch_size:
                session.add_all(buf)
                session.flush()
                buf.clear()
            bar.update(1)
        if buf:
            session.add_all(buf)
            session.flush()
            buf.clear()
    finally:
        try:
            bar.close()
        except Exception:  # noqa: BLE001
            pass


def _prsm_sort_key(path: Path) -> int:
    stem = path.stem  # prsm<ID>
    try:
        return int(stem.removeprefix("prsm"))
    except ValueError:
        return 1 << 30


def _build_prsm_row(
    path: Path, *, cutoff_id: int, proteoform_rows: dict[tuple[int, int], Proteoform]
) -> Prsm | None:
    try:
        doc = load_js_object(path)
    except Exception as exc:  # noqa: BLE001
        log.error("failed to parse %s: %s", path, exc)
        return None

    prsm_root = doc.get("prsm") or doc
    prsm_id = to_int(prsm_root.get("prsm_id"))
    if prsm_id is None:
        return None

    annotated = prsm_root.get("annotated_protein", {}) or {}
    pf_id = to_int(annotated.get("proteoform_id"))
    seq_id = to_int(annotated.get("sequence_id"))
    if pf_id is None or seq_id is None:
        return None
    proteoform = proteoform_rows.get((seq_id, pf_id))
    if proteoform is None:
        return None

    ms = prsm_root.get("ms", {}) or {}
    header = ms.get("ms_header", {}) or {}
    peaks = ms.get("peaks", {}) or {}

    return Prsm(
        cutoff_id=cutoff_id,
        proteoform_id=proteoform.id,
        prsm_id=prsm_id,
        sequence_id=seq_id,
        p_value=to_float(prsm_root.get("p_value")),
        e_value=to_float(prsm_root.get("e_value")),
        fdr=to_float(prsm_root.get("fdr")),
        matched_fragment_number=to_int(prsm_root.get("matched_fragment_number")),
        matched_peak_number=to_int(prsm_root.get("matched_peak_number")),
        spectrum_file_name=header.get("spectrum_file_name"),
        ms1_scans=_as_text(header.get("ms1_scans")),
        ms2_scans=_as_text(header.get("scans")),
        ms1_ids=_as_text(header.get("ms1_ids")),
        ms2_ids=_as_text(header.get("ids")),
        precursor_mono_mass=to_float(header.get("precursor_mono_mass")),
        precursor_charge=to_int(header.get("precursor_charge")),
        precursor_mz=to_float(header.get("precursor_mz")),
        feature_inte=to_float(header.get("feature_inte")),
        proteoform_mass=to_float(annotated.get("proteoform_mass")),
        annotated_protein=annotated or None,
        ms_header=header or None,
        ms_peaks=peaks or None,
    )


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
