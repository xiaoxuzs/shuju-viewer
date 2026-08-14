from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from pyteomics import mass

from app.api.v1.bu import matches as matches_api
from app.bu.services import chromatogram_service, mobility_service, product_xic_service, spectrum_facade, xic_service
from app.schemas import (
    BuChromatogramOut,
    BuMobilitySliceOut,
    BuProductXicBatchIn,
    BuProductXicBatchIonIn,
    BuProductXicRtWindowIn,
)
from app.services import spectrum_memory_wiring
from app.services.mzml_scan_index import (
    ScanIndexMissingError,
    ScanIndexStaleError,
    ScanMetadata,
    ScanMetadataNotFoundError,
)
from app.services.mzml_scan_reader import (
    MzmlFileNotFoundError,
    MzmlIndexError,
    MzmlMappingError,
    SpectrumNotFoundError,
    UnsupportedMzmlError,
)
from app.spectrum_memory.mzml_dataset_bundle import DatasetMzmlBundle


def _match(*, raw_format: str = "mzml") -> dict[str, Any]:
    return {
        "match_id": 1,
        "run_id": 10,
        "sequence": "LLLPGELAK",
        "modified_sequence": "LLLPGELAK",
        "scan_number": -1,
        "precursor_mz": 477.3051452636719,
        "precursor_charge": 2,
        "retention_time": 92.46,
        "extra_metadata": {"rt_start": 92.15, "rt_stop": 93.08},
        "run_metadata": {"raw_format": raw_format},
    }


def _ms2_spec(scan: int = 67726) -> dict[str, Any]:
    sequence = "LLLPGELAK"
    mz = [
        float(mass.fast_mass(sequence[:pos], ion_type="b", charge=1))
        for pos in range(1, 7)
    ]
    mz += [
        float(mass.fast_mass(sequence[-pos:], ion_type="y", charge=1))
        for pos in range(1, 7)
    ]
    return {
        "scan": scan,
        "native_id": f"controllerType=0 controllerNumber=1 scan={scan}",
        "ms_level": 2,
        "rt_seconds": 92.4599 * 60.0,
        "mz": mz,
        "intensity": [1000.0 + i for i in range(len(mz))],
        "precursor": {
            "target_mz": 478.0,
            "lower_offset": 6.5,
            "upper_offset": 6.5,
            "selected_mz": 477.3051,
            "charge": 2,
        },
    }


def _fail(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("unexpected spectrum loading path")


def _scan_metadata(
    scan_number: int,
    *,
    ms_level: int,
    retention_time: float,
) -> ScanMetadata:
    return ScanMetadata(
        scan_number=scan_number,
        native_id=f"scan={scan_number}",
        ms_level=ms_level,
        retention_time=retention_time,
        tic=1000.0,
        bpc=500.0,
        precursor_mz=477.3051 if ms_level == 2 else None,
        isolation_target_mz=478.0 if ms_level == 2 else None,
        isolation_lower_mz=471.5 if ms_level == 2 else None,
        isolation_upper_mz=484.5 if ms_level == 2 else None,
    )


def _install_no_full_load_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spectrum_facade, "get_run_spectra", _fail)
    monkeypatch.setattr(spectrum_memory_wiring, "ensure_mzml_dataset_resident", _fail)
    monkeypatch.setattr(DatasetMzmlBundle, "load", _fail)
    monkeypatch.setattr(
        "app.spectrum_memory.mzml_spectrum_extract.load_mzml_path_to_scan_map",
        _fail,
    )


def test_match_ms2_without_explicit_scan_uses_scan_index_and_indexed_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    find_calls: list[tuple[Any, int, int, float, float, float | None]] = []
    read_calls: list[tuple[Any, int, int, int]] = []

    def find_one(
        session: Any,
        dataset_id: int,
        run_id: int,
        rt: float,
        precursor_mz: float,
        *,
        max_delta_minutes: float | None,
    ) -> ScanMetadata:
        find_calls.append((session, dataset_id, run_id, rt, precursor_mz, max_delta_minutes))
        return _scan_metadata(67726, ms_level=2, retention_time=92.48)

    def get_one(session: Any, dataset_id: int, run_id: int, scan_number: int):
        read_calls.append((session, dataset_id, run_id, scan_number))
        return _ms2_spec(scan_number), False

    monkeypatch.setattr(spectrum_facade, "find_nearest_ms2_scan", find_one)
    monkeypatch.setattr(spectrum_facade, "get_spectrum_by_scan", get_one)
    _install_no_full_load_guards(monkeypatch)
    session = object()

    out = spectrum_facade.get_match_ms2(
        session,  # type: ignore[arg-type]
        {"dataset_id": 39},
        _match(),
    )

    assert find_calls == [(session, 39, 10, 92.46, 477.3051452636719, 0.5)]
    assert read_calls == [(session, 39, 10, 67726)]
    assert out.scan == 67726
    assert out.ms_level == 2
    assert len(out.matched_ions) >= 10


def test_match_ms2_explicit_rt_uses_unbounded_nearest_scan_index_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    max_deltas: list[float | None] = []

    def find_one(*_args: Any, max_delta_minutes: float | None) -> ScanMetadata:
        max_deltas.append(max_delta_minutes)
        return _scan_metadata(67726, ms_level=2, retention_time=92.48)

    monkeypatch.setattr(spectrum_facade, "find_nearest_ms2_scan", find_one)
    monkeypatch.setattr(
        spectrum_facade,
        "get_spectrum_by_scan",
        lambda *_args: (_ms2_spec(67726), False),
    )
    _install_no_full_load_guards(monkeypatch)

    out = spectrum_facade.get_match_ms2(
        None,  # type: ignore[arg-type]
        {"dataset_id": 39},
        _match(),
        rt=92.46,
    )

    assert max_deltas == [None]
    assert out.scan == 67726


def test_match_ms2_passes_modified_sequence_to_fragment_matcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, Any] = {}
    match = _match()
    match["sequence"] = "ACDE"
    match["modified_sequence"] = "AC(UniMod:4)DE"

    def capture_match(**kwargs: Any):
        received.update(kwargs)
        return []

    monkeypatch.setattr(
        spectrum_facade,
        "get_spectrum_by_scan",
        lambda *_args: (_ms2_spec(67726), False),
    )
    monkeypatch.setattr(spectrum_facade, "match_by_ions", capture_match)

    out = spectrum_facade.get_match_ms2(
        None,  # type: ignore[arg-type]
        {"dataset_id": 39},
        match,
        scan=67726,
    )

    assert received["sequence"] == "ACDE"
    assert received["modified_sequence"] == "AC(UniMod:4)DE"
    assert out.annotation_status == "modified"
    assert out.annotation_warnings == []


def test_match_ms2_keeps_raw_spectrum_but_skips_unsafe_modified_annotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _ms2_spec(67726)
    match = _match()
    match["modified_sequence"] = "LLL[UniMod:4]PGELAK"
    monkeypatch.setattr(
        spectrum_facade,
        "get_spectrum_by_scan",
        lambda *_args: (spec, False),
    )

    out = spectrum_facade.get_match_ms2(
        None,  # type: ignore[arg-type]
        {"dataset_id": 39},
        match,
        scan=67726,
    )

    assert out.mz == spec["mz"]
    assert out.intensity == spec["intensity"]
    assert out.matched_ions == []
    assert out.annotation_status == "unsupported_modification"
    assert len(out.annotation_warnings) == 1
    assert "modified_sequence_invalid" in out.annotation_warnings[0]


def test_match_ms2_marks_missing_modified_sequence_without_hiding_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    match = _match()
    match.pop("modified_sequence")
    monkeypatch.setattr(
        spectrum_facade,
        "get_spectrum_by_scan",
        lambda *_args: (_ms2_spec(67726), False),
    )

    out = spectrum_facade.get_match_ms2(
        None,  # type: ignore[arg-type]
        {"dataset_id": 39},
        match,
        scan=67726,
    )

    assert len(out.matched_ions) >= 10
    assert out.annotation_status == "modification_data_missing"
    assert "Stripped.Sequence only" in out.annotation_warnings[0]


def test_match_ms2_without_explicit_scan_reports_no_candidate_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_candidate(*_args: Any, **_kwargs: Any) -> ScanMetadata:
        raise ScanMetadataNotFoundError("ms2_scan_not_found")

    monkeypatch.setattr(spectrum_facade, "find_nearest_ms2_scan", no_candidate)
    monkeypatch.setattr(spectrum_facade, "get_spectrum_by_scan", _fail)
    _install_no_full_load_guards(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        spectrum_facade.get_match_ms2(None, {"dataset_id": 39}, _match())  # type: ignore[arg-type]

    assert exc.value.status_code == 404
    assert exc.value.detail["error"] == "ms2_scan_not_found"


def test_match_ms2_without_explicit_scan_rejects_ms1_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        spectrum_facade,
        "find_nearest_ms2_scan",
        lambda *_args, **_kwargs: _scan_metadata(101, ms_level=2, retention_time=92.45),
    )
    monkeypatch.setattr(
        spectrum_facade,
        "get_spectrum_by_scan",
        lambda *_args: ({**_ms2_spec(101), "ms_level": 1}, False),
    )
    _install_no_full_load_guards(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        spectrum_facade.get_match_ms2(None, {"dataset_id": 39}, _match())  # type: ignore[arg-type]

    assert exc.value.status_code == 404
    assert exc.value.detail == "ms2_scan_not_found"


@pytest.mark.parametrize(
    "source",
    ["query", "resolved_scan", "ms2_scan", "match_scan"],
)
def test_match_ms2_explicit_scan_uses_indexed_reader_only(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    expected_scan = 67720
    match = _match()
    query_scan = None
    if source == "query":
        query_scan = expected_scan
    elif source == "match_scan":
        match["scan_number"] = expected_scan
    else:
        match["extra_metadata"][source] = expected_scan

    calls: list[tuple[Any, int, int, int]] = []

    def get_one(session: Any, dataset_id: int, run_id: int, scan_number: int):
        calls.append((session, dataset_id, run_id, scan_number))
        return _ms2_spec(scan_number), False

    monkeypatch.setattr(spectrum_facade, "get_spectrum_by_scan", get_one)
    monkeypatch.setattr(spectrum_facade, "find_nearest_ms2_scan", _fail)
    _install_no_full_load_guards(monkeypatch)

    session = object()
    out = spectrum_facade.get_match_ms2(
        session,  # type: ignore[arg-type]
        {"dataset_id": 39},
        match,
        scan=query_scan,
    )

    assert calls == [(session, 39, 10, expected_scan)]
    assert out.scan == expected_scan
    assert out.ms_level == 2
    assert len(out.matched_ions) >= 10


def test_match_ms2_explicit_scan_rejects_ms1_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        spectrum_facade,
        "get_spectrum_by_scan",
        lambda *_args: ({**_ms2_spec(67720), "ms_level": 1}, False),
    )
    monkeypatch.setattr(spectrum_facade, "get_run_spectra", _fail)

    with pytest.raises(HTTPException) as exc:
        spectrum_facade.get_match_ms2(
            None,  # type: ignore[arg-type]
            {"dataset_id": 39},
            _match(),
            scan=67720,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "ms2_scan_not_found"


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (SpectrumNotFoundError("scan not found"), 404),
        (MzmlFileNotFoundError("mzML not found"), 404),
        (MzmlMappingError("cannot map run"), 409),
        (UnsupportedMzmlError("embedded index required"), 422),
        (MzmlIndexError("corrupted index"), 500),
    ],
)
def test_match_ms2_explicit_scan_maps_indexed_reader_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
) -> None:
    def raise_error(*_args: Any, **_kwargs: Any):
        raise error

    monkeypatch.setattr(spectrum_facade, "get_spectrum_by_scan", raise_error)
    monkeypatch.setattr(spectrum_facade, "get_run_spectra", _fail)

    with pytest.raises(HTTPException) as exc:
        spectrum_facade.get_match_ms2(
            None,  # type: ignore[arg-type]
            {"dataset_id": 39},
            _match(),
            scan=67720,
        )

    assert exc.value.status_code == expected_status
    assert exc.value.detail == str(error)


def test_bruker_match_ms2_is_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spectrum_facade, "find_nearest_ms2_scan", _fail)
    monkeypatch.setattr(spectrum_facade, "get_spectrum_by_scan", _fail)
    with pytest.raises(HTTPException) as exc:
        spectrum_facade.get_match_ms2(None, {"dataset_id": 39}, _match(raw_format="bruker_d"))  # type: ignore[arg-type]

    assert exc.value.status_code == 404
    assert exc.value.detail == "unsupported_raw_format"


def test_match_ms1_uses_scan_index_and_indexed_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    find_calls: list[tuple[Any, int, int, float, float]] = []
    read_calls: list[tuple[Any, int, int, int]] = []

    def find_one(
        session: Any,
        dataset_id: int,
        run_id: int,
        rt: float,
        window_minutes: float,
    ) -> ScanMetadata:
        find_calls.append((session, dataset_id, run_id, rt, window_minutes))
        return _scan_metadata(101, ms_level=1, retention_time=92.45)

    def get_one(session: Any, dataset_id: int, run_id: int, scan_number: int):
        read_calls.append((session, dataset_id, run_id, scan_number))
        return {
            "scan": scan_number,
            "native_id": f"scan={scan_number}",
            "ms_level": 1,
            "rt_seconds": 92.45 * 60.0,
            "mz": [477.305, 600.0],
            "intensity": [1000.0, 2000.0],
        }, False

    monkeypatch.setattr(spectrum_facade, "find_nearest_ms1_scan", find_one)
    monkeypatch.setattr(spectrum_facade, "get_spectrum_by_scan", get_one)
    _install_no_full_load_guards(monkeypatch)
    session = object()

    out = spectrum_facade.get_match_ms1(
        session,  # type: ignore[arg-type]
        {"dataset_id": 39},
        _match(),
    )

    assert find_calls == [(session, 39, 10, 92.46, 0.25)]
    assert read_calls == [(session, 39, 10, 101)]
    assert out.scan == 101
    assert out.ms_level == 1
    assert out.markers[0].label == "precursor"
    assert out.markers[0].mz == pytest.approx(477.3051452636719)
    assert out.precursor and out.precursor.charge == 2


def test_match_ms1_rejects_ms2_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        spectrum_facade,
        "find_nearest_ms1_scan",
        lambda *_args, **_kwargs: _scan_metadata(101, ms_level=1, retention_time=92.45),
    )
    monkeypatch.setattr(
        spectrum_facade,
        "get_spectrum_by_scan",
        lambda *_args: (_ms2_spec(101), False),
    )
    _install_no_full_load_guards(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        spectrum_facade.get_match_ms1(None, {"dataset_id": 39}, _match())  # type: ignore[arg-type]

    assert exc.value.status_code == 404
    assert exc.value.detail == "ms1_scan_not_found"


@pytest.mark.parametrize(
    ("error", "error_name"),
    [
        (ScanIndexMissingError("scan_index_missing"), "scan_index_missing"),
        (ScanIndexStaleError("scan_index_stale"), "scan_index_stale"),
    ],
)
@pytest.mark.parametrize("spectrum_kind", ["ms1", "ms2"])
def test_match_spectrum_maps_scan_index_state_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    error_name: str,
    spectrum_kind: str,
) -> None:
    def raise_error(*_args: Any, **_kwargs: Any) -> ScanMetadata:
        raise error

    if spectrum_kind == "ms1":
        monkeypatch.setattr(spectrum_facade, "find_nearest_ms1_scan", raise_error)
    else:
        monkeypatch.setattr(spectrum_facade, "find_nearest_ms2_scan", raise_error)
    monkeypatch.setattr(spectrum_facade, "get_spectrum_by_scan", _fail)
    _install_no_full_load_guards(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        if spectrum_kind == "ms1":
            spectrum_facade.get_match_ms1(None, {"dataset_id": 39}, _match())  # type: ignore[arg-type]
        else:
            spectrum_facade.get_match_ms2(None, {"dataset_id": 39}, _match())  # type: ignore[arg-type]

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == error_name
    assert exc.value.detail["backfill_command"] == (
        "python scripts/backfill_mzml_scan_indexes.py --dataset-id 39 --run-id 10"
    )


def test_bruker_match_ms1_is_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spectrum_facade, "find_nearest_ms1_scan", _fail)
    monkeypatch.setattr(spectrum_facade, "get_spectrum_by_scan", _fail)
    with pytest.raises(HTTPException) as exc:
        spectrum_facade.get_match_ms1(None, {"dataset_id": 39}, _match(raw_format="bruker_d"))  # type: ignore[arg-type]

    assert exc.value.status_code == 404
    assert exc.value.detail == "unsupported_raw_format"


def test_xic_uses_ms1_points_in_expanded_rt_window(monkeypatch: pytest.MonkeyPatch) -> None:
    spectra = {
        idx: {
            "scan": idx,
            "ms_level": 1,
            "rt_seconds": rt_min * 60.0,
            "mz": [477.304, 600.0],
            "intensity": [float(idx), 1.0],
        }
        for idx, rt_min in enumerate([87.2, 92.2, 92.8, 98.0], start=1)
    }
    monkeypatch.setattr(
        xic_service,
        "find_ms1_scans_in_rt_range",
        lambda *_args: [
            _scan_metadata(scan, ms_level=1, retention_time=spec["rt_seconds"] / 60.0)
            for scan, spec in spectra.items()
        ],
    )
    monkeypatch.setattr(
        xic_service,
        "get_spectrum_by_scan",
        lambda _session, _dataset_id, _run_id, scan: (spectra[scan], False),
    )
    _install_no_full_load_guards(monkeypatch)

    out = xic_service.get_match_xic(None, {"dataset_id": 39}, _match(), ppm=10)  # type: ignore[arg-type]

    assert out.unit_rt == "min"
    assert out.rt_start == 92.15
    assert out.rt_stop == 93.08
    assert out.rt == [87.2, 92.2, 92.8, 98.0]
    assert out.intensity[1] > 0


def test_bruker_match_xic_is_unsupported() -> None:
    with pytest.raises(HTTPException) as exc:
        xic_service.get_match_xic(None, {"dataset_id": 39}, _match(raw_format="bruker_d"))  # type: ignore[arg-type]

    assert exc.value.status_code == 404
    assert exc.value.detail == "unsupported_raw_format"


def test_product_xic_uses_matching_ms2_window_and_returns_zero_for_missing_peak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_mz = 175.119
    spectra = {
        1: {
            **_ms2_spec(1),
            "rt_seconds": 92.15 * 60.0,
            "mz": [product_mz + product_mz * 19e-6, product_mz - product_mz * 10e-6],
            "intensity": [5200.0, 6100.0],
        },
        2: {
            **_ms2_spec(2),
            "rt_seconds": 92.46 * 60.0,
            "mz": [product_mz + product_mz * 21e-6],
            "intensity": [9999.0],
        },
        3: {
            **_ms2_spec(3),
            "rt_seconds": 92.50 * 60.0,
            "precursor": {"target_mz": 600.0, "lower_offset": 5.0, "upper_offset": 5.0},
            "mz": [product_mz],
            "intensity": [12000.0],
        },
    }
    monkeypatch.setattr(
        product_xic_service,
        "find_product_xic_ms2_scans",
        lambda *_args: [
            _scan_metadata(scan, ms_level=2, retention_time=spec["rt_seconds"] / 60.0)
            for scan, spec in spectra.items()
            if scan != 3
        ],
    )
    monkeypatch.setattr(
        product_xic_service,
        "get_spectrum_by_scan",
        lambda _session, _dataset_id, _run_id, scan: (spectra[scan], False),
    )
    _install_no_full_load_guards(monkeypatch)

    out = product_xic_service.get_match_product_xic(
        None, {"dataset_id": 39}, _match(), product_mz=product_mz, ppm=20  # type: ignore[arg-type]
    )

    assert out.curve_type == "PRODUCT_ION_XIC"
    assert out.isolation_filter is True
    assert [point.scan for point in out.points] == [1, 2]
    assert [point.intensity for point in out.points] == [6100.0, 0.0]


def test_product_xic_ppm_tolerance_is_inclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    product_mz = 500.0
    tolerance = product_mz * 20e-6
    spectra = {
        1: {
            **_ms2_spec(1),
            "rt_seconds": 92.46 * 60.0,
            "mz": [product_mz - tolerance, product_mz + tolerance + 1e-6],
            "intensity": [7000.0, 9000.0],
        }
    }
    monkeypatch.setattr(
        product_xic_service,
        "find_product_xic_ms2_scans",
        lambda *_args: [_scan_metadata(1, ms_level=2, retention_time=92.46)],
    )
    monkeypatch.setattr(
        product_xic_service,
        "get_spectrum_by_scan",
        lambda *_args: (spectra[1], False),
    )
    _install_no_full_load_guards(monkeypatch)

    out = product_xic_service.get_match_product_xic(
        None, {"dataset_id": 39}, _match(), product_mz=product_mz, ppm=20  # type: ignore[arg-type]
    )

    assert out.points[0].intensity == 7000.0


def test_bruker_product_xic_is_unsupported() -> None:
    with pytest.raises(HTTPException) as exc:
        product_xic_service.get_match_product_xic(
            None, {"dataset_id": 39}, _match(raw_format="bruker_d"), product_mz=175.119  # type: ignore[arg-type]
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "unsupported_raw_format"


def _batch_ion(ion_id: str, mz: float) -> BuProductXicBatchIonIn:
    return BuProductXicBatchIonIn(
        id=ion_id,
        ion=ion_id.split("|", 1)[0],
        series="y",
        position=5,
        charge=1,
        mz=mz,
    )


def test_product_xic_batch_loads_spectra_once_and_keeps_no_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    signal_mz = 175.119
    spectra = {
        1: {
            **_ms2_spec(1),
            "rt_seconds": 92.15 * 60.0,
            "mz": [signal_mz],
            "intensity": [6100.0],
        },
        2: {
            **_ms2_spec(2),
            "rt_seconds": 92.46 * 60.0,
            "mz": [signal_mz + 0.1],
            "intensity": [9999.0],
        },
    }

    monkeypatch.setattr(
        product_xic_service,
        "find_product_xic_ms2_scans",
        lambda *_args: [
            _scan_metadata(1, ms_level=2, retention_time=92.15),
            _scan_metadata(2, ms_level=2, retention_time=92.46),
        ],
    )

    def get_one(_session: Any, _dataset_id: int, _run_id: int, scan: int):
        calls.append(scan)
        return spectra[scan], False

    monkeypatch.setattr(product_xic_service, "get_spectrum_by_scan", get_one)
    _install_no_full_load_guards(monkeypatch)
    request = BuProductXicBatchIn(
        tolerance_ppm=20,
        ions=[
            _batch_ion("y5|1|175.119", signal_mz),
            _batch_ion("y6|1|250", 250.0),
        ],
    )

    out = product_xic_service.get_match_product_xics(
        None, {"dataset_id": 39}, _match(), request  # type: ignore[arg-type]
    )

    assert calls == [1, 2]
    assert [trace.id for trace in out.traces] == ["y5|1|175.119", "y6|1|250"]
    assert out.traces[0].status == "ok"
    assert [point.intensity for point in out.traces[0].points] == [6100.0, 0.0]
    assert out.traces[1].status == "no_signal"
    assert [point.intensity for point in out.traces[1].points] == [0.0, 0.0]


def test_product_xic_batch_rt_window_override(monkeypatch: pytest.MonkeyPatch) -> None:
    product_mz = 175.119
    spectra = {
        1: {**_ms2_spec(1), "rt_seconds": 92.15 * 60.0, "mz": [product_mz], "intensity": [100.0]},
        2: {**_ms2_spec(2), "rt_seconds": 92.46 * 60.0, "mz": [product_mz], "intensity": [200.0]},
    }
    find_calls: list[tuple[float, float]] = []

    def find_scans(
        _session: Any,
        _dataset_id: int,
        _run_id: int,
        rt_start: float,
        rt_end: float,
        _precursor_mz: float,
    ):
        find_calls.append((rt_start, rt_end))
        return [_scan_metadata(2, ms_level=2, retention_time=92.46)]

    monkeypatch.setattr(product_xic_service, "find_product_xic_ms2_scans", find_scans)
    monkeypatch.setattr(
        product_xic_service,
        "get_spectrum_by_scan",
        lambda *_args: (spectra[2], False),
    )
    _install_no_full_load_guards(monkeypatch)
    request = BuProductXicBatchIn(
        ions=[_batch_ion("y5|1|175.119", product_mz)],
        rt_window=BuProductXicRtWindowIn(start=92.4, end=92.5),
    )

    out = product_xic_service.get_match_product_xics(
        None, {"dataset_id": 39}, _match(), request  # type: ignore[arg-type]
    )

    assert [point.scan for point in out.traces[0].points] == [2]
    assert find_calls == [(92.4, 92.5)]


@pytest.mark.parametrize(
    "ions",
    [
        [],
        [_batch_ion(f"y{index}|1|{100 + index}", 100.0 + index) for index in range(9)],
    ],
)
def test_product_xic_batch_rejects_invalid_ion_count(
    ions: list[BuProductXicBatchIonIn],
) -> None:
    with pytest.raises(ValueError):
        BuProductXicBatchIn(ions=ions)


def test_product_xic_batch_rejects_invalid_mz_and_rt_window() -> None:
    with pytest.raises(ValueError):
        _batch_ion("y5|1|-1", -1)
    with pytest.raises(ValueError):
        BuProductXicRtWindowIn(start=93.0, end=92.0)


def test_bruker_product_xic_batch_is_unsupported() -> None:
    request = BuProductXicBatchIn(ions=[_batch_ion("y5|1|175.119", 175.119)])
    with pytest.raises(HTTPException) as exc:
        product_xic_service.get_match_product_xics(
            None,
            {"dataset_id": 39},
            _match(raw_format="bruker_d"),
            request,
        )  # type: ignore[arg-type]

    assert exc.value.status_code == 404
    assert exc.value.detail == "unsupported_raw_format"


def test_product_xic_batch_route_matches_old_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_mz = 175.119
    spectra = {
        1: {
            **_ms2_spec(1),
            "rt_seconds": 92.46 * 60.0,
            "mz": [product_mz],
            "intensity": [6100.0],
        }
    }
    monkeypatch.setattr(matches_api, "require_bu_dataset", lambda *_args: {"dataset_id": 39})
    monkeypatch.setattr(matches_api, "require_bu_match", lambda *_args: _match())
    monkeypatch.setattr(
        product_xic_service,
        "find_product_xic_ms2_scans",
        lambda *_args: [_scan_metadata(1, ms_level=2, retention_time=92.46)],
    )
    monkeypatch.setattr(
        product_xic_service,
        "get_spectrum_by_scan",
        lambda *_args: (spectra[1], False),
    )
    request = BuProductXicBatchIn(
        tolerance_ppm=20,
        ions=[_batch_ion("y5|1|175.119", product_mz)],
    )
    batch = matches_api.match_product_xics("demo", 1, request, None)  # type: ignore[arg-type]
    old_get = matches_api.match_product_xic(
        "demo", 1, product_mz, 20, None  # type: ignore[arg-type]
    )

    assert batch.traces[0].id == "y5|1|175.119"
    assert batch.traces[0].points == old_get.points
    assert old_get.curve_type == "PRODUCT_ION_XIC"


def test_chromatogram_accepts_bruker_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chromatogram_service, "get_binary_chromatogram", lambda *_args: None)
    monkeypatch.setattr(
        chromatogram_service,
        "_run_row",
        lambda *_args: {"run_id": 11, "file_path": "sample.d", "run_metadata": {"raw_format": "bruker_d"}},
    )
    monkeypatch.setattr(
        chromatogram_service.tdf_chromatogram,
        "get_chromatogram",
        lambda **_kwargs: BuChromatogramOut(type="tic", rt=[1.0], intensity=[2.0], point_count_original=1),
    )

    out = chromatogram_service.get_chromatogram(None, {"dataset_id": 39}, 11, chrom_type="tic")  # type: ignore[arg-type]

    assert out.unit_rt == "min"
    assert out.rt == [1.0]


def test_mobility_slice_rejects_mzml_match() -> None:
    with pytest.raises(HTTPException) as exc:
        mobility_service.get_match_mobility_slice({"dataset_id": 39}, _match(raw_format="mzml"))

    assert exc.value.status_code == 404
    assert exc.value.detail == "unsupported_raw_format"


def test_mobility_slice_accepts_bruker_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mobility_service.tdf_mobility_slice,
        "get_mobility_slice",
        lambda **_kwargs: BuMobilitySliceOut(mz=[500.0], one_over_k0=[1.1], intensity=[100.0], frame_id=7, rt_min=92.5),
    )

    out = mobility_service.get_match_mobility_slice(
        {"dataset_id": 39},
        {**_match(raw_format="bruker_d"), "file_path": "sample.d"},
    )

    assert out.frame_id == 7
    assert out.mz == [500.0]
