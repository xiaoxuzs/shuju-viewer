from __future__ import annotations

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
