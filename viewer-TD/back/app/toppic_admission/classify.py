"""Decision tree: filesystem signals → admission route."""

from __future__ import annotations

from pathlib import Path

from . import reject as reject_codes
from .pairing import pair_pipeline_runs
from .reject import reject_message
from .signals import collect_signals
from .types import (
    AdmissionDecision,
    AdmissionEvidence,
    AdmissionRoute,
    DirectIngestShape,
    PfmbIngestSource,
    SignalSnapshot,
)


def _evidence_from_signals(signals: SignalSnapshot) -> AdmissionEvidence:
    return AdmissionEvidence(
        has_topfd=signals.has_topfd,
        has_toppic_dir=signals.has_toppic_dir,
        has_prsm_xml=bool(signals.prsm_xml_files),
        has_ms2_msalign=bool(signals.ms2_msalign_files),
        has_mzml=bool(signals.mzml_files),
        prsm_file_count=signals.prsm_file_count,
        is_toppic_html_tree=signals.is_toppic_html_tree,
    )


def _unsupported(
    ingest_root: Path,
    signals: SignalSnapshot,
    *,
    code: str,
    detail: str | None = None,
    notes: tuple[str, ...] = (),
) -> AdmissionDecision:
    evidence = _evidence_from_signals(signals)
    if notes:
        evidence = AdmissionEvidence(
            has_topfd=evidence.has_topfd,
            has_toppic_dir=evidence.has_toppic_dir,
            has_prsm_xml=evidence.has_prsm_xml,
            has_ms2_msalign=evidence.has_ms2_msalign,
            has_mzml=evidence.has_mzml,
            prsm_file_count=evidence.prsm_file_count,
            is_toppic_html_tree=evidence.is_toppic_html_tree,
            notes=notes,
        )
    return AdmissionDecision(
        route=AdmissionRoute.UNSUPPORTED,
        ingest_root=ingest_root.resolve(),
        evidence=evidence,
        reject_code=code,
        reject_reason=reject_message(code, detail=detail),
    )


def _has_pipeline_inputs(signals: SignalSnapshot) -> bool:
    return (
        signals.has_topfd
        and signals.has_toppic_dir
        and bool(signals.prsm_xml_files)
        and bool(signals.ms2_msalign_files)
        and bool(signals.mzml_files)
    )


def classify_from_signals(ingest_root: Path, signals: SignalSnapshot) -> AdmissionDecision:
    """Classify admission from a pre-collected signal snapshot (test hook)."""
    root = ingest_root.resolve()

    if signals.is_bu_diann_layout:
        return _unsupported(root, signals, code=reject_codes.REJECT_BU_DIANN)

    if signals.has_supported_prsm_files:
        if signals.is_toppic_html_tree:
            return AdmissionDecision(
                route=AdmissionRoute.DIRECT_INGEST,
                ingest_root=root,
                evidence=_evidence_from_signals(signals),
                direct_shape=DirectIngestShape.TOPPIC_HTML,
            )
        if signals.prsm_bundle_dir is not None:
            return AdmissionDecision(
                route=AdmissionRoute.DIRECT_INGEST,
                ingest_root=root,
                evidence=_evidence_from_signals(signals),
                direct_shape=DirectIngestShape.PRSM_BUNDLE,
            )
        return _unsupported(root, signals, code=reject_codes.REJECT_PRSM_LAYOUT)

    if _has_pipeline_inputs(signals):
        pairing = pair_pipeline_runs(
            prsm_xml_files=signals.prsm_xml_files,
            ms2_msalign_files=signals.ms2_msalign_files,
            mzml_files=signals.mzml_files,
        )
        if pairing.reject_code:
            return _unsupported(
                root,
                signals,
                code=pairing.reject_code,
                detail=pairing.reject_detail,
            )
        if pairing.triples:
            return AdmissionDecision(
                route=AdmissionRoute.NEED_PFMB,
                ingest_root=root,
                evidence=_evidence_from_signals(signals),
                pfmb_source=PfmbIngestSource.XML_MSALIGN,
                run_triples=pairing.triples,
            )

    if signals.mzml_files and not signals.has_topfd and not signals.has_toppic_dir:
        return _unsupported(root, signals, code=reject_codes.REJECT_ONLY_MZML)

    if signals.has_topfd or signals.has_toppic_dir or signals.prsm_xml_files or signals.ms2_msalign_files:
        if not signals.has_topfd:
            return _unsupported(root, signals, code=reject_codes.REJECT_MISSING_TOPFD)
        if not signals.has_toppic_dir:
            return _unsupported(root, signals, code=reject_codes.REJECT_MISSING_TOPPIC)
        if not signals.prsm_xml_files:
            return _unsupported(root, signals, code=reject_codes.REJECT_MISSING_PRSM_XML)
        if not signals.ms2_msalign_files:
            return _unsupported(root, signals, code=reject_codes.REJECT_MISSING_MS2_MSALIGN)
        if not signals.mzml_files:
            return _unsupported(root, signals, code=reject_codes.REJECT_MISSING_MZML)

    return _unsupported(root, signals, code=reject_codes.REJECT_UNKNOWN_LAYOUT)


def classify_admission(ingest_root: Path) -> AdmissionDecision:
    """Classify a resolved ingest root (read-only)."""
    return classify_from_signals(ingest_root, collect_signals(ingest_root))
