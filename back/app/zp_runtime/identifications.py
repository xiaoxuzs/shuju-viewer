"""Business-level identification access backed by committed .zp artifacts."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

from sqlalchemy.orm import Session

from app.zp_runtime.assets import find_active_asset
from app.zp_runtime.core import ZpAssetReadError, ZpRuntimeError
from app.zp_runtime.package import (
    BinaryLayerUnavailableError,
    bottom_up_reader_class,
    top_down_reader_class,
    zp_read_error_classes,
)
from app.zp_runtime.reader_cache import ZpFileIdentity, ZpReaderCacheError, get_reader_handle


@dataclass(frozen=True, slots=True)
class ZpBottomUpOverview:
    summary: dict[str, Any]
    metadata: dict[str, Any]
    quantification_summary: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ZpTopDownOverview:
    summary: dict[str, Any]
    metadata: dict[str, Any]
    interpretation_provenance: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ZpBottomUpMatch:
    identification: dict[str, Any]
    peptide: dict[str, Any] | None
    protein_group: dict[str, Any] | None
    proteins: tuple[dict[str, Any], ...]
    modifications: tuple[dict[str, Any], ...]
    fragment_matches: tuple[dict[str, Any], ...]
    quantification: tuple[dict[str, Any], ...]
    spectrum: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ZpBottomUpPeptide:
    peptide: dict[str, Any]
    identifications: tuple[dict[str, Any], ...]
    proteins: tuple[dict[str, Any], ...]
    protein_groups: tuple[dict[str, Any], ...]
    modifications: tuple[dict[str, Any], ...]
    quantification: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ZpBottomUpProtein:
    protein: dict[str, Any]
    identifications: tuple[dict[str, Any], ...]
    peptides: tuple[dict[str, Any], ...]
    protein_groups: tuple[dict[str, Any], ...]
    quantification: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ZpTopDownPrsm:
    prsm: dict[str, Any]
    proteoform: dict[str, Any] | None
    modifications: tuple[dict[str, Any], ...]
    fragment_matches: tuple[dict[str, Any], ...]
    peaks: tuple[dict[str, Any], ...]
    features: tuple[dict[str, Any], ...]
    spectrum: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ZpTopDownProteoform:
    proteoform: dict[str, Any]
    prsms: tuple[dict[str, Any], ...]
    modifications: tuple[dict[str, Any], ...]
    fragment_matches: tuple[dict[str, Any], ...]
    peaks: tuple[dict[str, Any], ...]
    features: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ZpTopDownProtein:
    sequence_id: str | None
    protein_accession: str | None
    protein_description: str | None
    proteoforms: tuple[dict[str, Any], ...]
    prsms: tuple[dict[str, Any], ...]
    modifications: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ZpExtensionSummary:
    extension_type: str
    extension_version: str
    owner: str | None
    schema_name: str | None
    schema_version: int | str | None
    record_count: int | None


@dataclass(frozen=True, slots=True)
class ZpExtensionPayload:
    extension_type: str
    extension_version: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _BottomUpIndex:
    identifications_by_id: dict[str, dict[str, Any]]
    identifications_by_precursor: dict[str, tuple[dict[str, Any], ...]]
    identifications_by_peptide_id: dict[str, tuple[dict[str, Any], ...]]
    identifications_by_protein_id: dict[str, tuple[dict[str, Any], ...]]
    peptides_by_id: dict[str, dict[str, Any]]
    peptides_by_sequence: dict[str, tuple[dict[str, Any], ...]]
    proteins_by_id: dict[str, dict[str, Any]]
    proteins_by_accession: dict[str, tuple[dict[str, Any], ...]]
    groups_by_id: dict[str, dict[str, Any]]
    groups_by_protein_id: dict[str, tuple[dict[str, Any], ...]]
    modifications_by_identification: dict[str, tuple[dict[str, Any], ...]]
    fragments_by_identification: dict[str, tuple[dict[str, Any], ...]]
    quantification_by_id: dict[str, dict[str, Any]]
    spectra_by_id: dict[str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class _TopDownIndex:
    prsms_by_id: dict[str, dict[str, Any]]
    proteoforms_by_id: dict[str, dict[str, Any]]
    proteoforms_by_sequence_id: dict[str, tuple[dict[str, Any], ...]]
    proteoforms_by_accession: dict[str, tuple[dict[str, Any], ...]]
    prsms_by_proteoform_id: dict[str, tuple[dict[str, Any], ...]]
    modifications_by_prsm_id: dict[str, tuple[dict[str, Any], ...]]
    modifications_by_proteoform_id: dict[str, tuple[dict[str, Any], ...]]
    fragments_by_prsm_id: dict[str, tuple[dict[str, Any], ...]]
    peaks_by_prsm_id: dict[str, tuple[dict[str, Any], ...]]
    features_by_prsm_id: dict[str, tuple[dict[str, Any], ...]]
    spectra_by_id: dict[str, dict[str, Any]]


_T = TypeVar("_T")
_CACHE_LOCK = threading.RLock()
_BUSINESS_READER_CACHE: dict[tuple[str, ZpFileIdentity], Any] = {}
_BOTTOM_UP_INDEX_CACHE: dict[ZpFileIdentity, _BottomUpIndex] = {}
_TOP_DOWN_INDEX_CACHE: dict[ZpFileIdentity, _TopDownIndex] = {}


def clear_identification_runtime_cache() -> None:
    with _CACHE_LOCK:
        _BUSINESS_READER_CACHE.clear()
        _BOTTOM_UP_INDEX_CACHE.clear()
        _TOP_DOWN_INDEX_CACHE.clear()


def get_binary_bottom_up_overview(
    session: Session,
    dataset_id: int,
) -> ZpBottomUpOverview | None:
    asset = find_active_asset(session, dataset_id)
    if asset is None:
        return None
    reader = _business_reader("bottom_up", asset.zp_path)

    def read() -> ZpBottomUpOverview:
        return ZpBottomUpOverview(
            summary=reader.get_bottom_up_summary(),
            metadata=reader.get_metadata(),
            quantification_summary=reader.get_bottom_up_quantification_summary(),
        )

    return _read_or_raise(read)


def get_binary_top_down_overview(
    session: Session,
    dataset_id: int,
) -> ZpTopDownOverview | None:
    asset = find_active_asset(session, dataset_id)
    if asset is None:
        return None
    reader = _business_reader("top_down", asset.zp_path)

    def read() -> ZpTopDownOverview:
        return ZpTopDownOverview(
            summary=reader.get_top_down_summary(),
            metadata=reader.get_metadata(),
            interpretation_provenance=reader.get_top_down_interpretation_provenance(),
        )

    return _read_or_raise(read)


def get_binary_bottom_up_match(
    session: Session,
    dataset_id: int,
    match: dict[str, Any],
) -> ZpBottomUpMatch | None:
    asset = find_active_asset(session, dataset_id, run_id=_int_or_none(match.get("run_id")))
    if asset is None:
        return None
    index = _bottom_up_index(asset.zp_path)
    precursor_id = _match_precursor_id(match)
    if precursor_id is None:
        raise ZpAssetReadError("binary_identification_mapping_missing")
    candidates = index.identifications_by_precursor.get(precursor_id, ())
    if not candidates:
        raise ZpAssetReadError("binary_identification_mapping_missing")

    run_keys = _match_run_keys(match)
    filtered = [
        item
        for item in candidates
        if _normalize_identity(str(item.get("source_run_name") or "")) in run_keys
    ]
    matches = filtered or list(candidates)
    if len(matches) != 1:
        raise ZpAssetReadError("binary_identification_mapping_ambiguous")
    identification = matches[0]
    identification_id = str(identification.get("identification_id") or "")
    protein_ids = tuple(
        str(item)
        for item in identification.get("protein_ids", ())
        if isinstance(item, str)
    )
    quantification = tuple(
        index.quantification_by_id[item]
        for item in identification.get("quantification_ids", ())
        if isinstance(item, str) and item in index.quantification_by_id
    )
    return ZpBottomUpMatch(
        identification=dict(identification),
        peptide=index.peptides_by_id.get(str(identification.get("peptide_id") or "")),
        protein_group=index.groups_by_id.get(str(identification.get("protein_group_id") or "")),
        proteins=tuple(index.proteins_by_id[item] for item in protein_ids if item in index.proteins_by_id),
        modifications=index.modifications_by_identification.get(identification_id, ()),
        fragment_matches=index.fragments_by_identification.get(identification_id, ()),
        quantification=quantification,
        spectrum=index.spectra_by_id.get(str(identification.get("spectrum_id") or "")),
    )


def get_binary_bottom_up_peptide(
    session: Session,
    dataset_id: int,
    sequence: str,
) -> ZpBottomUpPeptide | None:
    asset = find_active_asset(session, dataset_id)
    if asset is None:
        return None
    index = _bottom_up_index(asset.zp_path)
    key = _sequence_key(sequence)
    candidates = index.peptides_by_sequence.get(key, ())
    if not candidates:
        raise ZpAssetReadError("binary_peptide_mapping_missing")
    if len(candidates) != 1:
        raise ZpAssetReadError("binary_peptide_mapping_ambiguous")
    peptide = dict(candidates[0])
    peptide_id = str(peptide.get("peptide_id") or "")
    identifications = index.identifications_by_peptide_id.get(peptide_id, ())
    protein_ids = _string_ids(peptide.get("protein_ids"))
    group_ids = _string_ids(peptide.get("protein_group_ids"))
    identification_ids = tuple(str(item.get("identification_id") or "") for item in identifications)
    return ZpBottomUpPeptide(
        peptide=peptide,
        identifications=identifications,
        proteins=tuple(index.proteins_by_id[item] for item in protein_ids if item in index.proteins_by_id),
        protein_groups=tuple(index.groups_by_id[item] for item in group_ids if item in index.groups_by_id),
        modifications=_flatten_groups(index.modifications_by_identification, identification_ids),
        quantification=_quantification_for_identifications(index, identifications),
    )


def get_binary_bottom_up_protein(
    session: Session,
    dataset_id: int,
    accession: str,
) -> ZpBottomUpProtein | None:
    asset = find_active_asset(session, dataset_id)
    if asset is None:
        return None
    index = _bottom_up_index(asset.zp_path)
    candidates = index.proteins_by_accession.get(_identity_key(accession), ())
    if not candidates:
        raise ZpAssetReadError("binary_protein_mapping_missing")
    if len(candidates) != 1:
        raise ZpAssetReadError("binary_protein_mapping_ambiguous")
    protein = dict(candidates[0])
    protein_id = str(protein.get("protein_id") or "")
    peptide_ids = _string_ids(protein.get("peptide_ids"))
    identifications = index.identifications_by_protein_id.get(protein_id, ())
    return ZpBottomUpProtein(
        protein=protein,
        identifications=identifications,
        peptides=tuple(index.peptides_by_id[item] for item in peptide_ids if item in index.peptides_by_id),
        protein_groups=index.groups_by_protein_id.get(protein_id, ()),
        quantification=_quantification_for_identifications(index, identifications),
    )


def get_binary_top_down_prsm(
    session: Session,
    dataset_id: int,
    prsm_id: int | str,
) -> ZpTopDownPrsm | None:
    asset = find_active_asset(session, dataset_id)
    if asset is None:
        return None
    index = _top_down_index(asset.zp_path)
    prsm = index.prsms_by_id.get(_numeric_text(prsm_id))
    if prsm is None:
        raise ZpAssetReadError("binary_prsm_mapping_missing")
    prsm_id_text = str(prsm.get("prsm_id") or "")
    proteoform_id = str(prsm.get("proteoform_id") or "")
    return ZpTopDownPrsm(
        prsm=dict(prsm),
        proteoform=index.proteoforms_by_id.get(proteoform_id),
        modifications=index.modifications_by_prsm_id.get(prsm_id_text, ()),
        fragment_matches=index.fragments_by_prsm_id.get(prsm_id_text, ()),
        peaks=index.peaks_by_prsm_id.get(prsm_id_text, ()),
        features=index.features_by_prsm_id.get(prsm_id_text, ()),
        spectrum=index.spectra_by_id.get(str(prsm.get("spectrum_id") or "")),
    )


def get_binary_top_down_proteoform(
    session: Session,
    dataset_id: int,
    proteoform_id: int | str,
    *,
    sequence_id: int | str | None = None,
) -> ZpTopDownProteoform | None:
    asset = find_active_asset(session, dataset_id)
    if asset is None:
        return None
    index = _top_down_index(asset.zp_path)
    proteoform = _top_down_proteoform_match(index, proteoform_id, sequence_id)
    proteoform_id_text = str(proteoform.get("proteoform_id") or "")
    prsms = index.prsms_by_proteoform_id.get(proteoform_id_text, ())
    prsm_ids = tuple(str(item.get("prsm_id") or "") for item in prsms)
    return ZpTopDownProteoform(
        proteoform=dict(proteoform),
        prsms=prsms,
        modifications=index.modifications_by_proteoform_id.get(proteoform_id_text, ()),
        fragment_matches=_flatten_groups(index.fragments_by_prsm_id, prsm_ids),
        peaks=_flatten_groups(index.peaks_by_prsm_id, prsm_ids),
        features=_flatten_groups(index.features_by_prsm_id, prsm_ids),
    )


def get_binary_top_down_protein(
    session: Session,
    dataset_id: int,
    *,
    sequence_id: int | str | None = None,
    sequence_name: str | None = None,
) -> ZpTopDownProtein | None:
    asset = find_active_asset(session, dataset_id)
    if asset is None:
        return None
    index = _top_down_index(asset.zp_path)
    proteoforms: tuple[dict[str, Any], ...] = ()
    if sequence_id is not None:
        proteoforms = index.proteoforms_by_sequence_id.get(_numeric_text(sequence_id), ())
    if not proteoforms and sequence_name:
        proteoforms = index.proteoforms_by_accession.get(_identity_key(sequence_name), ())
    if not proteoforms:
        raise ZpAssetReadError("binary_protein_mapping_missing")
    proteoform_ids = tuple(str(item.get("proteoform_id") or "") for item in proteoforms)
    prsms = _flatten_groups(index.prsms_by_proteoform_id, proteoform_ids)
    return ZpTopDownProtein(
        sequence_id=str(proteoforms[0].get("sequence_id") or "") or None,
        protein_accession=str(proteoforms[0].get("protein_accession") or "") or None,
        protein_description=proteoforms[0].get("protein_description"),
        proteoforms=proteoforms,
        prsms=prsms,
        modifications=_flatten_groups(index.modifications_by_proteoform_id, proteoform_ids),
    )


def get_binary_extension_summaries(
    session: Session,
    dataset_id: int,
) -> tuple[ZpExtensionSummary, ...] | None:
    asset = find_active_asset(session, dataset_id)
    if asset is None:
        return None
    extensions = _read_extensions(asset.zp_path)
    return tuple(_extension_summary(item) for item in extensions)


def get_binary_extension_payload(
    session: Session,
    dataset_id: int,
    extension_type: str,
) -> ZpExtensionPayload | None:
    asset = find_active_asset(session, dataset_id)
    if asset is None:
        return None
    for item in _read_extensions(asset.zp_path):
        if str(item.extension_type) == extension_type:
            payload = item.payload if isinstance(item.payload, dict) else {}
            return ZpExtensionPayload(
                extension_type=str(item.extension_type),
                extension_version=str(item.extension_version),
                payload=dict(payload),
            )
    raise ZpAssetReadError("binary_extension_not_found")


def _business_reader(kind: str, path: Path) -> Any:
    try:
        handle = get_reader_handle(path)
    except ZpReaderCacheError as exc:
        raise ZpAssetReadError(str(exc)) from exc
    cache_key = (kind, handle.identity)
    with _CACHE_LOCK:
        cached = _BUSINESS_READER_CACHE.get(cache_key)
        if cached is not None:
            return cached
        try:
            reader_class = bottom_up_reader_class() if kind == "bottom_up" else top_down_reader_class()
            reader = reader_class(Path(handle.identity.path))
        except (BinaryLayerUnavailableError, ZpReaderCacheError) as exc:
            raise ZpAssetReadError(str(exc)) from exc
        except zp_read_error_classes() as exc:
            raise ZpAssetReadError("binary_zp_unreadable") from exc
        _BUSINESS_READER_CACHE[cache_key] = reader
        return reader


def _bottom_up_index(path: Path) -> _BottomUpIndex:
    handle = _reader_handle(path)
    with _CACHE_LOCK:
        cached = _BOTTOM_UP_INDEX_CACHE.get(handle.identity)
        if cached is not None:
            return cached
    _business_reader("bottom_up", path)

    def read() -> _BottomUpIndex:
        with handle.lock:
            extensions = tuple(handle.reader.read_extensions())
            spectra = tuple(handle.reader.read_spectra())
        payloads = {
            item.extension_type: item.payload
            for item in extensions
            if str(item.extension_type).startswith("bottom_up_")
        }
        identifications = tuple(_records(payloads, "bottom_up_identifications"))
        peptides = _records(payloads, "bottom_up_peptides")
        proteins = _records(payloads, "bottom_up_proteins")
        groups = _records(payloads, "bottom_up_protein_groups")
        built = _BottomUpIndex(
            identifications_by_id=_by_id(identifications, "identification_id"),
            identifications_by_precursor=_identifications_by_precursor(identifications),
            identifications_by_peptide_id=_group_by_id(identifications, "peptide_id"),
            identifications_by_protein_id=_group_by_member(identifications, "protein_ids"),
            peptides_by_id=_by_id(peptides, "peptide_id"),
            peptides_by_sequence=_group_by_identity(peptides, "sequence", key_func=_sequence_key),
            proteins_by_id=_by_id(proteins, "protein_id"),
            proteins_by_accession=_group_by_identity(proteins, "accession", key_func=_identity_key),
            groups_by_id=_by_id(groups, "protein_group_id"),
            groups_by_protein_id=_group_by_member(groups, "member_protein_ids"),
            modifications_by_identification=_group_by_id(
                _records(payloads, "bottom_up_modifications"),
                "identification_id",
            ),
            fragments_by_identification=_group_by_id(
                _records(payloads, "bottom_up_fragment_matches"),
                "identification_id",
            ),
            quantification_by_id=_by_id(_records(payloads, "bottom_up_quantification"), "quantification_id"),
            spectra_by_id={
                str(item.spectrum_id): {
                    "spectrum_id": str(item.spectrum_id),
                    "scan_number": int(item.scan_number),
                    "native_id": str(item.native_id),
                    "ms_level": int(item.ms_level),
                    "run_id": str(item.run_id),
                    "rt_seconds": float(item.rt),
                }
                for item in spectra
            },
        )
        return built

    built = _read_or_raise(read)
    with _CACHE_LOCK:
        _BOTTOM_UP_INDEX_CACHE[handle.identity] = built
    return built


def _top_down_index(path: Path) -> _TopDownIndex:
    handle = _reader_handle(path)
    with _CACHE_LOCK:
        cached = _TOP_DOWN_INDEX_CACHE.get(handle.identity)
        if cached is not None:
            return cached
    _business_reader("top_down", path)

    def read() -> _TopDownIndex:
        with handle.lock:
            extensions = tuple(handle.reader.read_extensions())
            spectra = tuple(handle.reader.read_spectra())
        payloads = {
            item.extension_type: item.payload
            for item in extensions
            if str(item.extension_type).startswith("top_down_")
        }
        prsms = _records(payloads, "top_down_prsms")
        proteoforms = _records(payloads, "top_down_proteoforms")
        fragments = _records(payloads, "top_down_fragment_matches")
        peaks = _records(payloads, "top_down_fragment_matches", record_key="peaks")
        features = _records(payloads, "top_down_features")
        modifications = _records(payloads, "top_down_modifications")
        built = _TopDownIndex(
            prsms_by_id=_by_id(prsms, "prsm_id"),
            proteoforms_by_id=_by_id(proteoforms, "proteoform_id"),
            proteoforms_by_sequence_id=_group_by_identity(proteoforms, "sequence_id", key_func=_numeric_text),
            proteoforms_by_accession=_group_by_identity(proteoforms, "protein_accession", key_func=_identity_key),
            prsms_by_proteoform_id=_group_by_id(prsms, "proteoform_id"),
            modifications_by_prsm_id=_group_by_id(modifications, "prsm_id"),
            modifications_by_proteoform_id=_group_by_id(modifications, "proteoform_id"),
            fragments_by_prsm_id=_group_by_id(fragments, "prsm_id"),
            peaks_by_prsm_id=_group_by_id(peaks, "prsm_id"),
            features_by_prsm_id=_group_by_id(features, "prsm_id"),
            spectra_by_id={
                str(item.spectrum_id): {
                    "spectrum_id": str(item.spectrum_id),
                    "scan_number": int(item.scan_number),
                    "native_id": str(item.native_id),
                    "ms_level": int(item.ms_level),
                    "run_id": str(item.run_id),
                    "rt_seconds": float(item.rt),
                }
                for item in spectra
            },
        )
        return built

    built = _read_or_raise(read)
    with _CACHE_LOCK:
        _TOP_DOWN_INDEX_CACHE[handle.identity] = built
    return built


def _reader_handle(path: Path) -> Any:
    try:
        return get_reader_handle(path)
    except ZpReaderCacheError as exc:
        raise ZpAssetReadError(str(exc)) from exc


def _read_or_raise(operation: Callable[[], _T]) -> _T:
    try:
        return operation()
    except ZpRuntimeError:
        raise
    except (BinaryLayerUnavailableError, ZpReaderCacheError) as exc:
        raise ZpAssetReadError(str(exc)) from exc
    except zp_read_error_classes() as exc:
        raise ZpAssetReadError("binary_zp_unreadable") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise ZpAssetReadError("binary_zp_invalid") from exc


def _records(
    payloads: dict[str, dict[str, Any]],
    extension_type: str,
    *,
    record_key: str = "records",
) -> tuple[dict[str, Any], ...]:
    payload = payloads.get(extension_type)
    if payload is None:
        return ()
    records = payload.get(record_key)
    if not isinstance(records, list):
        return ()
    return tuple(dict(item) for item in records if isinstance(item, dict))


def _by_id(records: tuple[dict[str, Any], ...], field_name: str) -> dict[str, dict[str, Any]]:
    return {
        str(item[field_name]): dict(item)
        for item in records
        if isinstance(item.get(field_name), str)
    }


def _group_by_identity(
    records: tuple[dict[str, Any], ...],
    field_name: str,
    *,
    key_func: Callable[[Any], str],
) -> dict[str, tuple[dict[str, Any], ...]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        value = item.get(field_name)
        if value is None:
            continue
        key = key_func(value)
        if key:
            grouped.setdefault(key, []).append(dict(item))
    return {key: tuple(values) for key, values in grouped.items()}


def _group_by_id(records: tuple[dict[str, Any], ...], field_name: str) -> dict[str, tuple[dict[str, Any], ...]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        value = item.get(field_name)
        if isinstance(value, str):
            grouped.setdefault(value, []).append(dict(item))
    return {key: tuple(values) for key, values in grouped.items()}


def _group_by_member(records: tuple[dict[str, Any], ...], field_name: str) -> dict[str, tuple[dict[str, Any], ...]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        for value in _string_ids(item.get(field_name)):
            grouped.setdefault(value, []).append(dict(item))
    return {key: tuple(values) for key, values in grouped.items()}


def _flatten_groups(
    groups: dict[str, tuple[dict[str, Any], ...]],
    ids: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for identifier in ids:
        for item in groups.get(identifier, ()):
            key = repr(sorted(item.items(), key=lambda part: str(part[0])))
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(item))
    return tuple(out)


def _quantification_for_identifications(
    index: _BottomUpIndex,
    identifications: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    ids: list[str] = []
    for identification in identifications:
        ids.extend(_string_ids(identification.get("quantification_ids")))
    return tuple(index.quantification_by_id[item] for item in ids if item in index.quantification_by_id)


def _identifications_by_precursor(
    records: tuple[dict[str, Any], ...],
) -> dict[str, tuple[dict[str, Any], ...]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        value = item.get("source_precursor_id")
        if isinstance(value, str) and value:
            grouped.setdefault(value, []).append(dict(item))
    return {key: tuple(values) for key, values in grouped.items()}


def _match_precursor_id(match: dict[str, Any]) -> str | None:
    metadata = _json_object(match.get("extra_metadata"))
    value = metadata.get("precursor_id")
    return str(value) if value else None


def _match_run_keys(match: dict[str, Any]) -> set[str]:
    metadata = _json_object(match.get("run_metadata"))
    values = {
        match.get("run_name"),
        match.get("file_path"),
        metadata.get("diann_run_name"),
        metadata.get("run_name"),
        metadata.get("mzml_file_path"),
        metadata.get("raw_file_path"),
    }
    return {
        _normalize_identity(str(item))
        for item in values
        if isinstance(item, str) and item.strip()
    }


def _normalize_identity(value: str) -> str:
    text = value.replace("\\", "/").strip().casefold()
    path_name = Path(text).name
    return path_name or text


def _identity_key(value: Any) -> str:
    return str(value).strip().casefold()


def _sequence_key(value: Any) -> str:
    return str(value).strip().upper()


def _numeric_text(value: Any) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value).strip()


def _string_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)


def _top_down_proteoform_match(
    index: _TopDownIndex,
    proteoform_id: int | str,
    sequence_id: int | str | None,
) -> dict[str, Any]:
    source_id = _numeric_text(proteoform_id)
    if sequence_id is not None:
        composite = f"{_numeric_text(sequence_id)}:{source_id}"
        match = index.proteoforms_by_id.get(composite)
        if match is not None:
            return match
    match = index.proteoforms_by_id.get(source_id)
    if match is not None:
        return match
    raise ZpAssetReadError("binary_proteoform_mapping_missing")


def _read_extensions(path: Path) -> tuple[Any, ...]:
    handle = _reader_handle(path)

    def read() -> tuple[Any, ...]:
        with handle.lock:
            return tuple(handle.reader.read_extensions())

    return _read_or_raise(read)


def _extension_summary(item: Any) -> ZpExtensionSummary:
    payload = item.payload if isinstance(item.payload, dict) else {}
    record_count = payload.get("record_count")
    return ZpExtensionSummary(
        extension_type=str(item.extension_type),
        extension_version=str(item.extension_version),
        owner=payload.get("owner") if isinstance(payload.get("owner"), str) else None,
        schema_name=payload.get("schema_name") if isinstance(payload.get("schema_name"), str) else None,
        schema_version=payload.get("schema_version"),
        record_count=record_count if isinstance(record_count, int) else None,
    )


def _json_object(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
