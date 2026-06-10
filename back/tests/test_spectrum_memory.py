from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from app.spectrum_memory.contracts import MzmlBundleSpec, MzmlRunFileSpec
from app.spectrum_memory.eviction_coordinator import EvictionCoordinator
from app.spectrum_memory.lru_mru_queue import DatasetMruQueue
from app.spectrum_memory.size_accounting import pre_load_reserve_bytes
from app.spectrum_memory.types import CapacityError, NotResidentError, Residency


def test_dataset_mru_queue_lru_is_leftmost_after_touches() -> None:
    q = DatasetMruQueue()
    q.touch(1)
    q.touch(2)
    assert q.pop_lru() == 1
    assert q.pop_lru() == 2
    assert q.pop_lru() is None


def test_dataset_mru_queue_touch_moves_to_mru() -> None:
    q = DatasetMruQueue()
    q.touch(1)
    q.touch(2)
    q.touch(1)
    assert q.pop_lru() == 2
    assert q.pop_lru() == 1


def test_pre_load_reserve_scales_with_file_size(tmp_path: Path) -> None:
    p = tmp_path / "x.mzML"
    p.write_bytes(b"0" * 300_000)
    spec = MzmlBundleSpec(
        dataset_id=1,
        runs=(MzmlRunFileSpec(run_id=1, mzml_path=p),),
    )
    r1 = pre_load_reserve_bytes(spec)
    p.write_bytes(b"0" * 600_000)
    spec2 = MzmlBundleSpec(
        dataset_id=1,
        runs=(MzmlRunFileSpec(run_id=1, mzml_path=p),),
    )
    r2 = pre_load_reserve_bytes(spec2)
    assert r2 > r1
    assert r1 >= 1024 * 1024


class _FakeBundle:
    __slots__ = ("accounted_bytes", "run_to_spectra", "dataset_id")

    def __init__(self, *, dataset_id: int, accounted_bytes: int, run_to_spectra: dict) -> None:
        self.dataset_id = dataset_id
        self.accounted_bytes = accounted_bytes
        self.run_to_spectra = run_to_spectra


def _fake_load_factory(*, accounted: int) -> object:
    def _load(spec: MzmlBundleSpec) -> _FakeBundle:
        return _FakeBundle(
            dataset_id=spec.dataset_id,
            accounted_bytes=accounted,
            run_to_spectra={1: {42: {"scan": 42, "mz": [100.0], "intensity": [1.0]}}},
        )

    return _load


def _mzml_bundle_mod():
    pytest.importorskip("lxml.etree", reason="pyteomics mzML needs lxml")
    import app.spectrum_memory.mzml_dataset_bundle as mdb

    return mdb


def test_eviction_coordinator_evicts_lru_when_over_budget(tmp_path: Path) -> None:
    mdb = _mzml_bundle_mod()
    p1 = tmp_path / "a.mzML"
    p2 = tmp_path / "b.mzML"
    p1.write_bytes(b"x")
    p2.write_bytes(b"x")
    spec1 = MzmlBundleSpec(dataset_id=101, runs=(MzmlRunFileSpec(run_id=1, mzml_path=p1),))
    spec2 = MzmlBundleSpec(dataset_id=102, runs=(MzmlRunFileSpec(run_id=1, mzml_path=p2),))

    coord = EvictionCoordinator()
    coord._max = 500

    with (
        patch("app.spectrum_memory.eviction_coordinator.pre_load_reserve_bytes", return_value=50),
        patch.object(
            mdb.DatasetMzmlBundle,
            "load",
            side_effect=_fake_load_factory(accounted=300),
        ),
    ):
        coord.ensure_dataset_resident(spec1)
        coord.ensure_dataset_resident(spec2)

    assert coord.residency_of(101) == Residency.ABSENT
    assert coord.residency_of(102) == Residency.READY
    assert coord._current_total == 300


def test_eviction_coordinator_hit_is_idempotent_and_keeps_resident(tmp_path: Path) -> None:
    mdb = _mzml_bundle_mod()
    p = tmp_path / "c.mzML"
    p.write_bytes(b"x")
    spec = MzmlBundleSpec(dataset_id=201, runs=(MzmlRunFileSpec(run_id=1, mzml_path=p),))

    coord = EvictionCoordinator()
    coord._max = 10_000

    with (
        patch("app.spectrum_memory.eviction_coordinator.pre_load_reserve_bytes", return_value=50),
        patch.object(
            mdb.DatasetMzmlBundle,
            "load",
            side_effect=_fake_load_factory(accounted=200),
        ),
    ):
        coord.ensure_dataset_resident(spec)
        coord.ensure_dataset_resident(spec)

    assert coord.residency_of(201) == Residency.READY
    assert coord._current_total == 200


def test_eviction_coordinator_get_spectrum_raises_when_absent() -> None:
    coord = EvictionCoordinator()
    coord._max = 10_000
    with pytest.raises(NotResidentError):
        coord.get_mzml_spectrum(999, run_id=1, scan_number=1)


def test_eviction_coordinator_get_spectrum_hit(tmp_path: Path) -> None:
    mdb = _mzml_bundle_mod()
    p = tmp_path / "d.mzML"
    p.write_bytes(b"x")
    spec = MzmlBundleSpec(dataset_id=301, runs=(MzmlRunFileSpec(run_id=1, mzml_path=p),))

    coord = EvictionCoordinator()
    coord._max = 10_000

    with (
        patch("app.spectrum_memory.eviction_coordinator.pre_load_reserve_bytes", return_value=50),
        patch.object(
            mdb.DatasetMzmlBundle,
            "load",
            side_effect=_fake_load_factory(accounted=200),
        ),
    ):
        coord.ensure_dataset_resident(spec)

    out = coord.get_mzml_spectrum(301, run_id=1, scan_number=42)
    assert out is not None
    assert out["scan"] == 42


def test_eviction_coordinator_get_run_spectra_hit(tmp_path: Path) -> None:
    mdb = _mzml_bundle_mod()
    p = tmp_path / "run-map.mzML"
    p.write_bytes(b"x")
    spec = MzmlBundleSpec(dataset_id=302, runs=(MzmlRunFileSpec(run_id=1, mzml_path=p),))

    coord = EvictionCoordinator()
    coord._max = 10_000

    with (
        patch("app.spectrum_memory.eviction_coordinator.pre_load_reserve_bytes", return_value=50),
        patch.object(
            mdb.DatasetMzmlBundle,
            "load",
            side_effect=_fake_load_factory(accounted=200),
        ),
    ):
        coord.ensure_dataset_resident(spec)

    spectra = coord.get_mzml_run_spectra(302, run_id=1)
    assert spectra is not None
    assert spectra[42]["scan"] == 42


def test_eviction_coordinator_release_drops_and_frees_accounting(tmp_path: Path) -> None:
    mdb = _mzml_bundle_mod()
    p = tmp_path / "e.mzML"
    p.write_bytes(b"x")
    spec = MzmlBundleSpec(dataset_id=401, runs=(MzmlRunFileSpec(run_id=1, mzml_path=p),))

    coord = EvictionCoordinator()
    coord._max = 10_000

    with (
        patch("app.spectrum_memory.eviction_coordinator.pre_load_reserve_bytes", return_value=50),
        patch.object(
            mdb.DatasetMzmlBundle,
            "load",
            side_effect=_fake_load_factory(accounted=250),
        ),
    ):
        coord.ensure_dataset_resident(spec)

    assert coord._current_total == 250
    coord.release_dataset(401)
    assert coord.residency_of(401) == Residency.ABSENT
    assert coord._current_total == 0


def test_eviction_coordinator_single_dataset_exceeds_max_raises(tmp_path: Path) -> None:
    mdb = _mzml_bundle_mod()
    p = tmp_path / "huge.mzML"
    p.write_bytes(b"x")
    spec = MzmlBundleSpec(dataset_id=501, runs=(MzmlRunFileSpec(run_id=1, mzml_path=p),))

    coord = EvictionCoordinator()
    coord._max = 100

    with (
        patch("app.spectrum_memory.eviction_coordinator.pre_load_reserve_bytes", return_value=50),
        patch.object(
            mdb.DatasetMzmlBundle,
            "load",
            side_effect=_fake_load_factory(accounted=500),
        ),
    ):
        with pytest.raises(CapacityError):
            coord.ensure_dataset_resident(spec)

    assert coord.residency_of(501) == Residency.ABSENT


def test_concurrent_same_dataset_loads_once(tmp_path: Path) -> None:
    mdb = _mzml_bundle_mod()
    path = tmp_path / "single-flight.mzML"
    path.write_bytes(b"x")
    spec = MzmlBundleSpec(dataset_id=601, runs=(MzmlRunFileSpec(run_id=1, mzml_path=path),))
    coord = EvictionCoordinator()
    coord._max = 10_000
    load_started = threading.Event()
    release_load = threading.Event()
    call_count = 0
    call_count_lock = threading.Lock()

    def load(current_spec: MzmlBundleSpec) -> _FakeBundle:
        nonlocal call_count
        with call_count_lock:
            call_count += 1
        load_started.set()
        assert release_load.wait(timeout=2)
        return _fake_load_factory(accounted=200)(current_spec)

    def ensure_and_get() -> dict[int, dict]:
        coord.ensure_dataset_resident(spec)
        spectra = coord.get_mzml_run_spectra(601, run_id=1)
        assert spectra is not None
        return spectra

    with (
        patch("app.spectrum_memory.eviction_coordinator.pre_load_reserve_bytes", return_value=50),
        patch.object(mdb.DatasetMzmlBundle, "load", side_effect=load),
        ThreadPoolExecutor(max_workers=4) as pool,
    ):
        futures = [pool.submit(ensure_and_get) for _ in range(4)]
        assert load_started.wait(timeout=1)
        assert coord.residency_of(601) == Residency.LOADING
        release_load.set()
        results = [future.result(timeout=2) for future in futures]

    assert call_count == 1
    assert all(result is results[0] for result in results)
    assert coord.residency_of(601) == Residency.READY


def test_different_dataset_loads_can_overlap(tmp_path: Path) -> None:
    mdb = _mzml_bundle_mod()
    path1 = tmp_path / "overlap-a.mzML"
    path2 = tmp_path / "overlap-b.mzML"
    path1.write_bytes(b"x")
    path2.write_bytes(b"x")
    spec1 = MzmlBundleSpec(dataset_id=701, runs=(MzmlRunFileSpec(run_id=1, mzml_path=path1),))
    spec2 = MzmlBundleSpec(dataset_id=702, runs=(MzmlRunFileSpec(run_id=1, mzml_path=path2),))
    coord = EvictionCoordinator()
    coord._max = 10_000
    both_started = threading.Event()
    release_loads = threading.Event()
    started: set[int] = set()
    started_lock = threading.Lock()

    def load(current_spec: MzmlBundleSpec) -> _FakeBundle:
        with started_lock:
            started.add(current_spec.dataset_id)
            if len(started) == 2:
                both_started.set()
        assert release_loads.wait(timeout=2)
        return _fake_load_factory(accounted=200)(current_spec)

    with (
        patch("app.spectrum_memory.eviction_coordinator.pre_load_reserve_bytes", return_value=50),
        patch.object(mdb.DatasetMzmlBundle, "load", side_effect=load),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        future1 = pool.submit(coord.ensure_dataset_resident, spec1)
        future2 = pool.submit(coord.ensure_dataset_resident, spec2)
        assert both_started.wait(timeout=1)
        assert coord.residency_of(701) == Residency.LOADING
        assert coord.residency_of(702) == Residency.LOADING
        release_loads.set()
        future1.result(timeout=2)
        future2.result(timeout=2)

    assert started == {701, 702}
    assert coord.residency_of(701) == Residency.READY
    assert coord.residency_of(702) == Residency.READY


def test_failed_dataset_load_releases_waiters_and_clears_loading(tmp_path: Path) -> None:
    mdb = _mzml_bundle_mod()
    path = tmp_path / "failed-single-flight.mzML"
    path.write_bytes(b"x")
    spec = MzmlBundleSpec(dataset_id=801, runs=(MzmlRunFileSpec(run_id=1, mzml_path=path),))
    coord = EvictionCoordinator()
    coord._max = 10_000
    load_started = threading.Event()
    release_failure = threading.Event()
    failure = RuntimeError("mzML parse failed")
    attempts = 0

    def load(current_spec: MzmlBundleSpec) -> _FakeBundle:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            load_started.set()
            assert release_failure.wait(timeout=2)
            raise failure
        return _fake_load_factory(accounted=200)(current_spec)

    with (
        patch("app.spectrum_memory.eviction_coordinator.pre_load_reserve_bytes", return_value=50),
        patch.object(mdb.DatasetMzmlBundle, "load", side_effect=load),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        loader = pool.submit(coord.ensure_dataset_resident, spec)
        assert load_started.wait(timeout=1)
        waiter = pool.submit(coord.ensure_dataset_resident, spec)
        assert coord.residency_of(801) == Residency.LOADING
        release_failure.set()

        with pytest.raises(RuntimeError) as loader_exc:
            loader.result(timeout=2)
        with pytest.raises(RuntimeError) as waiter_exc:
            waiter.result(timeout=2)

        assert loader_exc.value is failure
        assert waiter_exc.value is failure
        assert coord.residency_of(801) == Residency.ABSENT

        coord.ensure_dataset_resident(spec)

    assert attempts == 2
    assert coord.residency_of(801) == Residency.READY
